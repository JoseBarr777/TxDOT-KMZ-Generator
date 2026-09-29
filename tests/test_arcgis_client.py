"""Tests for ArcGISLayerClient's pagination and source-completeness checks.

Pagination regression: TxDOT_City_Boundaries advertises maxRecordCount=1000
while this project's configured page_size is 2000. The original
query_geojson_all() stopped as soon as a page returned fewer features than
the *requested* page_size, and advanced the offset by that requested
page_size rather than the actual count returned -- both wrong when the
server silently caps a request below what was asked for.

Completeness: a paginated fetch must reconcile against the service's own
count for the same `where`, carry unique object IDs, and page in stable
object-ID order. A short, padded or duplicated result raises instead of
being returned (and therefore instead of being cached).

All HTTP is mocked with `responses`; nothing reaches the network.
"""

import pytest
import responses
from responses import matchers

from txdot_overlay.acquisition.arcgis_client import (
    ArcGISIncompleteResultError,
    ArcGISLayerClient,
    ArcGISRequestError,
)

LAYER_URL = "https://example.test/arcgis/rest/services/Fake/FeatureServer/0"
QUERY_URL = f"{LAYER_URL}/query"


def _feature(object_id, field="OBJECTID") -> dict:
    return {
        "type": "Feature",
        "properties": {field: object_id},
        "geometry": {"type": "Point", "coordinates": [0, 0]},
    }


def _page(object_ids, field="OBJECTID") -> dict:
    return {"type": "FeatureCollection", "features": [_feature(i, field) for i in object_ids]}


def _mock_count(count, where="1=1"):
    responses.add(
        responses.GET,
        QUERY_URL,
        json={"count": count},
        match=[
            matchers.query_param_matcher({"where": where, "returnCountOnly": "true", "f": "json"})
        ],
    )


def _mock_page(offset, body, where="1=1", order_by="OBJECTID ASC"):
    responses.add(
        responses.GET,
        QUERY_URL,
        json=body,
        match=[
            matchers.query_param_matcher(
                {
                    "where": where,
                    "outFields": "*",
                    "returnGeometry": "true",
                    "resultOffset": str(offset),
                    "f": "geojson",
                    "resultRecordCount": "2000",
                    "orderByFields": order_by,
                }
            )
        ],
    )


def _client():
    return ArcGISLayerClient(LAYER_URL, max_retries=1)


def _fetch(**kwargs):
    return _client().query_geojson_all(object_id_field="OBJECTID", page_size=2000, **kwargs)


def _calls(kind):
    """kind: 'count' or 'page'."""
    return [
        c for c in responses.calls if ("returnCountOnly=true" in c.request.url) == (kind == "count")
    ]


# --- Complete fetches -----------------------------------------------------------


@responses.activate
def test_paginates_past_a_server_side_cap_below_page_size():
    # Server caps every response at 1000 features regardless of the requested
    # resultRecordCount (2000) -- 1227 total, matching the real
    # TxDOT_City_Boundaries counts observed live.
    _mock_count(1227)
    _mock_page(0, _page(range(1000)))
    _mock_page(1000, _page(range(1000, 1227)))  # offset advanced by 1000 actually returned

    result = _fetch()

    object_ids = [f["properties"]["OBJECTID"] for f in result["features"]]
    assert object_ids == list(range(1227))  # every feature present, none skipped/duplicated
    # Count is asked once per logical query, not per page; paging stops once the
    # count is reached, without a trailing empty-page request.
    assert len(_calls("count")) == 1
    assert len(_calls("page")) == 2


@responses.activate
def test_every_page_is_ordered_by_the_object_id_field():
    _mock_count(1227)
    _mock_page(0, _page(range(1000)))
    _mock_page(1000, _page(range(1000, 1227)))

    _fetch()

    for call in _calls("page"):
        assert call.request.params["orderByFields"] == "OBJECTID ASC"


@responses.activate
def test_single_page_under_page_size_completes():
    _mock_count(254)
    _mock_page(0, _page(range(254)))

    assert len(_fetch()["features"]) == 254


@responses.activate
def test_where_clause_is_used_for_both_count_and_pages():
    _mock_count(3, where="CO = 7")
    _mock_page(0, _page([10, 11, 12]), where="CO = 7")

    assert len(_fetch(where="CO = 7")["features"]) == 3


@responses.activate
def test_zero_record_query_passes_after_confirming_an_empty_page():
    _mock_count(0)
    _mock_page(0, _page([]))

    assert _fetch()["features"] == []
    assert len(_calls("page")) == 1


@responses.activate
def test_object_id_field_is_not_assumed_to_be_objectid():
    _mock_count(2)
    _mock_page(0, _page([1, 2], field="FID"), order_by="FID ASC")

    result = _client().query_geojson_all(object_id_field="FID", page_size=2000)

    assert [f["properties"]["FID"] for f in result["features"]] == [1, 2]


# --- Incomplete fetches fail closed -------------------------------------------


@responses.activate
def test_short_fetch_raises():
    _mock_count(1227)
    _mock_page(0, _page(range(1000)))
    _mock_page(1000, _page([]))  # early empty page: 227 features never arrive

    with pytest.raises(ArcGISIncompleteResultError) as exc:
        _fetch()
    message = str(exc.value)
    assert LAYER_URL in message
    assert "where='1=1'" in message
    assert "1227" in message
    assert "returned 1000" in message


@responses.activate
def test_empty_first_page_with_nonzero_count_raises():
    _mock_count(5)
    _mock_page(0, _page([]))

    with pytest.raises(ArcGISIncompleteResultError, match="reports 5 feature"):
        _fetch()


@responses.activate
def test_features_beyond_the_count_raise():
    _mock_count(2)
    _mock_page(0, _page([1, 2, 3]))

    with pytest.raises(ArcGISIncompleteResultError, match="returned 3"):
        _fetch()


@responses.activate
def test_zero_count_but_features_returned_raises():
    _mock_count(0)
    _mock_page(0, _page([1]))

    with pytest.raises(ArcGISIncompleteResultError):
        _fetch()


@responses.activate
def test_duplicate_object_ids_raise_even_when_the_count_matches():
    # Offset paging over a changing layer can repeat one record and skip
    # another: the total still matches the count.
    _mock_count(4)
    _mock_page(0, _page([1, 2, 2, 4]))

    with pytest.raises(ArcGISIncompleteResultError) as exc:
        _fetch()
    assert "1 duplicate OBJECTID value(s): 2" in str(exc.value)


@responses.activate
def test_many_duplicates_are_summarized():
    _mock_count(14)
    _mock_page(0, _page([i for i in range(7) for _ in range(2)]))

    with pytest.raises(ArcGISIncompleteResultError, match=r"7 duplicate OBJECTID .*\(\+2 more\)"):
        _fetch()


@responses.activate
def test_feature_without_the_object_id_field_raises():
    _mock_count(2)
    page = _page([1, 2])
    del page["features"][1]["properties"]["OBJECTID"]
    _mock_page(0, page)

    with pytest.raises(ArcGISIncompleteResultError, match="no object-ID field 'OBJECTID'"):
        _fetch()


@responses.activate
def test_count_response_without_a_count_raises():
    responses.add(responses.GET, QUERY_URL, json={"objectIds": []})

    with pytest.raises(ArcGISRequestError, match="no usable count"):
        _client().count("1=1")


def test_incomplete_result_is_a_request_error():
    # Existing callers that handle ArcGISRequestError treat it the same way.
    assert issubclass(ArcGISIncompleteResultError, ArcGISRequestError)
