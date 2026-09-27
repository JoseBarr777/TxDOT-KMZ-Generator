"""`validate-offline-packages`: independently verify the District/Statewide
offline ZIP packages already on disk.

Read-only: never builds, rewrites, or repairs a package -- see
`commands/build_offline_packages.py` for that. This command answers "are the
packages on disk correct right now", checked against the standalone county
KMZ files on disk and the authoritative district/county source metadata,
never against the packages' own prior output or manifest.json.
"""

from __future__ import annotations

from txdot_overlay.config import Config
from txdot_overlay.export.offline_package_validate import validate_offline_packages
from txdot_overlay.logging_setup import get_logger
from txdot_overlay.pipeline import get_cache, load_counties, load_districts

logger = get_logger(__name__)


def _print_result(result, *, output_dir) -> None:
    status = "OK" if result.ok else "FAILED"
    print(f"{result.label}: {status}  ({result.path.relative_to(output_dir)})")
    for message in result.report.errors:
        print(f"  ERROR:   {message}")
    for message in result.report.warnings:
        print(f"  WARNING: {message}")


def run(config: Config, *, force_refresh: bool = False) -> int:
    cache = get_cache(config)
    districts = load_districts(config, cache, force_refresh=force_refresh)
    counties = load_counties(config, cache, force_refresh=force_refresh)

    result = validate_offline_packages(config, districts, counties)

    for district in result.districts:
        _print_result(district, output_dir=config.output_dir)
    _print_result(result.statewide, output_dir=config.output_dir)

    valid_districts = sum(1 for d in result.districts if d.ok)
    total_errors = sum(len(d.report.errors) for d in result.districts) + len(
        result.statewide.report.errors
    )

    print(f"\n{valid_districts}/{len(result.districts)} district package(s) valid")
    print(f"Statewide package valid: {result.statewide.ok}")
    print(f"Total errors: {total_errors}")

    return 0 if result.ok else 1
