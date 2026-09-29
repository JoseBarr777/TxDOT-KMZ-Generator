"""Freshness semantics of the GIS source disk cache (acquisition/cache.py) and
the force-refresh path through acquisition/fetch.py.

Exercises the real DiskCache in a temporary directory with fake fetch
functions; ArcGISLayerClient is replaced by a fake, so nothing touches the
network. The key release guarantee pinned here: a failed fetch is always an
error -- stale cached data is never returned in its place.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from txdot_overlay.acquisition import fetch
from txdot_overlay.acquisition.cache import DiskCache

KEY = "districts__1=1__*"
SOURCE_URL = "https://example.test/arcgis/rest/services/Fake/FeatureServer/0/query"
PARAMS = {"where": "1=1", "outFields": "*"}
MAX_AGE_HOURS = 168.0


def _collection(tag):
    return {"type": "FeatureCollection", "features": [{"properties": {"tag": tag}}]}


class Fetcher:
    """Fake fetch_fn: returns (or raises) and counts calls."""

    def __init__(self, result=None, exc=None):
        self.result = result
        self.exc = exc
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        return self.result


def _only_cache_file(cache_dir):
    (path,) = [p for p in cache_dir.iterdir() if p.suffix == ".json"]
    return path


def _age_entry(cache_dir, hours):
    """Backdate the single cache entry's retrieved_at, instead of sleeping."""
    path = _only_cache_file(cache_dir)
    payload = json.loads(path.read_text(encoding="utf-8"))
    backdated = datetime.now(timezone.utc) - timedelta(hours=hours)
    payload["_meta"]["retrieved_at"] = backdated.isoformat()
    path.write_text(json.dumps(payload), encoding="utf-8")
    return backdated


def _get_or_fetch(cache, fetcher, max_age_hours=MAX_AGE_HOURS):
    return cache.get_or_fetch(
        KEY,
        source_url=SOURCE_URL,
        params=PARAMS,
        max_age_hours=max_age_hours,
        fetch_fn=fetcher,
    )


@pytest.fixture
def cache(tmp_path):
    return DiskCache(tmp_path / "cache")


def test_miss_fetches_and_records_provenance(cache):
    fetcher = Fetcher(result=_collection("new"))
    before = datetime.now(timezone.utc)
    entry = _get_or_fetch(cache, fetcher)

    assert fetcher.calls == 1
    assert entry.data == _collection("new")
    payload = json.loads(_only_cache_file(cache.cache_dir).read_text(encoding="utf-8"))
    assert payload["data"] == _collection("new")
    assert payload["_meta"]["source_url"] == SOURCE_URL
    assert payload["_meta"]["params"] == PARAMS
    assert datetime.fromisoformat(payload["_meta"]["retrieved_at"]) >= before


def test_fresh_hit_does_not_fetch(cache):
    cache.set(KEY, source_url=SOURCE_URL, params=PARAMS, data=_collection("cached"))
    _age_entry(cache.cache_dir, hours=MAX_AGE_HOURS - 1)
    fetcher = Fetcher(result=_collection("new"))

    entry = _get_or_fetch(cache, fetcher)

    assert fetcher.calls == 0
    assert entry.data == _collection("cached")


def test_stale_entry_is_refetched_and_rewritten(cache):
    cache.set(KEY, source_url=SOURCE_URL, params=PARAMS, data=_collection("old"))
    backdated = _age_entry(cache.cache_dir, hours=MAX_AGE_HOURS + 1)
    fetcher = Fetcher(result=_collection("new"))

    entry = _get_or_fetch(cache, fetcher)

    assert fetcher.calls == 1
    assert entry.data == _collection("new")
    reread = cache.get(KEY)
    assert reread.data == _collection("new")
    assert reread.retrieved_at > backdated


def test_corrupt_entry_is_a_miss_and_is_replaced(cache):
    cache.set(KEY, source_url=SOURCE_URL, params=PARAMS, data=_collection("old"))
    _only_cache_file(cache.cache_dir).write_text("{not json", encoding="utf-8")
    assert cache.get(KEY) is None

    fetcher = Fetcher(result=_collection("new"))
    entry = _get_or_fetch(cache, fetcher)

    assert fetcher.calls == 1
    assert entry.data == _collection("new")
    assert cache.get(KEY).data == _collection("new")


def test_fetch_failure_never_falls_back_to_stale_data(cache):
    # Release guarantee: a source-fetch failure must fail the build, not
    # quietly become publication of the stale cached copy.
    cache.set(KEY, source_url=SOURCE_URL, params=PARAMS, data=_collection("stale"))
    backdated = _age_entry(cache.cache_dir, hours=MAX_AGE_HOURS + 1)
    fetcher = Fetcher(exc=RuntimeError("ArcGIS endpoint unavailable"))

    with pytest.raises(RuntimeError, match="ArcGIS endpoint unavailable"):
        _get_or_fetch(cache, fetcher)

    assert fetcher.calls == 1
    # The stale entry is left as it was -- not refreshed, not deleted.
    left = cache.get(KEY)
    assert left.data == _collection("stale")
    assert left.retrieved_at == backdated


# --- Application path: fetch_source_features ---------------------------------


class FakeLayerClient:
    """Stands in for ArcGISLayerClient; records queries, never touches the network."""

    calls = 0
    result = _collection("remote")
    exc = None

    def __init__(self, layer_url, **kwargs):
        self.layer_url = layer_url

    def query_geojson_all(self, *, where, out_fields, page_size):
        FakeLayerClient.calls += 1
        if FakeLayerClient.exc is not None:
            raise FakeLayerClient.exc
        return FakeLayerClient.result


@pytest.fixture
def fake_client(monkeypatch):
    FakeLayerClient.calls = 0
    FakeLayerClient.result = _collection("remote")
    FakeLayerClient.exc = None
    monkeypatch.setattr(fetch, "ArcGISLayerClient", FakeLayerClient)
    return FakeLayerClient


def test_force_refresh_refetches_an_otherwise_fresh_entry(config, cache, fake_client):
    source = config.sources["districts"]

    fetch.fetch_source_features(source, config, cache)
    assert fake_client.calls == 1

    # Fresh under the configured TTL: reused.
    fetch.fetch_source_features(source, config, cache)
    assert fake_client.calls == 1

    # force_refresh -> max_age 0: refetched and written back.
    fake_client.result = _collection("refreshed")
    entry = fetch.fetch_source_features(source, config, cache, force_refresh=True)
    assert fake_client.calls == 2
    assert entry.data == _collection("refreshed")

    # ...and a later default call reuses the refreshed entry (as the
    # post-build release commands do).
    entry = fetch.fetch_source_features(source, config, cache)
    assert fake_client.calls == 2
    assert entry.data == _collection("refreshed")


def test_source_fetch_failure_propagates_despite_stale_cache(config, cache, fake_client):
    source = config.sources["districts"]
    fetch.fetch_source_features(source, config, cache)
    _age_entry(cache.cache_dir, hours=config.cache_max_age_hours + 1)

    fake_client.exc = RuntimeError("Request failed after 3 attempts")
    with pytest.raises(RuntimeError, match="failed after 3 attempts"):
        fetch.fetch_source_features(source, config, cache)
