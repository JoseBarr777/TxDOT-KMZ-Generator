"""Tests for ArcGISLayerClient's pagination, in particular a server-side
maxRecordCount cap below the configured page size.

Regression coverage for a real bug found while adding the city-limits
source: TxDOT_City_Boundaries advertises maxRecordCount=1000 while this
project's configured page_size is 2000. The original query_geojson_all()
stopped as soon as a page returned fewer features than the *requested*
page_size, and advanced the offset by that requested page_size rather than
the actual count returned -- both wrong when the server silently caps a
request below what was asked for: it under-fetched (dropped every feature
past the first capped page) and would have skipped records had it not
already stopped.
"""

import responses

from txdot_overlay.acquisition.arcgis_client import ArcGISLayerClient

LAYER_URL = "https://example.test/arcgis/rest/services/Fake/FeatureServer/0"


def _feature(object_id: int) -> dict:
    return {
        "type": "Feature",
        "properties": {"OBJECTID": object_id},
        "geometry": {"type": "Point", "coordinates": [0, 0]},
    }


@responses.activate
def test_query_geojson_all_paginates_past_a_server_side_cap_below_page_size():
    # Server caps every response at 1000 features regardless of the
    # requested resultRecordCount (2000) -- 1227 total, matching the real
    # TxDOT_City_Boundaries counts observed live this session.
    first_page = {"type": "FeatureCollection", "features": [_feature(i) for i in range(1000)]}
    second_page = {
        "type": "FeatureCollection",
        "features": [_feature(i) for i in range(1000, 1227)],
    }
    third_page_empty = {"type": "FeatureCollection", "features": []}

    responses.add(
        responses.GET,
        f"{LAYER_URL}/query",
        json=first_page,
        match=[
            responses.matchers.query_param_matcher(
                {
                    "where": "1=1",
                    "outFields": "*",
                    "returnGeometry": "true",
                    "resultOffset": "0",
                    "f": "geojson",
                    "resultRecordCount": "2000",
                }
            )
        ],
    )
    responses.add(
        responses.GET,
        f"{LAYER_URL}/query",
        json=second_page,
        match=[
            responses.matchers.query_param_matcher(
                {
                    "where": "1=1",
                    "outFields": "*",
                    "returnGeometry": "true",
                    "resultOffset": "1000",
                    "f": "geojson",
                    "resultRecordCount": "2000",
                }
            )
        ],
    )
    responses.add(
        responses.GET,
        f"{LAYER_URL}/query",
        json=third_page_empty,
        match=[
            responses.matchers.query_param_matcher(
                {
                    "where": "1=1",
                    "outFields": "*",
                    "returnGeometry": "true",
                    "resultOffset": "1227",
                    "f": "geojson",
                    "resultRecordCount": "2000",
                }
            )
        ],
    )

    client = ArcGISLayerClient(LAYER_URL, max_retries=1)
    result = client.query_geojson_all(page_size=2000)

    assert len(result["features"]) == 1227
    object_ids = [f["properties"]["OBJECTID"] for f in result["features"]]
    assert object_ids == list(range(1227))  # every feature present, none skipped/duplicated


@responses.activate
def test_query_geojson_all_stops_on_empty_page_when_under_page_size():
    single_page = {"type": "FeatureCollection", "features": [_feature(i) for i in range(254)]}
    empty_page = {"type": "FeatureCollection", "features": []}

    responses.add(
        responses.GET,
        f"{LAYER_URL}/query",
        json=single_page,
        match=[
            responses.matchers.query_param_matcher(
                {
                    "where": "1=1",
                    "outFields": "*",
                    "returnGeometry": "true",
                    "resultOffset": "0",
                    "f": "geojson",
                    "resultRecordCount": "2000",
                }
            )
        ],
    )
    responses.add(
        responses.GET,
        f"{LAYER_URL}/query",
        json=empty_page,
        match=[
            responses.matchers.query_param_matcher(
                {
                    "where": "1=1",
                    "outFields": "*",
                    "returnGeometry": "true",
                    "resultOffset": "254",
                    "f": "geojson",
                    "resultRecordCount": "2000",
                }
            )
        ],
    )

    client = ArcGISLayerClient(LAYER_URL, max_retries=1)
    result = client.query_geojson_all(page_size=2000)

    assert len(result["features"]) == 254
