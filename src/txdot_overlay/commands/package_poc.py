"""`package-poc`: assemble a portable, self-contained proof-of-concept directory.

Copies master.kml plus one district's county KMZ files into a clean output
directory. Every NetworkLink href written by kml_builder is already a
relative POSIX path (e.g. "districts/tyler/smith.kmz"), so as long as the
copy preserves that same relative layout under the package directory, the
whole directory can be moved/zipped/emailed anywhere and Google Earth will
still resolve the links -- this command verifies that by re-running the
portability check (export.validate) against the *copied* files, not the
originals, so it can't pass by accident against the wrong location.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from txdot_overlay.commands import build_boundaries, build_district
from txdot_overlay.config import Config
from txdot_overlay.export.kml_builder import county_kmz_relative_path
from txdot_overlay.export.validate import validate_master_kml
from txdot_overlay.logging_setup import get_logger
from txdot_overlay.pipeline import (
    counties_in_district,
    find_district_row,
    get_cache,
    load_counties,
    load_districts,
)
from txdot_overlay.utils import slugify

logger = get_logger(__name__)


def run(
    district_name: str,
    config: Config,
    *,
    output_dir: Path | None = None,
    force_refresh: bool = False,
) -> int:
    cache = get_cache(config)
    districts = load_districts(config, cache, force_refresh=force_refresh)
    counties = load_counties(config, cache, force_refresh=force_refresh)

    try:
        district_row = find_district_row(districts, config, district_name)
    except ValueError as exc:
        logger.error(str(exc))
        return 1

    district_fields = config.sources["districts"].fields
    resolved_district = district_row[district_fields["name"]]

    logger.info(
        "Rebuilding master.kml and %s District to ensure the package is current", resolved_district
    )
    boundaries_result = build_boundaries.run(config, force_refresh=force_refresh)
    district_result = build_district.run(resolved_district, config, force_refresh=force_refresh)
    if boundaries_result != 0 or district_result != 0:
        logger.error("Build step failed; not packaging incomplete output")
        return 1

    package_dir = output_dir or (Path.cwd() / "dist" / f"poc_{slugify(resolved_district)}")
    if package_dir.exists():
        shutil.rmtree(package_dir)
    package_dir.mkdir(parents=True)

    master_src = config.output_dir / config.master_kml_name
    master_dst = package_dir / config.master_kml_name
    shutil.copy2(master_src, master_dst)
    copied_files = [master_dst]

    district_counties = counties_in_district(counties, config, resolved_district)
    county_fields = config.sources["counties"].fields
    missing = []
    for _, county_row in district_counties.iterrows():
        county_name = county_row[county_fields["name"]]
        relative_path = county_kmz_relative_path(resolved_district, county_name)
        src = config.output_dir / relative_path
        if not src.exists():
            missing.append(county_name)
            continue
        dst = package_dir / relative_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied_files.append(dst)

    if missing:
        logger.error("Missing built KMZ for county/ies: %s", ", ".join(missing))
        return 1

    logger.info("Packaged %d file(s) into %s", len(copied_files), package_dir)

    # Verify portability against the COPY, not the original output directory --
    # this is the actual claim being made ("moving the folder still works").
    # Only the packaged district's own links should resolve; every other
    # district's county links are *expected* to warn "not found" since their
    # KMZs were never copied into this single-district package.
    report = validate_master_kml(master_dst, config)
    packaged_relative_paths = {
        county_kmz_relative_path(resolved_district, row[county_fields["name"]]).as_posix()
        for _, row in district_counties.iterrows()
    }
    broken_packaged_links = [
        w for w in report.warnings if any(p in w for p in packaged_relative_paths)
    ]
    expected_other_district_warnings = len(report.warnings) - len(broken_packaged_links)

    logger.info(
        "Portability check: %d error(s), %d broken link(s) within the packaged "
        "district (should be 0), %d expected warning(s) for other districts' "
        "unbuilt counties",
        len(report.errors),
        len(broken_packaged_links),
        expected_other_district_warnings,
    )
    for error in report.errors:
        logger.error("Portability check: %s", error)
    for warning in broken_packaged_links:
        logger.error("Portability check: broken link inside package: %s", warning)

    print(f"\nPackage directory: {package_dir}")
    for path in sorted(copied_files):
        size_kb = path.stat().st_size / 1024
        print(f"  {path.relative_to(package_dir.parent)}  ({size_kb:.0f} KB)")

    return 0 if report.ok and not broken_packaged_links else 1
