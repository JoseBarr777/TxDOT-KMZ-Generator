"""Tests for grade-separated-connector handling in the exported KML structure.

Covers the explicit requirements: grade-separated connectors (RDBD_ID=GS)
are retained (not dropped), placed under Roadway Network Connectors >
Grade-Separated Connectors, visible by default, and never classified as
physical state highways / never counted as physical roadway features.

Naming note: this category was previously called "artificial centerline."
That name is retired -- see processing/classify.py's module docstring --
because no official current TxDOT source was found asserting that every
GS-coded record is classified by TxDOT as an "Artificial Centerline."

The "Reference Geometry" wrapper folder was itself later renamed to
"Roadway Network Connectors" as part of the county hierarchy restructure
(see docs/SOURCE_AUDIT.md and README.md) -- Grade-Separated Connectors
flipped from hidden-by-default to visible-by-default in that same change.
"""

from xml.etree import ElementTree as ET

import geopandas as gpd
from shapely.geometry import LineString, Polygon

from txdot_overlay.export.kml_builder import build_county_detail_kml
from txdot_overlay.processing.classify import classify_routes
from txdot_overlay.styling.styles import build_all_styles

KML_NS = "{http://www.opengis.net/kml/2.2}"

COUNTY_POLY = Polygon([(-95.5, 32.0), (-95.0, 32.0), (-95.0, 32.5), (-95.5, 32.5)])


def _empty_city_limits(config):
    fields = config.sources["city_limits"].fields
    return gpd.GeoDataFrame(
        {name: [] for name in fields.values()} | {"geometry": []},
        crs="EPSG:4326",
    )


def _sample_roadways(config):
    fields = config.sources["roadways"].fields
    gdf = gpd.GeoDataFrame(
        {
            fields["highway_full"]: ["IH0020", "IH0020"],
            fields["highway_system"]: ["IH", "IH"],
            fields["roadbed_id"]: ["KG", "GS"],  # one physical, one connector
            fields["street_name"]: [None, None],
            fields["route_id"]: ["RTE1", "RTE2"],
            fields["maintenance_agency"]: [1, 1],
            "geometry": [
                LineString([(-95.3, 32.1), (-95.2, 32.1)]),
                LineString([(-95.2, 32.1), (-95.1, 32.1)]),
            ],
        },
        crs="EPSG:4326",
    )
    return classify_routes(gdf, config)


def _build_kml(config):
    roadways = _sample_roadways(config)
    styles = build_all_styles(config)
    kml = build_county_detail_kml(
        district_name="Tyler",
        county_name="Smith",
        county_attrs={config.sources["counties"].fields["name"]: "Smith"},
        county_geometry=COUNTY_POLY,
        roadways=roadways,
        city_limits=_empty_city_limits(config),
        config=config,
        styles=styles,
    )
    return ET.fromstring(kml.kml()), roadways


def _find_folder(root, name, within=None):
    search_root = within if within is not None else root
    for folder in search_root.iter(f"{KML_NS}Folder"):
        name_el = folder.find(f"{KML_NS}name")
        if name_el is not None and name_el.text == name:
            return folder
    return None


def _is_visible(element) -> bool:
    vis_el = element.find(f"{KML_NS}visibility")
    return vis_el is None or vis_el.text != "0"


def test_grade_separated_connector_is_retained_not_dropped(config):
    root, roadways = _build_kml(config)
    # 1 county boundary placemark + 2 roadway placemarks (1 physical, 1 GS
    # connector) -- both roadway records must survive to the rendered KML.
    assert len(root.findall(f".//{KML_NS}Placemark")) == 3


def test_grade_separated_connector_placed_under_roadway_network_connectors_folder(config):
    root, _ = _build_kml(config)
    connectors_folder = _find_folder(root, "Roadway Network Connectors")
    assert connectors_folder is not None
    connector_folder = _find_folder(root, "Grade-Separated Connectors", within=connectors_folder)
    assert connector_folder is not None
    placemarks = connector_folder.findall(f"{KML_NS}Placemark")
    assert len(placemarks) == 1


def test_roadway_network_connectors_and_grade_separated_connectors_visible_by_default(config):
    root, _ = _build_kml(config)
    connectors_folder = _find_folder(root, "Roadway Network Connectors")
    connector_folder = _find_folder(root, "Grade-Separated Connectors", within=connectors_folder)
    assert _is_visible(connectors_folder) is True
    assert _is_visible(connector_folder) is True


def test_grade_separated_connector_not_present_in_interstate_folder(config):
    root, _ = _build_kml(config)
    roadways_folder = _find_folder(root, "TxDOT Roadways")
    interstate_folder = _find_folder(root, "Interstate", within=roadways_folder)
    assert interstate_folder is not None
    # Only the physical (KG) segment belongs here -- the GS connector must not.
    placemarks = interstate_folder.findall(f"{KML_NS}Placemark")
    assert len(placemarks) == 1


def test_physical_roadway_count_excludes_grade_separated_connector(config):
    _, roadways = _build_kml(config)
    physical_count = (roadways["route_category"] != "grade_separated_connector").sum()
    connector_count = (roadways["route_category"] == "grade_separated_connector").sum()
    assert physical_count == 1
    assert connector_count == 1


def test_grade_separated_connector_physical_type_is_not_state_highway_system(config):
    _, roadways = _build_kml(config)
    connector_row = roadways[roadways["route_category"] == "grade_separated_connector"].iloc[0]
    assert connector_row["physical_type"] == "grade_separated_connector"
    assert connector_row["physical_type"] != "state_highway_system"


def test_no_folder_or_style_named_artificial_centerlines(config):
    """Regression guard: the retired folder/label name must not reappear."""
    root, _ = _build_kml(config)
    names = [el.text for el in root.iter(f"{KML_NS}name")]
    assert "Artificial Centerlines" not in names
    assert "Grade-Separated Connectors" in names
