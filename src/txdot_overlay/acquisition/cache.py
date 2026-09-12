"""Local disk cache for ArcGIS query results, preserving source URL and fetch time.

Each cache entry is a single JSON file containing:
    {
        "_meta": {"source_url": ..., "params": {...}, "retrieved_at": "<ISO8601 UTC>"},
        "data": {<the raw GeoJSON or JSON response>}
    }
so downstream consumers always know where a dataset came from and how old it is.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from txdot_overlay.logging_setup import get_logger

logger = get_logger(__name__)


@dataclass
class CacheEntry:
    source_url: str
    params: dict[str, Any]
    retrieved_at: datetime
    data: dict[str, Any]

    def is_stale(self, max_age_hours: float) -> bool:
        age = datetime.now(timezone.utc) - self.retrieved_at
        return age > timedelta(hours=max_age_hours)


class DiskCache:
    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _key_to_path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
        safe_prefix = "".join(c if c.isalnum() else "_" for c in key)[:60]
        return self.cache_dir / f"{safe_prefix}_{digest}.json"

    def get(self, key: str) -> CacheEntry | None:
        path = self._key_to_path(key)
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
            meta = payload["_meta"]
            return CacheEntry(
                source_url=meta["source_url"],
                params=meta.get("params", {}),
                retrieved_at=datetime.fromisoformat(meta["retrieved_at"]),
                data=payload["data"],
            )
        except (json.JSONDecodeError, KeyError, OSError) as exc:
            logger.warning("Ignoring unreadable cache entry %s: %s", path, exc)
            return None

    def set(
        self, key: str, *, source_url: str, params: dict[str, Any], data: dict[str, Any]
    ) -> CacheEntry:
        entry = CacheEntry(
            source_url=source_url,
            params=params,
            retrieved_at=datetime.now(timezone.utc),
            data=data,
        )
        path = self._key_to_path(key)
        payload = {
            "_meta": {
                "source_url": entry.source_url,
                "params": entry.params,
                "retrieved_at": entry.retrieved_at.isoformat(),
            },
            "data": entry.data,
        }
        with path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        return entry

    def get_or_fetch(
        self,
        key: str,
        *,
        source_url: str,
        params: dict[str, Any],
        max_age_hours: float,
        fetch_fn,
    ) -> CacheEntry:
        """Return a fresh cache entry, calling fetch_fn() -> dict only on miss/stale."""
        cached = self.get(key)
        if cached is not None and not cached.is_stale(max_age_hours):
            logger.info(
                "Cache hit for %s (fetched %s)", key, cached.retrieved_at.isoformat()
            )
            return cached
        logger.info("Cache miss/stale for %s; fetching from %s", key, source_url)
        data = fetch_fn()
        return self.set(key, source_url=source_url, params=params, data=data)
