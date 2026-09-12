"""Fetches feature data for a configured source, transparently caching results."""
from __future__ import annotations

from typing import Any

from txdot_overlay.acquisition.arcgis_client import ArcGISLayerClient
from txdot_overlay.acquisition.cache import CacheEntry, DiskCache
from txdot_overlay.config import Config, SourceConfig
from txdot_overlay.logging_setup import get_logger

logger = get_logger(__name__)


def fetch_source_features(
    source: SourceConfig,
    config: Config,
    cache: DiskCache,
    *,
    where: str = "1=1",
    out_fields: str = "*",
    force_refresh: bool = False,
) -> CacheEntry:
    """Fetch a GeoJSON FeatureCollection for `source`, using the disk cache when fresh."""
    cache_key = f"{source.key}__{where}__{out_fields}"

    def _fetch() -> dict[str, Any]:
        client = ArcGISLayerClient(
            source.layer_url,
            timeout_seconds=config.network_timeout_seconds,
            max_retries=config.network_max_retries,
            retry_backoff_seconds=config.network_retry_backoff_seconds,
        )
        return client.query_geojson_all(
            where=where,
            out_fields=out_fields,
            page_size=config.network_page_size,
        )

    max_age = 0.0 if force_refresh else config.cache_max_age_hours
    entry = cache.get_or_fetch(
        cache_key,
        source_url=f"{source.layer_url}/query",
        params={"where": where, "outFields": out_fields},
        max_age_hours=max_age,
        fetch_fn=_fetch,
    )
    feature_count = len(entry.data.get("features", []))
    logger.info("%s: %d feature(s) (where=%s)", source.label, feature_count, where)
    return entry
