from xml.etree import ElementTree as ET

import geopandas as gpd
from shapely.geometry import Polygon

from txdot_overlay.export.kml_builder import build_master_kml
from txdot_overlay.styling.styles import build_all_styles

KML_NS = "{http://www.opengis.net/kml/2.2}"

DISTRICT_A = Polygon([(-96, 32), (-95, 32), (-95, 33), (-96, 33)])
DISTRICT_B = Polygon([(-97, 32), (-96.5, 32), (-96.5, 32.5), (-97, 32.5)])
COUNTY_A1 = Polygon([(-96, 32), (-95.5, 32), (-95.5, 32.5), (-96, 32.5)])


def _districts_gdf():
    return gpd.GeoDataFrame(
        {
            "DIST_NM": ["Alpha", "Beta"],
            "DIST_NBR": [1, 2],
            "DIST_ABRVN": ["ALP", "BET"],
            "TYPE": ["Rural", "Urban"],
            "geometry": [DISTRICT_A, DISTRICT_B],
        },
        crs="EPSG:4326",
    )


def _counties_gdf():
    return gpd.GeoDataFrame(
        {
            "CNTY_NM": ["Alphaville"],
            "CNTY_FIPS": ["48001"],
            "CNTY_NBR": [1],
            "DIST_NM": ["Alpha"],
            "DIST_NBR": [1],
            "geometry": [COUNTY_A1],
        },
        crs="EPSG:4326",
    )


def _folder(root, name):
    for folder in root.iter(f"{KML_NS}Folder"):
        name_el = folder.find(f"{KML_NS}name")
        if name_el is not None and name_el.text == name:
            return folder
    raise AssertionError(f"Folder {name!r} not found")


def _is_visible(element) -> bool:
    vis_el = element.find(f"{KML_NS}visibility")
    return vis_el is None or vis_el.text != "0"


def _placemark_visibility(folder, name):
    for placemark in folder.findall(f"{KML_NS}Placemark"):
        name_el = placemark.find(f"{KML_NS}name")
        if name_el is not None and name_el.text == name:
            return _is_visible(placemark)
    raise AssertionError(f"Placemark {name!r} not found in folder")


def test_master_kml_default_visibility_matches_config(config):
    styles = build_all_styles(config)
    kml = build_master_kml(_districts_gdf(), _counties_gdf(), config, styles)
    root = ET.fromstring(kml.kml())

    boundaries_folder = _folder(root, "District Boundaries")
    assert _is_visible(boundaries_folder) == config.visibility_defaults[
        "district_boundaries_folder"
    ]
    assert (
        _placemark_visibility(boundaries_folder, "Alpha")
        == config.visibility_defaults["district_placemarks"]
    )

    details_folder = _folder(root, "District Details")
    assert _is_visible(details_folder) == config.visibility_defaults[
        "district_details_folder"
    ]

    alpha_district_folder = _folder(details_folder, "Alpha")
    assert _is_visible(alpha_district_folder) == config.visibility_defaults[
        "district_detail_folder"
    ]

    network_links = alpha_district_folder.findall(f"{KML_NS}NetworkLink")
    assert len(network_links) == 1
    assert _is_visible(network_links[0]) == config.visibility_defaults["county_folder"]


def test_master_kml_networklink_href_is_relative_and_matches_convention(config):
    styles = build_all_styles(config)
    kml = build_master_kml(_districts_gdf(), _counties_gdf(), config, styles)
    root = ET.fromstring(kml.kml())

    href_el = next(root.iter(f"{KML_NS}href"))
    assert href_el.text == "districts/alpha/alphaville.kmz"
    assert not href_el.text.startswith("/")
