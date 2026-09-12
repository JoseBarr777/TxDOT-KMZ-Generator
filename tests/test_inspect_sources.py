import responses

from txdot_overlay.acquisition.inspect import inspect_source, list_service_layers
from txdot_overlay.config import SourceConfig

SERVICE_URL = "https://example.test/arcgis/rest/services/Fake_Layer/FeatureServer"
LAYER_URL = f"{SERVICE_URL}/0"


def _source() -> SourceConfig:
    return SourceConfig(
        key="fake",
        label="Fake Layer",
        service_url=SERVICE_URL,
        layer_id=0,
        fields={"name": "NAME", "number": "NUM"},
        description_fields=["NAME", "NUM"],
    )


@responses.activate
def test_inspect_source_reports_present_and_missing_fields():
    responses.add(
        responses.GET,
        SERVICE_URL,
        json={
            "layers": [{"id": 0, "name": "Fake_Layer"}],
            "tables": [],
        },
        status=200,
    )
    responses.add(
        responses.GET,
        LAYER_URL,
        json={
            "name": "Fake_Layer",
            "geometryType": "esriGeometryPolygon",
            "fields": [
                {"name": "OBJECTID", "type": "esriFieldTypeOID"},
                {"name": "NAME", "type": "esriFieldTypeString"},
                # Note: "NUM" is deliberately absent to exercise the missing-field path.
            ],
            "maxRecordCount": 1000,
            "supportedQueryFormats": "JSON, geoJSON",
            "extent": {"spatialReference": {"wkid": 4326, "latestWkid": 4326}},
        },
        status=200,
    )
    responses.add(
        responses.GET,
        f"{LAYER_URL}/query",
        json={"count": 42},
        status=200,
    )

    inspection = inspect_source(_source())

    assert inspection.record_count == 42
    assert inspection.metadata.geometry_type == "esriGeometryPolygon"
    assert inspection.metadata.max_record_count == 1000
    assert inspection.metadata.spatial_reference_wkid == 4326
    assert inspection.metadata.supported_query_formats == ["JSON", "geoJSON"]
    assert inspection.configured_fields_present == {"name": True, "number": False}
    assert inspection.missing_configured_fields == ["number"]


@responses.activate
def test_list_service_layers_includes_layers_and_tables():
    responses.add(
        responses.GET,
        SERVICE_URL,
        json={
            "layers": [{"id": 0, "name": "Roads"}],
            "tables": [{"id": 1, "name": "Lookup"}],
        },
        status=200,
    )
    summaries = list_service_layers(SERVICE_URL)
    assert [(s.layer_id, s.name, s.layer_type) for s in summaries] == [
        (0, "Roads", "layer"),
        (1, "Lookup", "table"),
    ]


@responses.activate
def test_inspect_source_all_fields_present():
    responses.add(
        responses.GET,
        SERVICE_URL,
        json={"layers": [{"id": 0, "name": "Fake_Layer"}], "tables": []},
        status=200,
    )
    responses.add(
        responses.GET,
        LAYER_URL,
        json={
            "name": "Fake_Layer",
            "geometryType": "esriGeometryPolygon",
            "fields": [
                {"name": "NAME", "type": "esriFieldTypeString"},
                {"name": "NUM", "type": "esriFieldTypeInteger"},
            ],
            "maxRecordCount": 2000,
            "supportedQueryFormats": "JSON",
            "extent": {"spatialReference": {"wkid": 3857}},
        },
        status=200,
    )
    responses.add(responses.GET, f"{LAYER_URL}/query", json={"count": 5}, status=200)

    inspection = inspect_source(_source())
    assert inspection.missing_configured_fields == []
