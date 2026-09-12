"""`build-district`: build the detail KMZ for every county belonging to one district."""
from __future__ import annotations

from txdot_overlay.commands.build_county import build_county
from txdot_overlay.config import Config
from txdot_overlay.logging_setup import get_logger
from txdot_overlay.pipeline import counties_in_district, find_district_row, get_cache, load_counties, load_districts

logger = get_logger(__name__)


def run(district_name: str, config: Config, *, force_refresh: bool = False) -> int:
    cache = get_cache(config)
    districts = load_districts(config, cache, force_refresh=force_refresh)
    counties = load_counties(config, cache, force_refresh=force_refresh)

    try:
        district_row = find_district_row(districts, config, district_name)
    except ValueError as exc:
        logger.error(str(exc))
        return 1

    district_fields = config.sources["districts"].fields
    resolved_name = district_row[district_fields["name"]]
    district_counties = counties_in_district(counties, config, resolved_name)

    if district_counties.empty:
        logger.warning("No counties found for district %r", resolved_name)
        return 1

    county_field = config.sources["counties"].fields["name"]
    logger.info(
        "%s District: building %d county/ies: %s",
        resolved_name,
        len(district_counties),
        ", ".join(district_counties[county_field]),
    )

    exit_code = 0
    for _, county_row in district_counties.iterrows():
        county_name = county_row[county_field]
        try:
            build_county(county_name, config, counties=counties, force_refresh=force_refresh)
        except Exception as exc:  # noqa: BLE001 - continue building remaining counties
            logger.error("Failed to build county %s: %s", county_name, exc)
            exit_code = 1

    return exit_code
