"""A small, generic client for querying ArcGIS REST FeatureServer/MapServer layers.

Deliberately thin: it only knows how to ask ArcGIS REST endpoints for JSON
metadata and GeoJSON features over HTTP. It does not know anything about
TxDOT-specific fields -- callers inspect metadata before assuming field
names exist (see acquisition.inspect).
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass
from typing import Any

import requests

from txdot_overlay.logging_setup import get_logger

logger = get_logger(__name__)


class ArcGISRequestError(RuntimeError):
    """Raised when an ArcGIS REST endpoint returns an error or unexpected payload."""


class ArcGISIncompleteResultError(ArcGISRequestError):
    """Every request succeeded, but the assembled result is not the complete,
    duplicate-free set of features the service reports for the query."""


# At most this many duplicate object IDs are named in an error message.
_MAX_REPORTED_DUPLICATES = 5


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
        try:
            return int(payload["count"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ArcGISRequestError(
                f"{self.layer_url}: count query for where={where!r} returned no usable "
                f"count: {payload!r}"
            ) from exc

    def query_geojson_page(
        self,
        *,
        where: str = "1=1",
        out_fields: str = "*",
        result_offset: int = 0,
        result_record_count: int | None = None,
        return_geometry: bool = True,
        order_by_fields: str | None = None,
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
        if order_by_fields is not None:
            params["orderByFields"] = order_by_fields
        return self._get(f"{self.layer_url}/query", params)

    def query_geojson_all(
        self,
        *,
        object_id_field: str,
        where: str = "1=1",
        out_fields: str = "*",
        page_size: int = 2000,
        return_geometry: bool = True,
    ) -> dict[str, Any]:
        """Page through every matching feature and return one merged,
        verified-complete FeatureCollection.

        1. Ask the service how many features match (`count(where)`, once).
        2. Page with `resultOffset`, ordered by `object_id_field` ascending so
           offsets address a stable sequence. Stop when the running total
           reaches that count, or on an empty page.
        3. Require the fetched total to equal the count, and every feature's
           object ID to be present and unique. Otherwise raise
           ArcGISIncompleteResultError -- never return a partial result, so a
           caller that caches only on success (DiskCache.get_or_fetch) can
           never store one.

        The offset advances by the number of features actually returned,
        never by the requested `page_size`: a service may silently cap each
        page below what was requested via its own (possibly smaller)
        `maxRecordCount` -- confirmed live for `TxDOT_City_Boundaries`
        (`maxRecordCount=1000` while this project's configured page size is
        2000). Advancing by `page_size` would skip records, and treating a
        short page as the end would under-fetch.

        `exceededTransferLimit` is deliberately not consulted: the count is
        the authoritative completion signal, and where that flag appears in
        a GeoJSON response varies by server.

        ArcGIS is a live service; the count and the pages are separate
        requests. An edit landing between them shows up as a count mismatch
        or duplicate IDs and fails the fetch, to be retried by a later run.
        """
        expected_count = self.count(where)
        all_features: list[dict[str, Any]] = []
        offset = 0
        # At least one page is always requested, so features on a layer whose
        # count claims zero still surface as a mismatch.
        while True:
            page = self.query_geojson_page(
                where=where,
                out_fields=out_fields,
                result_offset=offset,
                result_record_count=page_size,
                return_geometry=return_geometry,
                order_by_fields=f"{object_id_field} ASC",
            )
            features = page.get("features", [])
            if not features:
                break
            all_features.extend(features)
            offset += len(features)
            if len(all_features) >= expected_count:
                break

        context = f"{self.layer_url} (where={where!r})"
        if len(all_features) != expected_count:
            raise ArcGISIncompleteResultError(
                f"{context}: incomplete result -- service count reports {expected_count} "
                f"feature(s), pagination returned {len(all_features)}"
            )
        _check_unique_object_ids(all_features, object_id_field, context)

        logger.info(
            "%s: fetched %d/%d feature(s), unique %s",
            context,
            len(all_features),
            expected_count,
            object_id_field,
        )
        return {"type": "FeatureCollection", "features": all_features}


def _check_unique_object_ids(
    features: list[dict[str, Any]], object_id_field: str, context: str
) -> None:
    object_ids = [(f.get("properties") or {}).get(object_id_field) for f in features]
    missing = sum(1 for object_id in object_ids if object_id is None)
    if missing:
        raise ArcGISIncompleteResultError(
            f"{context}: {missing} feature(s) have no object-ID field {object_id_field!r}"
        )
    duplicates = sorted(
        (object_id for object_id, n in Counter(object_ids).items() if n > 1), key=str
    )
    if duplicates:
        shown = ", ".join(str(d) for d in duplicates[:_MAX_REPORTED_DUPLICATES])
        more = len(duplicates) - _MAX_REPORTED_DUPLICATES
        suffix = f" (+{more} more)" if more > 0 else ""
        raise ArcGISIncompleteResultError(
            f"{context}: {len(duplicates)} duplicate {object_id_field} value(s): {shown}{suffix}"
        )
