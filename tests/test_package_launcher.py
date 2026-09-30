"""Google Earth launcher KMLs inside the District/Statewide offline packages.

A launcher is local package navigation: one obvious KML to open after
extracting a ZIP, listing the packaged county KMZs (all unchecked) by relative
archive path, with no GIS content and no hosted/remote reference. These tests
check what the backend can establish structurally; whether a given Google
Earth Pro version defers loading an unchecked link is a manual check.

Fixture county "KMZ" files are small hand-built zips so their bytes are known.
"""

from __future__ import annotations

import dataclasses
import zipfile
from xml.etree import ElementTree as ET

import geopandas as gpd
import pytest
import simplekml
from shapely.geometry import Point

from txdot_overlay.export.layout import (
    STATEWIDE_LAUNCHER_ARCHIVE_PATH,
    STATEWIDE_OFFLINE_ZIP,
    county_kmz_relative_path,
    district_launcher_archive_path,
    district_offline_zip_relative_path,
)
from txdot_overlay.export.offline_package import build_offline_packages
from txdot_overlay.export.offline_package_validate import (
    validate_district_package,
    validate_offline_packages,
    validate_statewide_package,
)
from txdot_overlay.export.package_launcher import (
    KML_NAMESPACE,
    build_district_launcher,
    build_statewide_launcher,
)

KML = f"{{{KML_NAMESPACE}}}"
POINT = Point(-96.0, 32.0)

# Deliberately unsorted, to prove launcher ordering is alphabetical.
TYLER = ("Tyler", 10, [("Smith", "48423"), ("Anderson", "48001")])
ABILENE = ("Abilene", 8, [("Borden", "48033")])
TYLER_LAUNCHER = district_launcher_archive_path("Tyler").as_posix()
STATEWIDE_LAUNCHER = STATEWIDE_LAUNCHER_ARCHIVE_PATH.as_posix()

ET.register_namespace("", KML_NAMESPACE)


def _districts_gdf(districts):
    return gpd.GeoDataFrame(
        {
            "DIST_NM": [d for d, _, _ in districts],
            "DIST_NBR": [n for _, n, _ in districts],
            "geometry": [POINT] * len(districts),
        },
        crs="EPSG:4326",
    )


def _counties_gdf(districts):
    rows = [(c, f, d, n) for d, n, counties in districts for c, f in counties]
    return gpd.GeoDataFrame(
        {
            "CNTY_NM": [r[0] for r in rows],
            "CNTY_FIPS": [r[1] for r in rows],
            "DIST_NM": [r[2] for r in rows],
            "DIST_NBR": [r[3] for r in rows],
            "geometry": [POINT] * len(rows),
        },
        crs="EPSG:4326",
    )


@pytest.fixture
def cfg(config, tmp_path):
    return dataclasses.replace(config, output_dir=tmp_path)


def _build(cfg, districts):
    for district, _number, counties in districts:
        for county, _fips in counties:
            path = cfg.output_dir / county_kmz_relative_path(district, county)
            path.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("doc.kml", f"<kml>{county} County fake content</kml>")
    return build_offline_packages(cfg, _districts_gdf(districts), _counties_gdf(districts))


def _members(path):
    with zipfile.ZipFile(path) as zf:
        return {name: zf.read(name) for name in zf.namelist()}


def _links(root):
    """[(container name, link name, visibility, href)] in document order."""
    parents = {child: parent for parent in root.iter() for child in parent}
    rows = []
    for link in root.iter(f"{KML}NetworkLink"):
        container = parents[link]
        rows.append(
            (
                container.findtext(f"{KML}name") if container.tag == f"{KML}Folder" else None,
                link.findtext(f"{KML}name"),
                link.findtext(f"{KML}visibility"),
                link.findtext(f"{KML}Link/{KML}href"),
            )
        )
    return rows


# --- District launcher ---------------------------------------------------------------


def test_district_launcher_lists_its_counties_unchecked_by_relative_path(cfg):
    result = _build(cfg, [TYLER])
    members = _members(result.districts[0].path)
    root = ET.fromstring(members[TYLER_LAUNCHER])

    assert TYLER_LAUNCHER == "Tyler District/Open Tyler District.kml"
    assert root.findtext(f"{KML}Document/{KML}name") == "Tyler District"
    assert _links(root) == [
        (None, "Anderson County", "0", "Anderson County.kmz"),
        (None, "Smith County", "0", "Smith County.kmz"),
    ]
    # Every href resolves, relative to the launcher, to a county KMZ in this ZIP.
    for _, _, _, href in _links(root):
        assert f"Tyler District/{href}" in members


def test_launchers_hold_no_gis_content_or_remote_reference(cfg):
    result = _build(cfg, [TYLER, ABILENE])
    for data in (
        _members(result.districts[1].path)[TYLER_LAUNCHER],
        _members(result.statewide_path)[STATEWIDE_LAUNCHER],
    ):
        root = ET.fromstring(data)
        # Every text and attribute value (the KML namespace URI is an
        # identifier, not a reference, and is not among them once parsed).
        values = [el.text or "" for el in root.iter()]
        values += [v for el in root.iter() for v in el.attrib.values()]
        for forbidden in ("http://", "https://", "kmz.josebarrera", "releases/", "current.json"):
            assert not any(forbidden in value for value in values)
        root = ET.fromstring(data)
        for tag in ("Placemark", "Polygon", "LineString", "Point", "GroundOverlay", "TimeStamp"):
            assert root.find(f".//{KML}{tag}") is None


# --- Statewide launcher -----------------------------------------------------------


def test_statewide_launcher_groups_counties_by_district(cfg):
    result = _build(cfg, [TYLER, ABILENE])
    members = _members(result.statewide_path)
    root = ET.fromstring(members[STATEWIDE_LAUNCHER])

    assert STATEWIDE_LAUNCHER == "Open Texas TxDOT Overlay.kml"
    assert root.findtext(f"{KML}Document/{KML}name") == "Texas TxDOT Overlay"
    folders = root.findall(f"{KML}Document/{KML}Folder")
    assert [f.findtext(f"{KML}name") for f in folders] == ["Abilene District", "Tyler District"]
    assert _links(root) == [
        ("Abilene District", "Borden County", "0", "Abilene District/Borden County.kmz"),
        ("Tyler District", "Anderson County", "0", "Tyler District/Anderson County.kmz"),
        ("Tyler District", "Smith County", "0", "Tyler District/Smith County.kmz"),
    ]
    for _, _, _, href in _links(root):
        assert href in members


def test_complete_254_county_statewide_package_validates(cfg):
    districts = [
        (f"District {i:02d}", i, [(f"C{i:02d}x{j:02d}", f"48{i:02d}{j}") for j in range(n)])
        for i, n in enumerate([14] + [10] * 24)
    ]
    result = _build(cfg, districts)
    assert result.statewide_built

    root = ET.fromstring(_members(result.statewide_path)[STATEWIDE_LAUNCHER])
    links = _links(root)
    assert len(links) == 254
    assert {visibility for _, _, visibility, _ in links} == {"0"}
    assert len(root.findall(f"{KML}Document/{KML}Folder")) == 25

    validation = validate_offline_packages(cfg, _districts_gdf(districts), _counties_gdf(districts))
    assert validation.ok, [e for d in validation.districts for e in d.report.errors]


# --- Determinism ---------------------------------------------------------------------


def test_launcher_bytes_do_not_depend_on_process_state():
    before = build_district_launcher("Tyler", ["Anderson", "Smith"])
    # simplekml's process-global element-ID counter must not leak into launchers.
    simplekml.Kml().newfolder(name="noise").newpoint(name="p", coords=[(0, 0)])
    assert build_district_launcher("Tyler", ["Anderson", "Smith"]) == before
    assert build_statewide_launcher([("Tyler", ["Smith"])]) == build_statewide_launcher(
        [("Tyler", ["Smith"])]
    )


def test_rebuilt_packages_are_byte_identical(cfg):
    first = _build(cfg, [TYLER, ABILENE])
    tyler_bytes = first.districts[1].path.read_bytes()
    statewide_bytes = first.statewide_path.read_bytes()

    second = _build(cfg, [TYLER, ABILENE])
    assert second.districts[1].path.read_bytes() == tyler_bytes
    assert second.statewide_path.read_bytes() == statewide_bytes


def test_county_members_stay_byte_identical_to_canonical_kmzs(cfg):
    result = _build(cfg, [TYLER])
    canonical = (cfg.output_dir / county_kmz_relative_path("Tyler", "Smith")).read_bytes()
    assert _members(result.districts[0].path)["Tyler District/Smith County.kmz"] == canonical
    assert _members(result.statewide_path)["Tyler District/Smith County.kmz"] == canonical


# --- Deep validation rejects broken launchers ------------------------------------------


def _rewrite(zip_path, *, replace=None, drop=(), add=None):
    """Rewrite a built package with some members replaced/dropped/added."""
    members = _members(zip_path)
    members.update(replace or {})
    members.update(add or {})
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:
        for name, data in members.items():
            if name not in drop:
                zf.writestr(name, data)


def _edit_launcher(zip_path, arcname, edit):
    root = ET.fromstring(_members(zip_path)[arcname])
    edit(root)
    _rewrite(zip_path, replace={arcname: ET.tostring(root, encoding="utf-8")})


def _set_href(old, new):
    def edit(root):
        for href in root.iter(f"{KML}href"):
            if href.text == old:
                href.text = new

    return edit


@pytest.fixture
def tyler_zip(cfg):
    _build(cfg, [TYLER])
    return cfg.output_dir / district_offline_zip_relative_path("Tyler")


def _tyler_errors(cfg):
    result = validate_district_package(cfg, _counties_gdf([TYLER]), "Tyler")
    return result.report.errors


def test_valid_district_package_passes(cfg, tyler_zip):
    assert _tyler_errors(cfg) == []


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda z: _rewrite(z, drop={TYLER_LAUNCHER}), "missing archive member: " + TYLER_LAUNCHER),
        (
            lambda z: _rewrite(z, add={"Tyler District/Open Tyler District (2).kml": b"<kml/>"}),
            "unexpected archive member: Tyler District/Open Tyler District (2).kml",
        ),
        (
            lambda z: _rewrite(
                z, replace={TYLER_LAUNCHER: build_district_launcher("Tyler", ["Anderson"])}
            ),
            "launcher is missing county link: Smith County.kmz",
        ),
        (
            lambda z: _rewrite(
                z,
                replace={
                    TYLER_LAUNCHER: build_district_launcher("Tyler", ["Anderson", "Smith", "Wood"])
                },
            ),
            "launcher has unexpected link: Wood County.kmz",
        ),
        (
            lambda z: _edit_launcher(
                z,
                TYLER_LAUNCHER,
                _set_href("Smith County.kmz", "https://files.example/Smith County.kmz"),
            ),
            "href is not a local relative path",
        ),
        (
            lambda z: _edit_launcher(
                z, TYLER_LAUNCHER, _set_href("Smith County.kmz", "/tmp/Smith County.kmz")
            ),
            "href is absolute",
        ),
        (
            lambda z: _edit_launcher(
                z,
                TYLER_LAUNCHER,
                _set_href("Smith County.kmz", "../Tyler District/Smith County.kmz"),
            ),
            "href escapes the package",
        ),
        (
            lambda z: _edit_launcher(
                z, TYLER_LAUNCHER, _set_href("Smith County.kmz", "Smith County (old).kmz")
            ),
            "link does not resolve to a package member: Smith County (old).kmz",
        ),
        (
            lambda z: _edit_launcher(
                z,
                TYLER_LAUNCHER,
                lambda root: setattr(
                    root.find(f".//{KML}NetworkLink/{KML}visibility"), "text", "1"
                ),
            ),
            "county link starts enabled (visibility != 0): Anderson County.kmz",
        ),
        (
            lambda z: _edit_launcher(
                z,
                TYLER_LAUNCHER,
                lambda root: root.find(f".//{KML}NetworkLink").remove(
                    root.find(f".//{KML}NetworkLink/{KML}visibility")
                ),
            ),
            "county link starts enabled (visibility != 0): Anderson County.kmz",
        ),
        (
            lambda z: _edit_launcher(
                z,
                TYLER_LAUNCHER,
                lambda root: ET.SubElement(root.find(f"{KML}Document"), f"{KML}Placemark"),
            ),
            "launcher contains GIS content (Placemark)",
        ),
        (
            lambda z: _rewrite(z, replace={TYLER_LAUNCHER: b"<kml><Document>"}),
            "launcher is not valid XML",
        ),
        (
            lambda z: _rewrite(z, replace={"Tyler District/Smith County.kmz": b"altered"}),
            "embedded KMZ does not match source",
        ),
    ],
)
def test_validator_rejects_broken_district_packages(cfg, tyler_zip, mutate, expected):
    mutate(tyler_zip)
    errors = _tyler_errors(cfg)
    assert any(expected in e for e in errors), errors


def test_validator_rejects_a_county_under_the_wrong_district(cfg):
    districts = [TYLER, ABILENE]
    result = _build(cfg, districts)

    def move_smith_to_abilene(root):
        folders = {f.findtext(f"{KML}name"): f for f in root.iter(f"{KML}Folder")}
        smith = next(
            link
            for link in folders["Tyler District"].findall(f"{KML}NetworkLink")
            if link.findtext(f"{KML}name") == "Smith County"
        )
        folders["Tyler District"].remove(smith)
        folders["Abilene District"].append(smith)

    _edit_launcher(result.statewide_path, STATEWIDE_LAUNCHER, move_smith_to_abilene)
    validation = validate_statewide_package(
        cfg, _districts_gdf(districts), _counties_gdf(districts)
    )
    assert not validation.ok
    assert (
        "Statewide: link Tyler District/Smith County.kmz is not under Tyler District"
        in validation.report.errors
    )


def test_validator_rejects_a_missing_statewide_launcher(cfg):
    districts = [TYLER, ABILENE]
    _build(cfg, districts)
    _rewrite(cfg.output_dir / STATEWIDE_OFFLINE_ZIP, drop={STATEWIDE_LAUNCHER})
    validation = validate_statewide_package(
        cfg, _districts_gdf(districts), _counties_gdf(districts)
    )
    assert f"Statewide: missing archive member: {STATEWIDE_LAUNCHER}" in validation.report.errors
