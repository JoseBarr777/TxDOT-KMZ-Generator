import geopandas as gpd
import pytest
from shapely.geometry import LineString

from txdot_overlay.processing.classify import (
    GRADE_SEPARATED_CONNECTOR_STYLE_KEY,
    PhysicalRoadType,
    classify_physical_type,
    classify_route_style,
    classify_routes,
    is_grade_separated_connector,
)


def test_is_grade_separated_connector_true_for_gs():
    assert is_grade_separated_connector("GS") is True
    assert is_grade_separated_connector("gs") is True
    assert is_grade_separated_connector(" GS ") is True


@pytest.mark.parametrize("rdbd_id", ["AG", "KG", "LG", "RG", "XG", None, float("nan")])
def test_is_grade_separated_connector_false_for_everything_else(rdbd_id):
    assert is_grade_separated_connector(rdbd_id) is False


def test_classify_physical_type_grade_separated_connector_wins_regardless_of_hsys():
    # A GS connector on an Interstate must not be classified as a physical
    # state highway -- this is the core "not classified as physical state
    # highways" requirement.
    result = classify_physical_type(hsys="IH", rdbd_id="GS")
    assert result == PhysicalRoadType.GRADE_SEPARATED_CONNECTOR


@pytest.mark.parametrize(
    "hsys",
    ["IH", "US", "SH", "FM", "RM", "SL", "SS", "BU", "PR", "SA", "PA", "UA", "FS", "RS"],
)
def test_classify_physical_type_state_highway_system(hsys):
    assert classify_physical_type(hsys=hsys, rdbd_id="KG") == PhysicalRoadType.STATE_HIGHWAY_SYSTEM


def test_classify_physical_type_county_road():
    assert classify_physical_type(hsys="CR", rdbd_id="KG") == PhysicalRoadType.COUNTY_ROAD


def test_classify_physical_type_local_street():
    assert classify_physical_type(hsys="LS", rdbd_id="KG") == PhysicalRoadType.LOCAL_STREET


@pytest.mark.parametrize("hsys", ["FD", "TL"])
def test_classify_physical_type_other_physical_roadway(hsys):
    assert classify_physical_type(hsys=hsys, rdbd_id="KG") == PhysicalRoadType.OTHER_PHYSICAL_ROADWAY


@pytest.mark.parametrize("hsys", [None, float("nan"), "", "ZZ"])
def test_classify_physical_type_unknown(hsys):
    assert classify_physical_type(hsys=hsys, rdbd_id="KG") == PhysicalRoadType.UNKNOWN


def test_classify_route_style_grade_separated_connector_ignores_hsys(config):
    style = classify_route_style(hsys="US", rdbd_id="GS", config=config)
    assert style == GRADE_SEPARATED_CONNECTOR_STYLE_KEY
    assert style != config.route_category("US")


def test_classify_route_style_physical_road_uses_config_mapping(config):
    assert classify_route_style(hsys="IH", rdbd_id="KG", config=config) == "interstate"
    assert classify_route_style(hsys="CR", rdbd_id="KG", config=config) == "county_local_other"


def test_classify_routes_adds_both_columns(config):
    road_fields = config.sources["roadways"].fields
    gdf = gpd.GeoDataFrame(
        {
            road_fields["highway_system"]: ["IH", "CR", "US"],
            road_fields["roadbed_id"]: ["KG", "KG", "GS"],
            "geometry": [LineString([(0, 0), (1, 1)])] * 3,
        },
        crs="EPSG:4326",
    )
    result = classify_routes(gdf, config)
    assert list(result["physical_type"]) == [
        PhysicalRoadType.STATE_HIGHWAY_SYSTEM.value,
        PhysicalRoadType.COUNTY_ROAD.value,
        PhysicalRoadType.GRADE_SEPARATED_CONNECTOR.value,
    ]
    assert list(result["route_category"]) == [
        "interstate",
        "county_local_other",
        "grade_separated_connector",
    ]


# --- Terminology safety: GS is decoded, not asserted equivalent to "artificial centerline" --


def test_classification_module_does_not_claim_artificial_centerline_synonymy():
    """Regression guard: no code identifier, enum value, or config key may
    still assert the retired "artificial_centerline" name as the
    classification itself -- that would claim GS and "Artificial
    Centerline" are synonymous, which no official current TxDOT source
    supports. The module's docstrings may still *discuss* the retired term
    as history (see the module docstring and processing/codes.py), so this
    checks identifiers/values, not prose mentions.
    """
    from txdot_overlay.processing import classify as classify_module

    assert not hasattr(classify_module, "ARTIFICIAL_CENTERLINE_STYLE_KEY")
    assert not hasattr(classify_module, "ARTIFICIAL_CENTERLINE_RDBD_ID")
    assert not hasattr(classify_module, "is_artificial_centerline")
    assert "ARTIFICIAL_CENTERLINE" not in PhysicalRoadType.__members__
    assert "artificial_centerline" not in {t.value for t in PhysicalRoadType}
    assert GRADE_SEPARATED_CONNECTOR_STYLE_KEY == "grade_separated_connector"


# --- Misleading "TxDOT-maintained" label safety ---------------------------------


def test_classification_module_never_asserts_txdot_maintained_label():
    """Regression guard: classification must never produce a "TxDOT-maintained"
    label from HSYS/physical-type alone -- only codes.is_maintained_by_state_highway_agency,
    driven by the verified RDWAY_MAINT_AGCY field, may answer a maintenance question."""
    import inspect

    from txdot_overlay.processing import classify as classify_module

    source = inspect.getsource(classify_module)
    assert "txdot-maintained" not in source.lower()
    assert "txdot maintained" not in source.lower()
