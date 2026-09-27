"""Locks down `export/offline_package.py`'s District/Statewide offline ZIP
packaging contract: consumes existing county KMZ bytes unchanged, groups them
by district using the same authoritative source metadata the rest of the
project uses, and never produces or leaves behind an incomplete-looking
package.

Fixture county "KMZ" files here are small hand-built zips (not
simplekml-derived) so their bytes are exactly known and reproducible --
matching the same reasoning `test_kmz_writer.py`/`test_zip_utils.py` already
established for avoiding simplekml's global element-id counter.
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

POINT = Point(-96.0, 32.0)

# (district, district_number, [(county, fips), ...])
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


def _write_all(cfg, districts):
    for district, _number, counties in districts:
        for county, _fips in counties:
            _write_fake_county_kmz(cfg, district, county)


@pytest.fixture
def cfg(config, tmp_path):
    return dataclasses.replace(config, output_dir=tmp_path)


def _read_members(path):
    with zipfile.ZipFile(path) as zf:
        return {info.filename: (info, zf.read(info.filename)) for info in zf.infolist()}


# --- District package structure ----------------------------------------------


def test_complete_district_produces_the_expected_zip_path(cfg):
    districts = [TYLER]
    _write_all(cfg, districts)

    result = build_offline_packages(cfg, _districts_gdf(districts), _counties_gdf(districts))

    tyler = next(d for d in result.districts if d.district_name == "Tyler")
    assert tyler.built
    assert tyler.path == cfg.output_dir / district_offline_zip_relative_path("Tyler")
    assert tyler.path.exists()


def test_district_zip_member_names_match_the_layout_contract(cfg):
    districts = [TYLER]
    _write_all(cfg, districts)

    result = build_offline_packages(cfg, _districts_gdf(districts), _counties_gdf(districts))
    tyler = next(d for d in result.districts if d.district_name == "Tyler")

    members = _read_members(tyler.path)
    assert set(members) == {
        offline_county_archive_path("Tyler", "Smith").as_posix(),
        offline_county_archive_path("Tyler", "Anderson").as_posix(),
    }


def test_district_zip_members_use_zip_stored(cfg):
    districts = [TYLER]
    _write_all(cfg, districts)

    result = build_offline_packages(cfg, _districts_gdf(districts), _counties_gdf(districts))
    tyler = next(d for d in result.districts if d.district_name == "Tyler")

    with zipfile.ZipFile(tyler.path) as zf:
        for info in zf.infolist():
            assert info.compress_type == zipfile.ZIP_STORED


def test_embedded_county_kmz_bytes_are_byte_identical_to_source(cfg):
    districts = [TYLER]
    _write_all(cfg, districts)
    source_bytes = (cfg.output_dir / county_kmz_relative_path("Tyler", "Smith")).read_bytes()

    result = build_offline_packages(cfg, _districts_gdf(districts), _counties_gdf(districts))
    tyler = next(d for d in result.districts if d.district_name == "Tyler")

    members = _read_members(tyler.path)
    _info, packaged_bytes = members[offline_county_archive_path("Tyler", "Smith").as_posix()]
    assert packaged_bytes == source_bytes


def test_multiple_districts_produce_independent_zips(cfg):
    districts = [TYLER, ABILENE]
    _write_all(cfg, districts)

    result = build_offline_packages(cfg, _districts_gdf(districts), _counties_gdf(districts))

    assert {d.district_name for d in result.built_districts} == {"Tyler", "Abilene"}
    tyler = next(d for d in result.districts if d.district_name == "Tyler")
    abilene = next(d for d in result.districts if d.district_name == "Abilene")
    assert set(_read_members(tyler.path)) == {
        offline_county_archive_path("Tyler", "Smith").as_posix(),
        offline_county_archive_path("Tyler", "Anderson").as_posix(),
    }
    assert set(_read_members(abilene.path)) == {
        offline_county_archive_path("Abilene", "Borden").as_posix(),
    }


# --- Statewide package structure ----------------------------------------------


def test_statewide_zip_contains_counties_from_all_districts(cfg):
    districts = [TYLER, ABILENE]
    _write_all(cfg, districts)

    result = build_offline_packages(cfg, _districts_gdf(districts), _counties_gdf(districts))

    assert result.statewide_built
    members = set(_read_members(result.statewide_path))
    assert members == {
        offline_county_archive_path("Tyler", "Smith").as_posix(),
        offline_county_archive_path("Tyler", "Anderson").as_posix(),
        offline_county_archive_path("Abilene", "Borden").as_posix(),
    }


def test_statewide_zip_uses_the_same_archive_member_paths_as_district_zips(cfg):
    districts = [TYLER]
    _write_all(cfg, districts)

    result = build_offline_packages(cfg, _districts_gdf(districts), _counties_gdf(districts))
    tyler = next(d for d in result.districts if d.district_name == "Tyler")

    assert set(_read_members(tyler.path)) == set(_read_members(result.statewide_path))


def test_statewide_zip_members_use_zip_stored(cfg):
    districts = [TYLER, ABILENE]
    _write_all(cfg, districts)

    result = build_offline_packages(cfg, _districts_gdf(districts), _counties_gdf(districts))

    with zipfile.ZipFile(result.statewide_path) as zf:
        for info in zf.infolist():
            assert info.compress_type == zipfile.ZIP_STORED


def test_statewide_zip_path_matches_layout_constant(cfg):
    districts = [TYLER]
    _write_all(cfg, districts)

    result = build_offline_packages(cfg, _districts_gdf(districts), _counties_gdf(districts))

    assert result.statewide_path == cfg.output_dir / STATEWIDE_OFFLINE_ZIP


# --- Determinism ---------------------------------------------------------------


def test_identical_inputs_produce_byte_identical_district_zip(cfg):
    districts = [TYLER]
    _write_all(cfg, districts)
    gdf_districts, gdf_counties = _districts_gdf(districts), _counties_gdf(districts)

    result1 = build_offline_packages(cfg, gdf_districts, gdf_counties)
    bytes1 = result1.districts[0].path.read_bytes()
    result2 = build_offline_packages(cfg, gdf_districts, gdf_counties)
    bytes2 = result2.districts[0].path.read_bytes()

    assert bytes1 == bytes2


def test_identical_inputs_produce_byte_identical_statewide_zip(cfg):
    districts = [TYLER, ABILENE]
    _write_all(cfg, districts)
    gdf_districts, gdf_counties = _districts_gdf(districts), _counties_gdf(districts)

    result1 = build_offline_packages(cfg, gdf_districts, gdf_counties)
    bytes1 = result1.statewide_path.read_bytes()
    result2 = build_offline_packages(cfg, gdf_districts, gdf_counties)
    bytes2 = result2.statewide_path.read_bytes()

    assert bytes1 == bytes2


def test_source_row_order_does_not_affect_archive_bytes(cfg):
    """Feed the counties GeoDataFrame in two different row orders (but the
    same logical membership) and confirm both the district and statewide
    ZIPs come out byte-identical either way.
    """
    districts = [TYLER, ABILENE]
    _write_all(cfg, districts)

    forward_counties = _counties_gdf(districts)
    reversed_counties = forward_counties.iloc[::-1].reset_index(drop=True)

    result_forward = build_offline_packages(cfg, _districts_gdf(districts), forward_counties)
    tyler_forward = next(d for d in result_forward.districts if d.district_name == "Tyler").path
    forward_bytes = tyler_forward.read_bytes()
    statewide_forward_bytes = result_forward.statewide_path.read_bytes()

    result_reversed = build_offline_packages(cfg, _districts_gdf(districts), reversed_counties)
    tyler_reversed = next(d for d in result_reversed.districts if d.district_name == "Tyler").path
    reversed_bytes = tyler_reversed.read_bytes()
    statewide_reversed_bytes = result_reversed.statewide_path.read_bytes()

    assert forward_bytes == reversed_bytes
    assert statewide_forward_bytes == statewide_reversed_bytes


# --- Missing-county / incompleteness behavior ----------------------------------


def test_missing_county_kmz_skips_that_district_package(cfg):
    districts = [TYLER]
    _write_fake_county_kmz(cfg, "Tyler", "Smith")
    # Anderson's KMZ is never written.

    result = build_offline_packages(cfg, _districts_gdf(districts), _counties_gdf(districts))

    tyler = next(d for d in result.districts if d.district_name == "Tyler")
    assert not tyler.built
    assert tyler.path is None
    assert tyler.missing_counties == ["Anderson"]
    assert not (cfg.output_dir / district_offline_zip_relative_path("Tyler")).exists()


def test_missing_county_kmz_in_any_district_skips_the_statewide_package(cfg):
    districts = [TYLER, ABILENE]
    _write_all(cfg, [ABILENE])
    _write_fake_county_kmz(cfg, "Tyler", "Smith")
    # Tyler's Anderson KMZ is missing -- Abilene is fully built.

    result = build_offline_packages(cfg, _districts_gdf(districts), _counties_gdf(districts))

    assert not result.statewide_built
    assert result.statewide_missing_counties == ["Tyler/Anderson"]
    assert not (cfg.output_dir / STATEWIDE_OFFLINE_ZIP).exists()
    # Abilene, the complete district, is still built independently.
    abilene = next(d for d in result.districts if d.district_name == "Abilene")
    assert abilene.built


def test_stale_district_zip_is_removed_when_district_becomes_incomplete(cfg):
    districts = [TYLER]
    _write_all(cfg, districts)
    gdf_districts, gdf_counties = _districts_gdf(districts), _counties_gdf(districts)

    first = build_offline_packages(cfg, gdf_districts, gdf_counties)
    tyler_zip = first.districts[0].path
    assert tyler_zip.exists()

    (cfg.output_dir / county_kmz_relative_path("Tyler", "Anderson")).unlink()
    second = build_offline_packages(cfg, gdf_districts, gdf_counties)

    assert not second.districts[0].built
    assert not tyler_zip.exists()


def test_stale_statewide_zip_is_removed_when_statewide_becomes_incomplete(cfg):
    districts = [TYLER, ABILENE]
    _write_all(cfg, districts)
    gdf_districts, gdf_counties = _districts_gdf(districts), _counties_gdf(districts)

    first = build_offline_packages(cfg, gdf_districts, gdf_counties)
    statewide_zip = first.statewide_path
    assert statewide_zip.exists()

    (cfg.output_dir / county_kmz_relative_path("Tyler", "Anderson")).unlink()
    second = build_offline_packages(cfg, gdf_districts, gdf_counties)

    assert not second.statewide_built
    assert not statewide_zip.exists()


# --- Source files are untouched -------------------------------------------------


def test_source_county_kmz_files_are_unchanged_after_packaging(cfg):
    districts = [TYLER, ABILENE]
    _write_all(cfg, districts)
    source_paths = [
        cfg.output_dir / county_kmz_relative_path(d, c)
        for d, _n, counties in districts
        for c, _f in counties
    ]
    before = {p: p.read_bytes() for p in source_paths}

    build_offline_packages(cfg, _districts_gdf(districts), _counties_gdf(districts))

    for path, original_bytes in before.items():
        assert path.read_bytes() == original_bytes
