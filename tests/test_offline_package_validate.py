"""Locks down `export/offline_package_validate.py`'s independent verification
contract: it must catch every way a District/Statewide offline package could
be wrong relative to the standalone county KMZs on disk and the
authoritative district/county source metadata, and it must never build,
repair, or otherwise modify anything it inspects.

Malformed packages are built here with raw `zipfile` calls rather than
`build_offline_packages`, since the whole point is to test what the
validator does when a package *doesn't* match what the builder would have
produced.
"""

from __future__ import annotations

import dataclasses
import zipfile

import geopandas as gpd
import pytest
from shapely.geometry import Point

from txdot_overlay.export.layout import (
    STATEWIDE_OFFLINE_ZIP,
    county_kmz_relative_path,
    district_offline_zip_relative_path,
    offline_county_archive_path,
)
from txdot_overlay.export.offline_package import build_offline_packages
from txdot_overlay.export.offline_package_validate import (
    validate_district_package,
    validate_offline_packages,
    validate_statewide_package,
)

POINT = Point(-96.0, 32.0)

TYLER = ("Tyler", 10, [("Smith", "48423"), ("Anderson", "48001")])
ABILENE = ("Abilene", 8, [("Borden", "48033")])


def _districts_gdf(districts):
    names, numbers = zip(*[(d, n) for d, n, _ in districts], strict=True)
    return gpd.GeoDataFrame(
        {"DIST_NM": list(names), "DIST_NBR": list(numbers), "geometry": [POINT] * len(names)},
        crs="EPSG:4326",
    )


def _counties_gdf(districts):
    rows = [
        (county, fips, district, number)
        for district, number, counties in districts
        for county, fips in counties
    ]
    names, fips, district_names, district_numbers = zip(*rows, strict=True)
    return gpd.GeoDataFrame(
        {
            "CNTY_NM": list(names),
            "CNTY_FIPS": list(fips),
            "DIST_NM": list(district_names),
            "DIST_NBR": list(district_numbers),
            "geometry": [POINT] * len(rows),
        },
        crs="EPSG:4326",
    )


def _write_fake_county_kmz(cfg, district, county, *, content=None):
    path = cfg.output_dir / county_kmz_relative_path(district, county)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("doc.kml", content or f"<kml>{county} County fake content</kml>")
    return path


def _write_all_sources(cfg, districts):
    for district, _number, counties in districts:
        for county, _fips in counties:
            _write_fake_county_kmz(cfg, district, county)


def _write_zip(path, entries, *, compress_type=zipfile.ZIP_STORED):
    """entries: list of (arcname, data) -- raw, not going through the builder."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compress_type) as zf:
        for arcname, data in entries:
            zf.writestr(arcname, data)


@pytest.fixture
def cfg(config, tmp_path):
    return dataclasses.replace(config, output_dir=tmp_path)


# --- Happy path ----------------------------------------------------------------


def test_valid_district_package_passes(cfg):
    districts = [TYLER]
    _write_all_sources(cfg, districts)
    build_offline_packages(cfg, _districts_gdf(districts), _counties_gdf(districts))

    result = validate_district_package(cfg, _counties_gdf(districts), "Tyler")

    assert result.ok
    assert result.report.errors == []


def test_valid_statewide_package_passes(cfg):
    districts = [TYLER, ABILENE]
    _write_all_sources(cfg, districts)
    build_offline_packages(cfg, _districts_gdf(districts), _counties_gdf(districts))

    result = validate_statewide_package(cfg, _districts_gdf(districts), _counties_gdf(districts))

    assert result.ok
    assert result.report.errors == []


def test_full_validate_offline_packages_passes_when_everything_is_correct(cfg):
    districts = [TYLER, ABILENE]
    _write_all_sources(cfg, districts)
    build_offline_packages(cfg, _districts_gdf(districts), _counties_gdf(districts))

    result = validate_offline_packages(cfg, _districts_gdf(districts), _counties_gdf(districts))

    assert result.ok
    assert all(d.ok for d in result.districts)
    assert result.statewide.ok


# --- Missing package -------------------------------------------------------------


def test_missing_district_zip_fails(cfg):
    districts = [TYLER]
    _write_all_sources(cfg, districts)
    # Deliberately never call build_offline_packages.

    result = validate_district_package(cfg, _counties_gdf(districts), "Tyler")

    assert not result.ok
    assert any("offline package not found" in e for e in result.report.errors)


def test_missing_statewide_zip_fails(cfg):
    districts = [TYLER]
    _write_all_sources(cfg, districts)

    result = validate_statewide_package(cfg, _districts_gdf(districts), _counties_gdf(districts))

    assert not result.ok
    assert any("offline package not found" in e for e in result.report.errors)


# --- Corrupt archive ---------------------------------------------------------------


def test_corrupt_zip_fails(cfg):
    districts = [TYLER]
    _write_all_sources(cfg, districts)
    zip_path = cfg.output_dir / district_offline_zip_relative_path("Tyler")
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    zip_path.write_bytes(b"this is not a zip file")

    result = validate_district_package(cfg, _counties_gdf(districts), "Tyler")

    assert not result.ok
    assert any("not a valid ZIP archive" in e for e in result.report.errors)


# --- Missing canonical source ------------------------------------------------------


def test_missing_standalone_source_county_kmz_fails(cfg):
    districts = [TYLER]
    _write_all_sources(cfg, districts)
    build_offline_packages(cfg, _districts_gdf(districts), _counties_gdf(districts))
    # Delete the canonical source AFTER packaging -- the package's own
    # embedded copy must not be treated as an acceptable substitute.
    (cfg.output_dir / county_kmz_relative_path("Tyler", "Smith")).unlink()

    result = validate_district_package(cfg, _counties_gdf(districts), "Tyler")

    assert not result.ok
    assert any("canonical source county KMZ missing" in e for e in result.report.errors)


# --- Membership mismatches ----------------------------------------------------------


def test_missing_expected_archive_member_fails(cfg):
    districts = [TYLER]
    _write_all_sources(cfg, districts)
    zip_path = cfg.output_dir / district_offline_zip_relative_path("Tyler")
    smith_bytes = (cfg.output_dir / county_kmz_relative_path("Tyler", "Smith")).read_bytes()
    _write_zip(
        zip_path,
        [(offline_county_archive_path("Tyler", "Smith").as_posix(), smith_bytes)],
        # Anderson's entry is deliberately omitted.
    )

    result = validate_district_package(cfg, _counties_gdf(districts), "Tyler")

    assert not result.ok
    assert any("missing archive member" in e and "Anderson" in e for e in result.report.errors)


def test_unexpected_archive_member_fails(cfg):
    districts = [TYLER]
    _write_all_sources(cfg, districts)
    zip_path = cfg.output_dir / district_offline_zip_relative_path("Tyler")
    smith_bytes = (cfg.output_dir / county_kmz_relative_path("Tyler", "Smith")).read_bytes()
    anderson_bytes = (cfg.output_dir / county_kmz_relative_path("Tyler", "Anderson")).read_bytes()
    _write_zip(
        zip_path,
        [
            (offline_county_archive_path("Tyler", "Smith").as_posix(), smith_bytes),
            (offline_county_archive_path("Tyler", "Anderson").as_posix(), anderson_bytes),
            ("Tyler District/Nonexistent County.kmz", b"not expected"),
        ],
    )

    result = validate_district_package(cfg, _counties_gdf(districts), "Tyler")

    assert not result.ok
    assert any(
        "unexpected archive member" in e and "Nonexistent" in e for e in result.report.errors
    )


def test_duplicate_archive_member_fails(cfg):
    districts = [TYLER]
    _write_all_sources(cfg, districts)
    zip_path = cfg.output_dir / district_offline_zip_relative_path("Tyler")
    smith_bytes = (cfg.output_dir / county_kmz_relative_path("Tyler", "Smith")).read_bytes()
    anderson_bytes = (cfg.output_dir / county_kmz_relative_path("Tyler", "Anderson")).read_bytes()
    smith_name = offline_county_archive_path("Tyler", "Smith").as_posix()
    # zipfile itself warns on writing a duplicate name -- expected here,
    # since a duplicate is exactly what this test deliberately constructs.
    with pytest.warns(UserWarning, match="Duplicate name"):
        _write_zip(
            zip_path,
            [
                (smith_name, smith_bytes),
                (smith_name, smith_bytes),  # duplicate arcname
                (offline_county_archive_path("Tyler", "Anderson").as_posix(), anderson_bytes),
            ],
        )

    result = validate_district_package(cfg, _counties_gdf(districts), "Tyler")

    assert not result.ok
    assert any("duplicate archive member" in e for e in result.report.errors)


def test_explicit_directory_entry_is_rejected(cfg):
    districts = [TYLER]
    _write_all_sources(cfg, districts)
    zip_path = cfg.output_dir / district_offline_zip_relative_path("Tyler")
    smith_bytes = (cfg.output_dir / county_kmz_relative_path("Tyler", "Smith")).read_bytes()
    anderson_bytes = (cfg.output_dir / county_kmz_relative_path("Tyler", "Anderson")).read_bytes()
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("Tyler District/", b"")  # explicit directory entry
        zf.writestr(offline_county_archive_path("Tyler", "Smith").as_posix(), smith_bytes)
        zf.writestr(offline_county_archive_path("Tyler", "Anderson").as_posix(), anderson_bytes)

    result = validate_district_package(cfg, _counties_gdf(districts), "Tyler")

    assert not result.ok
    assert any("explicit directory entry" in e for e in result.report.errors)


# --- Compression / byte identity -----------------------------------------------------


def test_wrong_compression_method_fails(cfg):
    districts = [TYLER]
    _write_all_sources(cfg, districts)
    zip_path = cfg.output_dir / district_offline_zip_relative_path("Tyler")
    smith_bytes = (cfg.output_dir / county_kmz_relative_path("Tyler", "Smith")).read_bytes()
    anderson_bytes = (cfg.output_dir / county_kmz_relative_path("Tyler", "Anderson")).read_bytes()
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(
            zipfile.ZipInfo(offline_county_archive_path("Tyler", "Smith").as_posix()),
            smith_bytes,
            zipfile.ZIP_DEFLATED,  # wrong -- offline packages must be ZIP_STORED
        )
        zf.writestr(
            zipfile.ZipInfo(offline_county_archive_path("Tyler", "Anderson").as_posix()),
            anderson_bytes,
            zipfile.ZIP_STORED,
        )

    result = validate_district_package(cfg, _counties_gdf(districts), "Tyler")

    assert not result.ok
    assert any("wrong compression method" in e for e in result.report.errors)


def test_embedded_kmz_hash_mismatch_fails(cfg):
    districts = [TYLER]
    _write_all_sources(cfg, districts)
    build_offline_packages(cfg, _districts_gdf(districts), _counties_gdf(districts))

    zip_path = cfg.output_dir / district_offline_zip_relative_path("Tyler")
    with zipfile.ZipFile(zip_path) as zf:
        entries = {info.filename: zf.read(info.filename) for info in zf.infolist()}
    entries[offline_county_archive_path("Tyler", "Smith").as_posix()] = b"tampered bytes"
    _write_zip(zip_path, list(entries.items()))

    result = validate_district_package(cfg, _counties_gdf(districts), "Tyler")

    assert not result.ok
    assert any(
        "embedded KMZ does not match source" in e and "Smith" in e for e in result.report.errors
    )


# --- Authoritative membership / statewide scope --------------------------------------


def test_district_validation_uses_the_expected_authoritative_membership(cfg):
    """A package that looks internally consistent (matches what it once was
    built for) must fail once the *source metadata* says a county belongs to
    the district that the package doesn't contain -- membership comes from
    counties/districts, never from "whatever the zip happens to have".
    """
    districts = [TYLER]
    _write_all_sources(cfg, districts)
    build_offline_packages(cfg, _districts_gdf(districts), _counties_gdf(districts))

    # Now the source metadata says Tyler also has a Cherokee county -- but
    # the already-built tyler.zip and Cherokee's own KMZ were never created.
    grown_districts = [
        ("Tyler", 10, [("Smith", "48423"), ("Anderson", "48001"), ("Cherokee", "48073")])
    ]

    result = validate_district_package(cfg, _counties_gdf(grown_districts), "Tyler")

    assert not result.ok
    assert any("missing" in e and "Cherokee" in e for e in result.report.errors)


def test_statewide_validation_spans_multiple_districts(cfg):
    districts = [TYLER, ABILENE]
    _write_all_sources(cfg, districts)
    build_offline_packages(cfg, _districts_gdf(districts), _counties_gdf(districts))

    result = validate_statewide_package(cfg, _districts_gdf(districts), _counties_gdf(districts))

    assert result.ok
    # Break Abilene's contribution specifically and confirm statewide
    # validation actually inspected it, not just Tyler's.
    borden_source = cfg.output_dir / county_kmz_relative_path("Abilene", "Borden")
    borden_source.unlink()
    broken = validate_statewide_package(cfg, _districts_gdf(districts), _counties_gdf(districts))
    assert not broken.ok
    assert any(str(borden_source) in e for e in broken.report.errors)


def test_source_row_order_does_not_affect_validation_outcome(cfg):
    districts = [TYLER, ABILENE]
    _write_all_sources(cfg, districts)
    build_offline_packages(cfg, _districts_gdf(districts), _counties_gdf(districts))

    forward_counties = _counties_gdf(districts)
    reversed_counties = forward_counties.iloc[::-1].reset_index(drop=True)

    result_forward = validate_offline_packages(cfg, _districts_gdf(districts), forward_counties)
    result_reversed = validate_offline_packages(cfg, _districts_gdf(districts), reversed_counties)

    assert result_forward.ok == result_reversed.ok is True


# --- Read-only ------------------------------------------------------------------------


def test_validation_does_not_modify_source_kmzs_or_packages(cfg):
    districts = [TYLER, ABILENE]
    _write_all_sources(cfg, districts)
    build_offline_packages(cfg, _districts_gdf(districts), _counties_gdf(districts))

    watched_paths = [
        cfg.output_dir / county_kmz_relative_path(d, c)
        for d, _n, counties in districts
        for c, _f in counties
    ] + [
        cfg.output_dir / district_offline_zip_relative_path("Tyler"),
        cfg.output_dir / district_offline_zip_relative_path("Abilene"),
        cfg.output_dir / STATEWIDE_OFFLINE_ZIP,
    ]
    before = {p: p.read_bytes() for p in watched_paths}

    validate_offline_packages(cfg, _districts_gdf(districts), _counties_gdf(districts))

    for path, original_bytes in before.items():
        assert path.read_bytes() == original_bytes
