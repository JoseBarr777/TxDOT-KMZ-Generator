"""`build-offline-packages`: package already-built county KMZs into District/
Statewide offline ZIPs.

Standalone for now -- it consumes whatever county KMZs `build-all`/
`build-county`/`build-district` already left on disk, the same way
`build-distribution` is a standalone entry point over already-loaded
district/county reference data. A later step will call this automatically
from `build-all`; until then the normal two-command sequence is:

    txdot-overlay build-all
    txdot-overlay build-offline-packages
"""

from __future__ import annotations

from txdot_overlay.config import Config
from txdot_overlay.export.offline_package import build_offline_packages
from txdot_overlay.logging_setup import get_logger
from txdot_overlay.pipeline import get_cache, load_counties, load_districts

logger = get_logger(__name__)


def run(config: Config, *, force_refresh: bool = False) -> int:
    cache = get_cache(config)
    districts = load_districts(config, cache, force_refresh=force_refresh)
    counties = load_counties(config, cache, force_refresh=force_refresh)

    result = build_offline_packages(config, districts, counties)

    built = result.built_districts
    skipped = result.skipped_districts

    print(
        f"Built {len(built)}/{len(result.districts)} district offline package(s) "
        f"under {config.output_dir}"
    )
    for district in built:
        size_kb = district.path.stat().st_size / 1024
        print(f"  {district.path.relative_to(config.output_dir)}  ({size_kb:.0f} KB)")
    for district in skipped:
        print(
            f"  SKIPPED {district.district_name} District: "
            f"missing {len(district.missing_counties)} county KMZ(s): "
            f"{', '.join(district.missing_counties)}"
        )

    if result.statewide_built:
        size_kb = result.statewide_path.stat().st_size / 1024
        print(
            f"Statewide offline package: "
            f"{result.statewide_path.relative_to(config.output_dir)}  ({size_kb:.0f} KB)"
        )
    else:
        print(
            f"Statewide offline package SKIPPED: "
            f"{len(result.statewide_missing_counties)} county KMZ(s) missing statewide"
        )

    return 0 if not skipped and result.statewide_built else 1
