from __future__ import annotations

import dataclasses
import hashlib

import geopandas as gpd
import pytest
import simplekml
from shapely.geometry import Polygon

from txdot_overlay.commands.build_distribution import build_distribution_artifacts
from txdot_overlay.export.kml_builder import (
    ADMIN_BOUNDARIES_KMZ,
    CITY_BOUNDARIES_KMZ,
    COUNTY_BOUNDARIES_KMZ,
    DISTRICT_BOUNDARIES_KMZ,
    build_master_kml,
    county_kmz_relative_path,
    district_kml_relative_path,
)
from txdot_overlay.export.kmz_writer import save_kml, save_kmz
from txdot_overlay.export.manifest import (
    ADMIN_BOUNDARIES_TYPE,
    CITY_BOUNDARIES_TYPE,
    COUNTY_BOUNDARIES_TYPE,
    COUNTY_KMZ_TYPE,
    DISTRICT_BOUNDARIES_TYPE,
    DISTRICT_KML_TYPE,
    MASTER_KML_TYPE,
    SCHEMA_VERSION,
    SINGLE_FILE_KMZ_TYPE,
    STATUS_COMPLETE,
    STATUS_FAILED,
    STATUS_PARTIAL,
    build_manifest,
)
from txdot_overlay.styling.styles import StyleResolver

DISTRICT_ALPHA = Polygon([(-96, 32), (-95, 32), (-95, 33), (-96, 33)])
DISTRICT_BETA = Polygon([(-97, 32), (-96.5, 32), (-96.5, 32.5), (-97, 32.5)])
AREA = Polygon([(-96, 32), (-95.5, 32), (-95.5, 32.5), (-96, 32.5)])

# (county, fips, number, district, district number) -- deliberately not in
# alphabetical input order, so ordering assertions mean something.
COUNTY_ROWS = [
    ("Zapata", "48505", 3, "Beta", 2),
    ("Wood", "48499", 2, "Alpha", 1),
    ("Anderson", "48001", 1, "Alpha", 1),
]


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


def _counties_gdf(rows=COUNTY_ROWS):
    names, fips, numbers, districts, district_numbers = zip(*rows, strict=True)
    return gpd.GeoDataFrame(
        {
            "CNTY_NM": list(names),
            "CNTY_FIPS": list(fips),
            "CNTY_NBR": list(numbers),
            "DIST_NM": list(districts),
            "DIST_NBR": list(district_numbers),
            "geometry": [AREA] * len(rows),
        },
        crs="EPSG:4326",
    )


def _city_limits_gdf():
    return gpd.GeoDataFrame(
        {
            "OBJECTID": [1, 2],
            "CITY_NM": ["Bellview", "Athens"],
            "CNTY_SEAT_FLAG": ["Y", "N"],
            "POP2022": [100, 200],
            "POP2020": [90, 180],
            "geometry": [AREA, AREA],
        },
        crs="EPSG:4326",
    )


def _write_valid_kmz(path):
    kml = simplekml.Kml()
    kml.newpoint(name="marker", coords=[(-96.0, 32.0)])
    return save_kmz(kml, path)


def _write_complete_distribution(cfg, districts, counties):
    """Write every REQUIRED artifact, using the real builders where possible."""
    style_resolver = StyleResolver(cfg)
    save_kml(
        build_master_kml(districts, counties, cfg, style_resolver),
        cfg.output_dir / cfg.master_kml_name,
    )
    build_distribution_artifacts(cfg, districts, counties, _city_limits_gdf(), style_resolver)
    for _, row in counties.iterrows():
        _write_valid_kmz(cfg.output_dir / county_kmz_relative_path(row["DIST_NM"], row["CNTY_NM"]))


@pytest.fixture
def cfg(config, tmp_path):
    return dataclasses.replace(config, output_dir=tmp_path)


@pytest.fixture
def complete(cfg):
    """A config whose output directory holds a complete, valid distribution."""
    districts, counties = _districts_gdf(), _counties_gdf()
    _write_complete_distribution(cfg, districts, counties)
    return cfg, districts, counties


def test_schema_shape(complete):
    cfg, districts, counties = complete
    payload = build_manifest(cfg, districts, counties).to_dict()

    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["generator"] == "txdot_overlay"
    assert payload["state"] == "TX"
    assert set(payload["validation"]) == {
        "status",
        "counties_included",
        "counties_expected",
        "districts_included",
        "districts_expected",
        "required_missing",
        "required_invalid",
    }
    assert payload["skipped"] == []

    master = next(a for a in payload["artifacts"] if a["type"] == MASTER_KML_TYPE)
    assert set(master) == {"type", "display_name", "path", "size_bytes", "sha256"}

    county = next(a for a in payload["artifacts"] if a["type"] == COUNTY_KMZ_TYPE)
    assert set(county) == {
        "type",
        "display_name",
        "path",
        "county",
        "county_fips",
        "district",
        "size_bytes",
        "sha256",
    }

    district = next(a for a in payload["artifacts"] if a["type"] == DISTRICT_KML_TYPE)
    assert set(district) == {"type", "display_name", "path", "district", "size_bytes", "sha256"}

    # Statewide administrative artifacts carry no county/district fields.
    admin = next(a for a in payload["artifacts"] if a["type"] == ADMIN_BOUNDARIES_TYPE)
    assert set(admin) == {"type", "display_name", "path", "size_bytes", "sha256"}


def test_all_new_artifact_types_are_present(complete):
    cfg, districts, counties = complete
    types = [a.type for a in build_manifest(cfg, districts, counties).artifacts]

    assert types.count(DISTRICT_KML_TYPE) == 2
    assert types.count(COUNTY_KMZ_TYPE) == 3
    for admin_type in (
        DISTRICT_BOUNDARIES_TYPE,
        COUNTY_BOUNDARIES_TYPE,
        CITY_BOUNDARIES_TYPE,
        ADMIN_BOUNDARIES_TYPE,
    ):
        assert types.count(admin_type) == 1


def test_district_metadata_and_paths(complete):
    cfg, districts, counties = complete
    artifacts = build_manifest(cfg, districts, counties).artifacts
    district_artifacts = [a for a in artifacts if a.type == DISTRICT_KML_TYPE]

    assert [a.district for a in district_artifacts] == ["Alpha", "Beta"]
    assert [a.display_name for a in district_artifacts] == ["Alpha District", "Beta District"]
    assert [a.path for a in district_artifacts] == ["districts/alpha.kml", "districts/beta.kml"]
    # A district KML is not county-scoped.
    assert all(a.county is None and a.county_fips is None for a in district_artifacts)


def test_admin_artifact_paths(complete):
    cfg, districts, counties = complete
    by_type = {a.type: a for a in build_manifest(cfg, districts, counties).artifacts}

    assert by_type[DISTRICT_BOUNDARIES_TYPE].path == DISTRICT_BOUNDARIES_KMZ.as_posix()
    assert by_type[COUNTY_BOUNDARIES_TYPE].path == COUNTY_BOUNDARIES_KMZ.as_posix()
    assert by_type[CITY_BOUNDARIES_TYPE].path == CITY_BOUNDARIES_KMZ.as_posix()
    assert by_type[ADMIN_BOUNDARIES_TYPE].path == ADMIN_BOUNDARIES_KMZ.as_posix()
    assert all(not a.path.startswith("/") for a in by_type.values())


def test_county_metadata_matches_source(complete):
    cfg, districts, counties = complete
    artifacts = build_manifest(cfg, districts, counties).artifacts
    anderson = next(a for a in artifacts if a.county == "Anderson")

    assert anderson.county_fips == "48001"
    assert anderson.district == "Alpha"
    assert anderson.display_name == "Anderson County"
    assert anderson.path == "districts/alpha/anderson.kmz"


def test_artifact_ordering_follows_the_download_model(complete):
    cfg, districts, counties = complete
    artifacts = build_manifest(cfg, districts, counties).artifacts

    assert [a.type for a in artifacts] == [
        MASTER_KML_TYPE,
        DISTRICT_KML_TYPE,
        DISTRICT_KML_TYPE,
        COUNTY_KMZ_TYPE,
        COUNTY_KMZ_TYPE,
        COUNTY_KMZ_TYPE,
        DISTRICT_BOUNDARIES_TYPE,
        COUNTY_BOUNDARIES_TYPE,
        CITY_BOUNDARIES_TYPE,
        ADMIN_BOUNDARIES_TYPE,
    ]
    # Counties: alphabetical by district, then alphabetical within it.
    counties_listed = [(a.district, a.county) for a in artifacts if a.type == COUNTY_KMZ_TYPE]
    assert counties_listed == [("Alpha", "Anderson"), ("Alpha", "Wood"), ("Beta", "Zapata")]


def test_manifest_is_deterministic_across_repeated_runs(complete):
    cfg, districts, counties = complete

    first = build_manifest(cfg, districts, counties).to_dict()
    second = build_manifest(cfg, districts, counties).to_dict()

    # generated_at is the one field allowed to vary between runs.
    first.pop("generated_at")
    second.pop("generated_at")
    assert first == second


def test_sizes_and_checksums_match_files_on_disk(complete):
    cfg, districts, counties = complete

    for artifact in build_manifest(cfg, districts, counties).artifacts:
        path = cfg.output_dir / artifact.path
        assert artifact.size_bytes == path.stat().st_size
        assert artifact.size_bytes > 0
        assert artifact.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()


def test_complete_distribution_reports_complete(complete):
    cfg, districts, counties = complete
    manifest = build_manifest(cfg, districts, counties)
    validation = manifest.to_dict()["validation"]

    assert manifest.status == STATUS_COMPLETE
    assert manifest.complete
    assert validation["counties_included"] == validation["counties_expected"] == 3
    assert validation["districts_included"] == validation["districts_expected"] == 2
    assert validation["required_missing"] == 0
    assert validation["required_invalid"] == 0


def test_missing_county_kmz_downgrades_release_to_partial(complete):
    cfg, districts, counties = complete
    (cfg.output_dir / county_kmz_relative_path("Alpha", "Wood")).unlink()

    manifest = build_manifest(cfg, districts, counties)

    assert manifest.status == STATUS_PARTIAL
    assert not manifest.complete
    assert [a.county for a in manifest.artifacts if a.type == COUNTY_KMZ_TYPE] == [
        "Anderson",
        "Zapata",
    ]
    skipped = manifest.to_dict()["skipped"]
    assert skipped == [
        {
            "type": COUNTY_KMZ_TYPE,
            "path": "districts/alpha/wood.kmz",
            "reason": "missing",
            "required": True,
        }
    ]
    assert manifest.to_dict()["validation"]["required_missing"] == 1


def test_missing_district_kml_downgrades_release_to_partial(complete):
    cfg, districts, counties = complete
    (cfg.output_dir / district_kml_relative_path("Beta")).unlink()

    manifest = build_manifest(cfg, districts, counties)

    assert manifest.status == STATUS_PARTIAL
    assert [a.district for a in manifest.artifacts if a.type == DISTRICT_KML_TYPE] == ["Alpha"]
    assert manifest.skipped[0].type == DISTRICT_KML_TYPE
    assert manifest.skipped[0].required is True


def test_missing_admin_artifact_downgrades_release_to_partial(complete):
    cfg, districts, counties = complete
    (cfg.output_dir / CITY_BOUNDARIES_KMZ).unlink()

    manifest = build_manifest(cfg, districts, counties)

    assert manifest.status == STATUS_PARTIAL
    assert not any(a.type == CITY_BOUNDARIES_TYPE for a in manifest.artifacts)
    assert manifest.skipped[0].type == CITY_BOUNDARIES_TYPE


def test_invalid_required_artifact_fails_the_release(complete):
    cfg, districts, counties = complete
    (cfg.output_dir / ADMIN_BOUNDARIES_KMZ).write_bytes(b"not a real zip/kmz")

    manifest = build_manifest(cfg, districts, counties)

    assert manifest.status == STATUS_FAILED
    assert not any(a.type == ADMIN_BOUNDARIES_TYPE for a in manifest.artifacts)
    assert "not a valid KMZ" in manifest.skipped[0].reason
    assert manifest.to_dict()["validation"]["required_invalid"] == 1


def test_invalid_master_kml_fails_the_release(complete):
    cfg, districts, counties = complete
    (cfg.output_dir / cfg.master_kml_name).write_text("<kml>truncated")

    manifest = build_manifest(cfg, districts, counties)

    assert manifest.status == STATUS_FAILED
    assert not any(a.type == MASTER_KML_TYPE for a in manifest.artifacts)


def test_missing_master_kml_fails_the_release(complete):
    cfg, districts, counties = complete
    (cfg.output_dir / cfg.master_kml_name).unlink()

    manifest = build_manifest(cfg, districts, counties)

    assert manifest.status == STATUS_FAILED
    assert manifest.skipped[0].type == MASTER_KML_TYPE
    assert manifest.skipped[0].reason == "missing"


def test_single_file_kmz_is_optional_and_never_blocks_a_release(complete):
    cfg, districts, counties = complete

    manifest = build_manifest(cfg, districts, counties)
    assert manifest.status == STATUS_COMPLETE
    assert not any(a.type == SINGLE_FILE_KMZ_TYPE for a in manifest.artifacts)
    # Absent-and-optional is silent: nothing for a publisher to triage.
    assert manifest.skipped == []

    _write_valid_kmz(cfg.output_dir / cfg.single_file_kmz_name)
    manifest = build_manifest(cfg, districts, counties)
    single_file = [a for a in manifest.artifacts if a.type == SINGLE_FILE_KMZ_TYPE]
    assert len(single_file) == 1
    assert single_file[0].path == cfg.single_file_kmz_name
    # ...and it sorts last, after the required set.
    assert manifest.artifacts[-1].type == SINGLE_FILE_KMZ_TYPE
    assert manifest.status == STATUS_COMPLETE
