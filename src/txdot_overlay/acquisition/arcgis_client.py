"""A small, generic client for querying ArcGIS REST FeatureServer/MapServer layers.

Deliberately thin: it only knows how to ask ArcGIS REST endpoints for JSON
metadata and GeoJSON features over HTTP. It does not know anything about
TxDOT-specific fields -- callers inspect metadata before assuming field
names exist (see acquisition.inspect).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import requests

from txdot_overlay.logging_setup import get_logger

logger = get_logger(__name__)


class ArcGISRequestError(RuntimeError):
    """Raised when an ArcGIS REST endpoint returns an error or unexpected payload."""


@dataclass
class LayerMetadata:
    """Subset of ArcGIS layer metadata this project cares about."""

    name: str
    geometry_type: str | None
    fields: list[dict[str, Any]]
    max_record_count: int | None
    supported_query_formats: list[str]
    spatial_reference_wkid: int | None
    source_url: str
    raw: dict[str, Any]

    @property
    def field_names(self) -> list[str]:
        return [f["name"] for f in self.fields]


class ArcGISLayerClient:
    """Talks to a single ArcGIS REST layer, e.g. `.../FeatureServer/0`."""

    def __init__(
        self,
        layer_url: str,
        *,
        timeout_seconds: float = 30.0,
        max_retries: int = 3,
        retry_backoff_seconds: float = 2.0,
        session: requests.Session | None = None,
    ) -> None:
        self.layer_url = layer_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self.session = session or requests.Session()

    def _get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout_seconds)
                response.raise_for_status()
                payload = response.json()
                if isinstance(payload, dict) and "error" in payload:
                    raise ArcGISRequestError(f"ArcGIS error from {url}: {payload['error']}")
                return payload
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                logger.warning(
                    "Request to %s failed (attempt %d/%d): %s",
                    url,
                    attempt,
                    self.max_retries,
                    exc,
                )
                if attempt < self.max_retries:
                    time.sleep(self.retry_backoff_seconds * attempt)
        raise ArcGISRequestError(
            f"Request to {url} failed after {self.max_retries} attempts: {last_error}"
        ) from last_error

    def get_metadata(self) -> LayerMetadata:
        """Fetch layer-level metadata (fields, geometry type, spatial reference)."""
        payload = self._get(self.layer_url, {"f": "json"})
        extent_sr = (payload.get("extent") or {}).get("spatialReference") or {}
        formats_raw = payload.get("supportedQueryFormats", "")
        formats = [f.strip() for f in formats_raw.split(",") if f.strip()]
        return LayerMetadata(
            name=payload.get("name", ""),
            geometry_type=payload.get("geometryType"),
            fields=payload.get("fields", []),
            max_record_count=payload.get("maxRecordCount"),
            supported_query_formats=formats,
            spatial_reference_wkid=extent_sr.get("latestWkid") or extent_sr.get("wkid"),
            source_url=self.layer_url,
            raw=payload,
        )

    def count(self, where: str = "1=1") -> int:
        payload = self._get(
            f"{self.layer_url}/query",
            {"where": where, "returnCountOnly": "true", "f": "json"},
        )
        return int(payload["count"])

    def query_geojson_page(
        self,
        *,
        where: str = "1=1",
        out_fields: str = "*",
        result_offset: int = 0,
        result_record_count: int | None = None,
        return_geometry: bool = True,
    ) -> dict[str, Any]:
        """Fetch a single page of features as a GeoJSON FeatureCollection.

        ArcGIS REST returns GeoJSON already reprojected to WGS84 (EPSG:4326)
        per the GeoJSON spec (RFC 7946), regardless of the layer's native
        spatial reference.
        """
        params: dict[str, Any] = {
            "where": where,
            "outFields": out_fields,
            "returnGeometry": "true" if return_geometry else "false",
            "resultOffset": result_offset,
            "f": "geojson",
        }
        if result_record_count is not None:
            params["resultRecordCount"] = result_record_count
        return self._get(f"{self.layer_url}/query", params)

    def query_geojson_all(
        self,
        *,
        where: str = "1=1",
        out_fields: str = "*",
        page_size: int = 2000,
        return_geometry: bool = True,
    ) -> dict[str, Any]:
        """Page through every matching feature, returning one merged FeatureCollection.

        Stops only on an empty page, and advances the offset by the number
        of features actually returned -- never by the requested `page_size`.
        A service may silently cap the returned count below what was
        requested via its own (possibly smaller) `maxRecordCount`: confirmed
        live for `TxDOT_City_Boundaries` (`maxRecordCount=1000` while this
        project's configured page size is 2000). Treating "fewer features
        than requested" as an end-of-data signal under-fetches in that case
        (silently missing the remainder of the layer), and advancing the
        offset by the requested page_size rather than the actual count would
        additionally skip records on the next page.
        """
        all_features: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = self.query_geojson_page(
                where=where,
                out_fields=out_fields,
                result_offset=offset,
                result_record_count=page_size,
                return_geometry=return_geometry,
            )
            features = page.get("features", [])
            if not features:
                break
            all_features.extend(features)
            offset += len(features)
        return {"type": "FeatureCollection", "features": all_features}
