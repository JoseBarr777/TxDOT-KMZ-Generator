"""Tests for the "City Limits" layer and its place in the county hierarchy.

Covers the explicit requirements: City Limits lives under a new
"Administrative Boundaries" folder alongside "County Boundary", defaults to
hidden while its parent stays visible (independently toggleable), and its
popup omits missing fields through the existing values.is_missing_value
normalization system rather than leaking "nan"/"None".
"""

from xml.etree import ElementTree as ET

import geopandas as gpd
from shapely.geometry import LineString, Polygon

from txdot_overlay.export.descriptions import build_city_limits_description_html
from txdot_overlay.export.kml_builder import build_county_detail_kml
from txdot_overlay.export.titles import UNNAMED_CITY_LABEL, resolve_city_limits_title
from txdot_overlay.processing.classify import classify_routes
from txdot_overlay.styling.styles import build_all_styles

KML_NS = "{http://www.opengis.net/kml/2.2}"

COUNTY_POLY = Polygon([(-95.5, 32.0), (-95.0, 32.0), (-95.0, 32.5), (-95.5, 32.5)])


def _sample_roadways(config):
    fields = config.sources["roadways"].fields
    gdf = gpd.GeoDataFrame(
        {
            fields["highway_full"]: ["IH0020"],
            fields["highway_system"]: ["IH"],
            fields["roadbed_id"]: ["KG"],
            fields["street_name"]: [None],
            fields["route_id"]: [None],
            fields["maintenance_agency"]: [1],
            "geometry": [LineString([(-95.3, 32.1), (-95.2, 32.1)])],
        },
        crs="EPSG:4326",
    )
    return classify_routes(gdf, config)


def _sample_city_limits(config):
    fields = config.sources["city_limits"].fields
    gdf = gpd.GeoDataFrame(
        {
            fields["name"]: ["Tyler", None],
            fields["county_seat_flag"]: ["Y", None],
            fields["population_2022"]: [105000, None],
            fields["population_2020"]: [104000, None],
            "geometry": [
                Polygon([(-95.35, 32.1), (-95.25, 32.1), (-95.25, 32.2), (-95.35, 32.2)]),
                Polygon([(-95.15, 32.05), (-95.05, 32.05), (-95.05, 32.15), (-95.15, 32.15)]),
            ],
        },
        crs="EPSG:4326",
    )
    return gdf


def _build_kml(config):
    roadways = _sample_roadways(config)
    city_limits = _sample_city_limits(config)
    styles = build_all_styles(config)
    kml = build_county_detail_kml(
        district_name="Tyler",
        county_name="Smith",
        county_attrs={config.sources["counties"].fields["name"]: "Smith"},
        county_geometry=COUNTY_POLY,
        roadways=roadways,
        city_limits=city_limits,
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


def _is_visible(element) -> bool:
    vis_el = element.find(f"{KML_NS}visibility")
    return vis_el is None or vis_el.text != "0"


def test_administrative_boundaries_wraps_county_boundary_and_city_limits(config):
    root = _build_kml(config)
    admin_folder = _find_folder(root, "Administrative Boundaries")
    assert admin_folder is not None
    assert _find_folder(admin_folder, "County Boundary") is not None
    assert _find_folder(admin_folder, "City Limits") is not None


def test_city_limits_hidden_by_default_while_parent_visible(config):
    root = _build_kml(config)
    admin_folder = _find_folder(root, "Administrative Boundaries")
    city_limits_folder = _find_folder(admin_folder, "City Limits")
    assert _is_visible(admin_folder) is True
    assert _is_visible(city_limits_folder) is False


def test_city_limits_placemarks_present_for_both_rows(config):
    root = _build_kml(config)
    admin_folder = _find_folder(root, "Administrative Boundaries")
    city_limits_folder = _find_folder(admin_folder, "City Limits")
    placemarks = city_limits_folder.findall(f"{KML_NS}Placemark")
    assert len(placemarks) == 2


def test_city_limits_title_falls_back_for_missing_name():
    title, raw = resolve_city_limits_title(city_name=None)
    assert title == UNNAMED_CITY_LABEL
    assert raw is None
    title, raw = resolve_city_limits_title(city_name="Tyler")
    assert title == "Tyler"


def test_city_limits_description_omits_missing_fields(config):
    fields = config.sources["city_limits"].fields
    html = build_city_limits_description_html(
        {
            fields["name"]: "Tyler",
            fields["county_seat_flag"]: None,
            fields["population_2022"]: None,
            fields["population_2020"]: None,
        },
        fields,
    )
    assert "nan" not in html.lower()
    assert "<td>None</td>" not in html
    assert "Tyler" in html
    # No population data present -> no Population section header.
    assert "Population" not in html


def test_city_limits_description_includes_population_and_source(config):
    fields = config.sources["city_limits"].fields
    html = build_city_limits_description_html(
        {
            fields["name"]: "Tyler",
            fields["county_seat_flag"]: "Y",
            fields["population_2022"]: 105000,
        },
        fields,
    )
    assert "Tyler" in html
    assert "105,000" in html or "105000" in html
    assert "Source" in html
