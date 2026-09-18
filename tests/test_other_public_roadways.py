"""Tests for the "Other Public Roadways" branch of the county hierarchy.

Covers the explicit requirements: off-system roadways (county roads, city
streets, RMA-maintained roads, and everything else off-system) are pulled
out of "TxDOT Roadways" into a sibling "Other Public Roadways" folder,
bucketed by HSYS/RDWAY_MAINT_AGCY per processing/classify.py's
classify_other_public_roadway_category, in the fixed order County Roads ->
City Streets -> Regional Mobility Authority Roads -> Other / Unclassified.
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
        {name: [] for name in fields.values()} | {"geometry": []}, crs="EPSG:4326"
    )


def _sample_roadways(config):
    fields = config.sources["roadways"].fields
    gdf = gpd.GeoDataFrame(
        {
            fields["highway_full"]: ["IH0020", None, None, None, None],
            fields["highway_system"]: ["IH", "CR", "LS", "TL", "TL"],
            fields["roadbed_id"]: ["KG"] * 5,
            fields["street_name"]: [None, "County Road 1", "Main St", None, None],
            fields["route_id"]: [None, None, None, "RTE-TL-RMA", "RTE-TL-OTHER"],
            fields["maintenance_agency"]: [1, 2, 4, 16, 17],
            "geometry": [
                LineString([(-95.3, 32.1), (-95.2, 32.1)]),
                LineString([(-95.3, 32.2), (-95.2, 32.2)]),
                LineString([(-95.3, 32.3), (-95.2, 32.3)]),
                LineString([(-95.3, 32.4), (-95.2, 32.4)]),
                LineString([(-95.3, 32.15), (-95.2, 32.15)]),
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
    return ET.fromstring(kml.kml())


def _find_folder(root, name, within=None):
    search_root = within if within is not None else root
    for folder in search_root.iter(f"{KML_NS}Folder"):
        name_el = folder.find(f"{KML_NS}name")
        if name_el is not None and name_el.text == name:
            return folder
    return None


def _direct_child_folders(folder):
    return [f for f in folder.findall(f"{KML_NS}Folder")]


def test_other_public_roadways_is_sibling_not_nested_in_txdot_roadways(config):
    root = _build_kml(config)
    txdot_folder = _find_folder(root, "TxDOT Roadways")
    other_public_folder = _find_folder(root, "Other Public Roadways")
    assert txdot_folder is not None
    assert other_public_folder is not None
    assert _find_folder(txdot_folder, "Other Public Roadways") is None
    assert _find_folder(other_public_folder, "TxDOT Roadways") is None


def test_only_on_system_road_appears_under_txdot_roadways(config):
    root = _build_kml(config)
    txdot_folder = _find_folder(root, "TxDOT Roadways")
    interstate_folder = _find_folder(root, "Interstate", within=txdot_folder)
    assert interstate_folder is not None
    assert len(interstate_folder.findall(f"{KML_NS}Placemark")) == 1
    # No off-system category folders should appear under TxDOT Roadways.
    assert _find_folder(txdot_folder, "County Roads") is None
    assert _find_folder(txdot_folder, "City Streets") is None


def test_county_road_and_city_street_bucketed_by_hsys(config):
    root = _build_kml(config)
    other_public_folder = _find_folder(root, "Other Public Roadways")
    county_roads_folder = _find_folder(root, "County Roads", within=other_public_folder)
    city_streets_folder = _find_folder(root, "City Streets", within=other_public_folder)
    assert len(county_roads_folder.findall(f"{KML_NS}Placemark")) == 1
    assert len(city_streets_folder.findall(f"{KML_NS}Placemark")) == 1


def test_rma_maintained_off_system_road_bucketed_separately_from_other_toll_road(config):
    root = _build_kml(config)
    other_public_folder = _find_folder(root, "Other Public Roadways")
    rma_folder = _find_folder(root, "Regional Mobility Authority Roads", within=other_public_folder)
    other_unclassified_folder = _find_folder(
        root, "Other / Unclassified", within=other_public_folder
    )
    assert rma_folder is not None
    assert other_unclassified_folder is not None
    # One TL row has RDWAY_MAINT_AGCY=16 (RMA) -> Regional Mobility Authority Roads;
    # the other TL row has RDWAY_MAINT_AGCY=17 (Other) -> Other / Unclassified.
    assert len(rma_folder.findall(f"{KML_NS}Placemark")) == 1
    assert len(other_unclassified_folder.findall(f"{KML_NS}Placemark")) == 1


def test_other_public_roadway_folder_order_matches_hierarchy(config):
    root = _build_kml(config)
    other_public_folder = _find_folder(root, "Other Public Roadways")
    names = [f.find(f"{KML_NS}name").text for f in _direct_child_folders(other_public_folder)]
    assert names == [
        "County Roads",
        "City Streets",
        "Regional Mobility Authority Roads",
        "Other / Unclassified",
    ]
