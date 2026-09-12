"""Shared data-loading helpers used by more than one CLI command.

Keeps the "fetch (cached) -> GeoDataFrame -> WGS84" plumbing in one place so
commands only deal with already-clean GeoDataFrames.
"""
from __future__ import annotations

import geopandas as gpd

from txdot_overlay.acquisition.cache import DiskCache
from txdot_overlay.acquisition.fetch import fetch_source_features
from txdot_overlay.config import Config
from txdot_overlay.processing.geometry import drop_invalid_geometries, geojson_to_geodataframe


def get_cache(config: Config) -> DiskCache:
    return DiskCache(config.cache_dir)


def load_districts(config: Config, cache: DiskCache, *, force_refresh: bool = False) -> gpd.GeoDataFrame:
    source = config.sources["districts"]
    entry = fetch_source_features(source, config, cache, force_refresh=force_refresh)
    gdf = geojson_to_geodataframe(entry.data)
    return drop_invalid_geometries(gdf, context="districts")


def load_counties(config: Config, cache: DiskCache, *, force_refresh: bool = False) -> gpd.GeoDataFrame:
    source = config.sources["counties"]
    entry = fetch_source_features(source, config, cache, force_refresh=force_refresh)
    gdf = geojson_to_geodataframe(entry.data)
    return drop_invalid_geometries(gdf, context="counties")


def load_roadways_for_county(
    config: Config,
    cache: DiskCache,
    county_number: int,
    *,
    force_refresh: bool = False,
) -> gpd.GeoDataFrame:
    source = config.sources["roadways"]
    county_code_field = source.fields["county_code"]
    where = f"{county_code_field} = {int(county_number)}"
    entry = fetch_source_features(source, config, cache, where=where, force_refresh=force_refresh)
    gdf = geojson_to_geodataframe(entry.data)
    return drop_invalid_geometries(gdf, context=f"roadways (county={county_number})")


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
