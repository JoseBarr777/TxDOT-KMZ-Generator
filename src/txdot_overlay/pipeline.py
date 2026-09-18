"""Shared data-loading helpers used by more than one CLI command.

Keeps the "fetch (cached) -> GeoDataFrame -> WGS84" plumbing in one place so
commands only deal with already-clean GeoDataFrames.
"""

from __future__ import annotations

import geopandas as gpd

from txdot_overlay.acquisition.cache import DiskCache
from txdot_overlay.acquisition.fetch import fetch_source_features
from txdot_overlay.config import Config, SourceConfig
from txdot_overlay.logging_setup import get_logger
from txdot_overlay.processing.diagnostics import GeometryIssue, repair_and_flag_geometries
from txdot_overlay.processing.geometry import geojson_to_geodataframe

logger = get_logger(__name__)


def get_cache(config: Config) -> DiskCache:
    return DiskCache(config.cache_dir)


def load_and_repair(
    source: SourceConfig,
    config: Config,
    cache: DiskCache,
    *,
    id_field: str,
    name_field: str,
    where: str = "1=1",
    force_refresh: bool = False,
) -> tuple[gpd.GeoDataFrame, list[GeometryIssue], gpd.GeoDataFrame]:
    """Fetch (cached) + repair-or-flag every feature's geometry.

    Returns (final_gdf, issues, raw_gdf) -- `raw_gdf` is the pre-repair frame
    exactly as downloaded, kept around so audit-data can report duplicate IDs
    and downloaded-vs-final counts without a second fetch.
    """
    entry = fetch_source_features(source, config, cache, where=where, force_refresh=force_refresh)
    raw_gdf = geojson_to_geodataframe(entry.data)
    final_gdf, issues = repair_and_flag_geometries(
        raw_gdf, id_field=id_field, name_field=name_field, context=source.label
    )
    return final_gdf, issues, raw_gdf


def _log_issue_summary(
    label: str, downloaded_count: int, final_count: int, issues: list[GeometryIssue]
) -> None:
    repaired = sum(1 for i in issues if i.status == "repaired")
    dropped = sum(1 for i in issues if i.dropped)
    logger.info(
        "%s: %d downloaded, %d repaired, %d dropped, %d final",
        label,
        downloaded_count,
        repaired,
        dropped,
        final_count,
    )
    if dropped:
        for issue in issues:
            if issue.dropped:
                logger.warning(
                    "%s: EXCLUDED %s (id=%s): %s (%s)",
                    label,
                    issue.name,
                    issue.id_value,
                    issue.status,
                    issue.reason,
                )


def load_districts(
    config: Config, cache: DiskCache, *, force_refresh: bool = False
) -> gpd.GeoDataFrame:
    source = config.sources["districts"]
    fields = source.fields
    final_gdf, issues, raw_gdf = load_and_repair(
        source,
        config,
        cache,
        id_field=fields["number"],
        name_field=fields["name"],
        force_refresh=force_refresh,
    )
    _log_issue_summary(source.label, len(raw_gdf), len(final_gdf), issues)
    return final_gdf


def load_counties(
    config: Config, cache: DiskCache, *, force_refresh: bool = False
) -> gpd.GeoDataFrame:
    source = config.sources["counties"]
    fields = source.fields
    final_gdf, issues, raw_gdf = load_and_repair(
        source,
        config,
        cache,
        id_field=fields["number"],
        name_field=fields["name"],
        force_refresh=force_refresh,
    )
    _log_issue_summary(source.label, len(raw_gdf), len(final_gdf), issues)
    return final_gdf


def load_city_limits(
    config: Config, cache: DiskCache, *, force_refresh: bool = False
) -> gpd.GeoDataFrame:
    """Fetch the statewide city-limits layer (1,227 features -- one page, cheap to cache).

    No per-county `where` scoping: the city layer has no county-code column,
    so county scoping happens spatially downstream (select cities
    intersecting a county, then clip cross-county cities to its boundary) --
    see commands/build_county.py.
    """
    source = config.sources["city_limits"]
    fields = source.fields
    final_gdf, issues, raw_gdf = load_and_repair(
        source,
        config,
        cache,
        id_field=fields["object_id"],
        name_field=fields["name"],
        force_refresh=force_refresh,
    )
    _log_issue_summary(source.label, len(raw_gdf), len(final_gdf), issues)
    return final_gdf


def load_roadways_for_county(
    config: Config,
    cache: DiskCache,
    county_number: int,
    *,
    force_refresh: bool = False,
) -> gpd.GeoDataFrame:
    source = config.sources["roadways"]
    fields = source.fields
    where = f"{fields['county_code']} = {int(county_number)}"
    final_gdf, issues, raw_gdf = load_and_repair(
        source,
        config,
        cache,
        id_field=fields["object_id"],
        name_field=fields["highway_full"],
        where=where,
        force_refresh=force_refresh,
    )
    _log_issue_summary(
        f"{source.label} (county={county_number})", len(raw_gdf), len(final_gdf), issues
    )
    return final_gdf


def find_county_row(counties: gpd.GeoDataFrame, config: Config, county_name: str):
    """Case-insensitive exact match on the county name field. Raises if not found."""
    name_field = config.sources["counties"].fields["name"]
    matches = counties[counties[name_field].str.lower() == county_name.strip().lower()]
    if matches.empty:
        available = ", ".join(sorted(counties[name_field].unique()))
        raise ValueError(f"County {county_name!r} not found. Available: {available}")
    if len(matches) > 1:
        raise ValueError(f"Multiple counties matched {county_name!r}; expected exactly one.")
    return matches.iloc[0]


def find_district_row(districts: gpd.GeoDataFrame, config: Config, district_name: str):
    """Case-insensitive exact match on the district name field. Raises if not found."""
    name_field = config.sources["districts"].fields["name"]
    matches = districts[districts[name_field].str.lower() == district_name.strip().lower()]
    if matches.empty:
        available = ", ".join(sorted(districts[name_field].unique()))
        raise ValueError(f"District {district_name!r} not found. Available: {available}")
    if len(matches) > 1:
        raise ValueError(f"Multiple districts matched {district_name!r}; expected exactly one.")
    return matches.iloc[0]


def counties_in_district(
    counties: gpd.GeoDataFrame, config: Config, district_name: str
) -> gpd.GeoDataFrame:
    district_field = config.sources["counties"].fields["district_name"]
    return counties[
        counties[district_field].str.lower() == district_name.strip().lower()
    ].sort_values(config.sources["counties"].fields["name"])
