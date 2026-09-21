"""District NetworkLink KMLs and administrative-only boundary artifacts.

The central claim these guard is that a district KML *references* county
data rather than duplicating it, and that the administrative artifacts
carry boundary polygons and no roadway geometry at all.
"""

from __future__ import annotations

import dataclasses
import zipfile
from xml.etree import ElementTree as ET

import geopandas as gpd
import pytest
from shapely.geometry import Polygon

from txdot_overlay.commands.build_distribution import build_distribution_artifacts
from txdot_overlay.export.kml_builder import (
    ADMIN_BOUNDARIES_KMZ,
    CITY_BOUNDARIES_KMZ,
    COUNTY_BOUNDARIES_KMZ,
    DISTRICT_BOUNDARIES_KMZ,
    build_admin_boundaries_kml,
    build_city_boundaries_kml,
    build_county_boundaries_kml,
    build_district_boundaries_kml,
    build_district_kml,
    district_kml_relative_path,
)
from txdot_overlay.styling.colors import hex_to_kml_color
from txdot_overlay.styling.styles import StyleResolver

KML_NS = "{http://www.opengis.net/kml/2.2}"

DISTRICT_ALPHA = Polygon([(-96, 32), (-95, 32), (-95, 33), (-96, 33)])
DISTRICT_BETA = Polygon([(-97, 32), (-96.5, 32), (-96.5, 32.5), (-97, 32.5)])
AREA = Polygon([(-96, 32), (-95.5, 32), (-95.5, 32.5), (-96, 32.5)])


def _districts_gdf():
    return gpd.GeoDataFrame(
        {
            "DIST_NM": ["Alpha", "Beta"],
            "DIST_NBR": [1, 2],
            "DIST_ABRVN": ["ALP", "BET"],
            "TYPE": ["Rural", "Urban"],
            "geometry": [DISTRICT_ALPHA, DISTRICT_BETA],
        },
        crs="EPSG:4326",
    )


def _counties_gdf():
    # Input order is deliberately not alphabetical.
    return gpd.GeoDataFrame(
        {
            "CNTY_NM": ["Zapata", "Wood", "Anderson"],
            "CNTY_FIPS": ["48505", "48499", "48001"],
            "CNTY_NBR": [3, 2, 1],
            "DIST_NM": ["Beta", "Alpha", "Alpha"],
            "DIST_NBR": [2, 1, 1],
            "geometry": [AREA, AREA, AREA],
        },
        crs="EPSG:4326",
    )


def _city_limits_gdf():
    return gpd.GeoDataFrame(
        {
            "OBJECTID": [2, 1],
            "CITY_NM": ["Bellview", "Athens"],
            "CNTY_SEAT_FLAG": ["N", "Y"],
            "POP2022": [200, 100],
            "POP2020": [180, 90],
            "geometry": [AREA, AREA],
        },
        crs="EPSG:4326",
    )


def _root_from_kmz(path):
    with zipfile.ZipFile(path) as zf:
        name = next(n for n in zf.namelist() if n.lower().endswith(".kml"))
        return ET.fromstring(zf.read(name))


def _folders(root):
    """Top-level folders of the document, in document order."""
    document = root.find(f"{KML_NS}Document")
    return document.findall(f"{KML_NS}Folder")


def _folder_named(root, name):
    for folder in root.iter(f"{KML_NS}Folder"):
        name_el = folder.find(f"{KML_NS}name")
        if name_el is not None and name_el.text == name:
            return folder
    raise AssertionError(f"Folder {name!r} not found")


def _names_in(folder, tag):
    return [
        el.find(f"{KML_NS}name").text
        for el in folder.findall(f"{KML_NS}{tag}")
        if el.find(f"{KML_NS}name") is not None
    ]


def _is_visible(element) -> bool:
    vis = element.find(f"{KML_NS}visibility")
    return vis is None or vis.text != "0"


def _count_roadway_geometry(root) -> int:
    """Roadways are the only line geometry this project emits."""
    return len(list(root.iter(f"{KML_NS}LineString")))


@pytest.fixture
def resolver(config):
    return StyleResolver(config)


@pytest.fixture
def alpha_kml(config, resolver):
    counties = _counties_gdf()
    district_row = _districts_gdf().iloc[0]
    return build_district_kml(
        district_name="Alpha",
        district_attrs=district_row.to_dict(),
        district_geometry=district_row.geometry,
        district_counties=counties[counties["DIST_NM"] == "Alpha"],
        config=config,
        style_resolver=resolver,
    )


# --- District NetworkLink KML -------------------------------------------------


def test_district_kml_contains_its_own_boundary(alpha_kml, config):
    root = ET.fromstring(alpha_kml.kml())
    boundary_folder = _folder_named(root, "District Boundary")

    assert _names_in(boundary_folder, "Placemark") == ["Alpha District"]
    assert len(list(boundary_folder.iter(f"{KML_NS}Polygon"))) == 1
    assert _is_visible(boundary_folder)


def test_district_kml_links_only_its_own_counties_in_alphabetical_order(alpha_kml):
    root = ET.fromstring(alpha_kml.kml())
    counties_folder = _folder_named(root, "County Details")

    assert _names_in(counties_folder, "NetworkLink") == ["Anderson", "Wood"]
    assert "Zapata" not in alpha_kml.kml()


def test_district_kml_networklinks_are_relative_to_the_document(alpha_kml):
    root = ET.fromstring(alpha_kml.kml())
    hrefs = [el.text for el in root.iter(f"{KML_NS}href")]

    assert hrefs == ["alpha/anderson.kmz", "alpha/wood.kmz"]
    assert all(not href.startswith("/") for href in hrefs)
    # districts/alpha.kml + "alpha/anderson.kmz" resolves to the real county KMZ.
    base = district_kml_relative_path("Alpha").parent
    assert (base / hrefs[0]).as_posix() == "districts/alpha/anderson.kmz"


def test_district_kml_duplicates_no_roadway_geometry(alpha_kml):
    root = ET.fromstring(alpha_kml.kml())

    assert _count_roadway_geometry(root) == 0
    # One polygon only -- the district boundary; counties arrive by reference.
    assert len(list(root.iter(f"{KML_NS}Polygon"))) == 1


def test_district_kml_county_links_visible_per_config(alpha_kml, config):
    root = ET.fromstring(alpha_kml.kml())
    counties_folder = _folder_named(root, "County Details")
    expected = config.visibility_defaults["district_kml_counties_folder"]

    assert _is_visible(counties_folder) == expected
    for link in counties_folder.findall(f"{KML_NS}NetworkLink"):
        assert _is_visible(link) == expected


# --- Administrative-only artifacts -------------------------------------------


def test_district_boundaries_artifact_has_districts_and_no_roads(config, resolver):
    root = ET.fromstring(build_district_boundaries_kml(_districts_gdf(), config, resolver).kml())
    folder = _folder_named(root, "District Boundaries")

    assert _names_in(folder, "Placemark") == ["Alpha", "Beta"]
    assert _count_roadway_geometry(root) == 0
    assert len(list(root.iter(f"{KML_NS}NetworkLink"))) == 0


def test_county_boundaries_artifact_has_counties_and_no_roads(config, resolver):
    root = ET.fromstring(build_county_boundaries_kml(_counties_gdf(), config, resolver).kml())
    folder = _folder_named(root, "County Boundaries")

    assert _names_in(folder, "Placemark") == ["Anderson County", "Wood County", "Zapata County"]
    assert _count_roadway_geometry(root) == 0


def test_city_boundaries_artifact_has_cities_and_no_roads(config, resolver):
    root = ET.fromstring(build_city_boundaries_kml(_city_limits_gdf(), config, resolver).kml())
    folder = _folder_named(root, "City Limits")

    assert _names_in(folder, "Placemark") == ["Athens", "Bellview"]
    assert _count_roadway_geometry(root) == 0


def test_combined_admin_artifact_has_three_independent_layers(config, resolver):
    kml = build_admin_boundaries_kml(
        _districts_gdf(), _counties_gdf(), _city_limits_gdf(), config, resolver
    )
    root = ET.fromstring(kml.kml())
    folders = _folders(root)

    assert [f.find(f"{KML_NS}name").text for f in folders] == [
        "District Boundaries",
        "County Boundaries",
        "City Limits",
    ]
    # Sibling folders, each independently toggleable, each carrying its own layer.
    assert [len(_names_in(f, "Placemark")) for f in folders] == [2, 3, 2]
    assert _count_roadway_geometry(root) == 0


def test_combined_admin_layer_visibility_matches_the_overlay_defaults(config, resolver):
    kml = build_admin_boundaries_kml(
        _districts_gdf(), _counties_gdf(), _city_limits_gdf(), config, resolver
    )
    root = ET.fromstring(kml.kml())

    assert (
        _is_visible(_folder_named(root, "District Boundaries"))
        == config.visibility_defaults["district_boundaries_folder"]
    )
    assert (
        _is_visible(_folder_named(root, "County Boundaries"))
        == config.visibility_defaults["county_boundary_folder"]
    )
    assert (
        _is_visible(_folder_named(root, "City Limits"))
        == config.visibility_defaults["city_limits_folder"]
    )


def test_admin_artifacts_reuse_the_approved_boundary_styling(config, resolver):
    """Same StyleResolver instances as the full overlay -- no second palette."""
    kml = build_admin_boundaries_kml(
        _districts_gdf(), _counties_gdf(), _city_limits_gdf(), config, resolver
    )
    styles_xml = kml.kml()

    for style_config in (config.district_style, config.county_style, config.city_limits_style):
        assert hex_to_kml_color(style_config.line_color) in styles_xml
        assert hex_to_kml_color(style_config.fill_color, style_config.fill_opacity) in styles_xml


def test_boundary_placemark_styles_are_shared_not_inlined_per_feature(config, resolver):
    """One <Style> per layer, referenced by styleUrl -- not copied per polygon."""
    kml = build_county_boundaries_kml(_counties_gdf(), config, resolver)
    root = ET.fromstring(kml.kml())

    assert len(list(root.iter(f"{KML_NS}Style"))) == 1
    assert len(list(root.iter(f"{KML_NS}styleUrl"))) == 3


# --- End-to-end artifact generation ------------------------------------------


def test_build_distribution_artifacts_writes_the_expected_tree(config, tmp_path, resolver):
    cfg = dataclasses.replace(config, output_dir=tmp_path)

    written = build_distribution_artifacts(
        cfg, _districts_gdf(), _counties_gdf(), _city_limits_gdf(), resolver
    )

    relative = [p.relative_to(tmp_path).as_posix() for p in written]
    assert relative == [
        "districts/alpha.kml",
        "districts/beta.kml",
        DISTRICT_BOUNDARIES_KMZ.as_posix(),
        COUNTY_BOUNDARIES_KMZ.as_posix(),
        CITY_BOUNDARIES_KMZ.as_posix(),
        ADMIN_BOUNDARIES_KMZ.as_posix(),
    ]
    assert all(p.exists() and p.stat().st_size > 0 for p in written)


def test_written_admin_kmz_files_are_readable_archives(config, tmp_path, resolver):
    cfg = dataclasses.replace(config, output_dir=tmp_path)
    build_distribution_artifacts(
        cfg, _districts_gdf(), _counties_gdf(), _city_limits_gdf(), resolver
    )

    root = _root_from_kmz(tmp_path / ADMIN_BOUNDARIES_KMZ)
    assert [f.find(f"{KML_NS}name").text for f in _folders(root)] == [
        "District Boundaries",
        "County Boundaries",
        "City Limits",
    ]
    assert _count_roadway_geometry(root) == 0


def _strip_ids(element: ET.Element) -> ET.Element:
    """Drop simplekml's per-object `id` attributes.

    They are a process-global counter, not content: rebuilding the same
    document a second time inside one process yields the same structure with
    higher ids. Two separate runs of the CLI from a fresh process do produce
    identical bytes -- within one process they cannot, so content is what
    these assertions compare.
    """
    for node in element.iter():
        node.attrib.pop("id", None)
        node.attrib.pop("targetId", None)
    return element


def test_generation_does_not_depend_on_source_row_order(config, tmp_path, resolver):
    """Shuffled input rows must produce identical artifact content."""
    first_dir, second_dir = tmp_path / "first", tmp_path / "second"
    shuffled = _counties_gdf().iloc[::-1]

    build_distribution_artifacts(
        dataclasses.replace(config, output_dir=first_dir),
        _districts_gdf(),
        _counties_gdf(),
        _city_limits_gdf(),
        resolver,
    )
    build_distribution_artifacts(
        dataclasses.replace(config, output_dir=second_dir),
        _districts_gdf(),
        shuffled,
        _city_limits_gdf(),
        resolver,
    )

    for relative in ("districts/alpha.kml", COUNTY_BOUNDARIES_KMZ.as_posix()):
        if relative.endswith(".kml"):
            first = ET.parse(first_dir / relative).getroot()
            second = ET.parse(second_dir / relative).getroot()
        else:
            first = _root_from_kmz(first_dir / relative)
            second = _root_from_kmz(second_dir / relative)
        assert ET.tostring(_strip_ids(first)) == ET.tostring(_strip_ids(second))
