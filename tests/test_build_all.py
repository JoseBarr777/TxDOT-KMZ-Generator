"""Locks down `build-all`'s Step 8 integration: it must call the existing
Step 6 offline-package builder, with the exact same data it already loaded,
after county KMZ generation -- without duplicating any packaging logic or
running deep validation itself.

`build_all_artifacts` takes already-loaded districts/counties/city_limits
(the same convention every other command's pure function already uses --
`build_distribution_artifacts`, `build_manifest`, `build_offline_packages`),
so these tests never touch the network. The one thing that *does* require
network in the real pipeline is `build_county` (it fetches roadway data), so
it's monkeypatched here with a stand-in that writes a small real KMZ file at
exactly the path the real one would -- this is the first monkeypatch used in
this test suite; every other command-level test avoids the network by
testing a pure function directly, but `build_all`'s own per-county loop has
no pure/non-network equivalent to call instead, so patching that one call is
the smallest way to exercise the loop for real without live GIS access.
"""

from __future__ import annotations

import dataclasses
import zipfile

import geopandas as gpd
import pytest
from shapely.geometry import Point

from txdot_overlay.commands import build_all
from txdot_overlay.export.layout import (
    county_kmz_relative_path,
    district_offline_zip_relative_path,
    offline_county_archive_path,
)
from txdot_overlay.export.offline_package import OfflinePackageResult

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


def _empty_city_limits_gdf():
    return gpd.GeoDataFrame(
        {"OBJECTID": [], "CITY_NM": [], "CNTY_SEAT_FLAG": [], "POP2022": [], "POP2020": []},
        geometry=[],
        crs="EPSG:4326",
    )


@pytest.fixture
def cfg(config, tmp_path):
    return dataclasses.replace(config, output_dir=tmp_path)


def _fake_build_county(
    county_name, config, *, counties=None, city_limits=None, force_refresh=False
):
    """Stands in for the real, network-dependent build_county: writes a small
    real KMZ at exactly the path the real one would, using the same
    counties GeoDataFrame the caller already loaded -- no GIS/network work.
    """
    county_fields = config.sources["counties"].fields
    row = counties[counties[county_fields["name"]] == county_name].iloc[0]
    district_name = row[county_fields["district_name"]]
    path = config.output_dir / county_kmz_relative_path(district_name, county_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("doc.kml", f"<kml>{county_name} County fake content</kml>")
    return path


# --- Wiring: build-all invokes the offline package builder with the right args ------


def test_build_all_artifacts_invokes_offline_package_builder_with_expected_args(cfg, monkeypatch):
    districts = [TYLER]
    gdf_districts, gdf_counties = _districts_gdf(districts), _counties_gdf(districts)

    monkeypatch.setattr(build_all, "build_county", _fake_build_county)

    recorded = {}

    def _recording_stub(config, districts_arg, counties_arg):
        recorded["config"] = config
        recorded["districts"] = districts_arg
        recorded["counties"] = counties_arg
        return OfflinePackageResult(districts=[], statewide_path=None)

    monkeypatch.setattr(build_all, "build_offline_packages", _recording_stub)

    build_all.build_all_artifacts(cfg, gdf_districts, gdf_counties, _empty_city_limits_gdf())

    assert recorded["config"] is cfg
    assert recorded["districts"] is gdf_districts
    assert recorded["counties"] is gdf_counties


def test_offline_package_builder_is_called_after_county_kmz_generation(cfg, monkeypatch):
    """The call must happen once county KMZs already exist on disk, not before."""
    districts = [TYLER]
    call_order = []

    def _tracking_build_county(county_name, config, **kwargs):
        call_order.append(("build_county", county_name))
        return _fake_build_county(county_name, config, **kwargs)

    def _tracking_build_offline_packages(config, districts_arg, counties_arg):
        call_order.append(("build_offline_packages", None))
        # By the time packaging runs, every county KMZ this district needs
        # must already be present on disk.
        for county_name in ("Smith", "Anderson"):
            assert (config.output_dir / county_kmz_relative_path("Tyler", county_name)).exists()
        return OfflinePackageResult(districts=[], statewide_path=None)

    monkeypatch.setattr(build_all, "build_county", _tracking_build_county)
    monkeypatch.setattr(build_all, "build_offline_packages", _tracking_build_offline_packages)

    build_all.build_all_artifacts(
        cfg, _districts_gdf(districts), _counties_gdf(districts), _empty_city_limits_gdf()
    )

    assert call_order[-1][0] == "build_offline_packages"
    assert ("build_county", "Smith") in call_order
    assert ("build_county", "Anderson") in call_order


# --- End-to-end: a complete build reports built packages -----------------------------


def test_complete_build_reports_district_and_statewide_packages_as_built(cfg, monkeypatch):
    districts = [TYLER, ABILENE]
    monkeypatch.setattr(build_all, "build_county", _fake_build_county)

    exit_code = build_all.build_all_artifacts(
        cfg, _districts_gdf(districts), _counties_gdf(districts), _empty_city_limits_gdf()
    )

    assert exit_code == 0
    tyler_zip = cfg.output_dir / district_offline_zip_relative_path("Tyler")
    abilene_zip = cfg.output_dir / district_offline_zip_relative_path("Abilene")
    assert tyler_zip.exists()
    assert abilene_zip.exists()
    with zipfile.ZipFile(tyler_zip) as zf:
        assert set(zf.namelist()) == {
            offline_county_archive_path("Tyler", "Smith").as_posix(),
            offline_county_archive_path("Tyler", "Anderson").as_posix(),
        }
    from txdot_overlay.export.layout import STATEWIDE_OFFLINE_ZIP

    assert (cfg.output_dir / STATEWIDE_OFFLINE_ZIP).exists()


# --- Incompleteness: reported, does not fail a legitimately-scoped build -------------


def test_scoped_build_reports_incomplete_packages_without_failing(cfg, monkeypatch):
    """A --district-scoped build never produces the *other* districts' county
    KMZs -- exactly like build_distribution_artifacts already tolerates for
    district KMLs referencing not-yet-built counties, this is expected,
    reported, and must not flip build-all's exit code to failure.
    """
    districts = [TYLER, ABILENE]
    monkeypatch.setattr(build_all, "build_county", _fake_build_county)

    exit_code = build_all.build_all_artifacts(
        cfg,
        _districts_gdf(districts),
        _counties_gdf(districts),
        _empty_city_limits_gdf(),
        districts_filter=["Tyler"],
    )

    assert exit_code == 0
    assert (cfg.output_dir / district_offline_zip_relative_path("Tyler")).exists()
    assert not (cfg.output_dir / district_offline_zip_relative_path("Abilene")).exists()

    from txdot_overlay.export.layout import STATEWIDE_OFFLINE_ZIP

    assert not (cfg.output_dir / STATEWIDE_OFFLINE_ZIP).exists()


def test_actual_county_build_failure_still_fails_the_command(cfg, monkeypatch):
    """Unlike scope-driven incompleteness, a real per-county exception must
    still fail build-all -- this behavior is unchanged from before Step 8;
    package incompleteness doesn't independently drive the exit code either
    way, it just rides along with whatever the county loop already decided.
    """
    districts = [TYLER]

    def _flaky_build_county(county_name, config, **kwargs):
        if county_name == "Anderson":
            raise RuntimeError("simulated county build failure")
        return _fake_build_county(county_name, config, **kwargs)

    monkeypatch.setattr(build_all, "build_county", _flaky_build_county)

    exit_code = build_all.build_all_artifacts(
        cfg, _districts_gdf(districts), _counties_gdf(districts), _empty_city_limits_gdf()
    )

    assert exit_code == 1
    # Tyler is missing Anderson's KMZ, so its bulk ZIP is correctly withheld too.
    assert not (cfg.output_dir / district_offline_zip_relative_path("Tyler")).exists()
