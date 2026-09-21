"""`build-county`: build one county's detail KMZ (county boundary + classified roadways)."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd

from txdot_overlay.config import Config
from txdot_overlay.export.kml_builder import build_county_detail_kml, county_kmz_relative_path
from txdot_overlay.export.kmz_writer import save_kmz
from txdot_overlay.logging_setup import get_logger
from txdot_overlay.pipeline import (
    find_county_row,
    get_cache,
    load_city_limits,
    load_counties,
    load_roadways_for_county,
)
from txdot_overlay.processing.assignment import assign_counties_and_districts
from txdot_overlay.processing.classify import classify_routes
from txdot_overlay.processing.geometry import (
    clip_to_polygon,
    drop_invalid_geometries,
    simplify_geometry,
)
from txdot_overlay.styling.styles import StyleResolver

logger = get_logger(__name__)


def select_city_limits_for_county(
    city_limits: gpd.GeoDataFrame, single_county_gdf: gpd.GeoDataFrame
) -> gpd.GeoDataFrame:
    """Select cities intersecting one county, clipped to its boundary.

    `city_limits` (the statewide fetch) is never mutated -- the intersecting
    rows are selected from it with their full, unclipped source geometry
    intact, and a *separate* clipped copy is returned for rendering, so the
    full source geometry always remains recoverable from `city_limits`
    itself, per the "preserve full source geometry separately from
    render-only simplification" requirement (clipping/repair below still
    always run on the unsimplified geometry -- simplification for render
    happens later, inside kml_builder, exactly like county boundaries).
    """
    if city_limits.empty:
        return city_limits
    matched = gpd.sjoin(
        city_limits, single_county_gdf[["geometry"]], predicate="intersects", how="inner"
    )
    selected = city_limits.loc[matched.index.unique()]
    clipped = clip_to_polygon(selected, single_county_gdf)
    return drop_invalid_geometries(clipped, context="city limits")


def build_county(
    county_name: str,
    config: Config,
    *,
    counties: gpd.GeoDataFrame | None = None,
    city_limits: gpd.GeoDataFrame | None = None,
    force_refresh: bool = False,
) -> Path:
    """Build and save one county's detail KMZ. Returns the path written."""
    cache = get_cache(config)
    if counties is None:
        counties = load_counties(config, cache, force_refresh=force_refresh)
    if city_limits is None:
        city_limits = load_city_limits(config, cache, force_refresh=force_refresh)

    county_fields = config.sources["counties"].fields
    county_row = find_county_row(counties, config, county_name)
    resolved_name = county_row[county_fields["name"]]
    district_name = county_row[county_fields["district_name"]]
    county_number = county_row[county_fields["number"]]

    roadways = load_roadways_for_county(config, cache, county_number, force_refresh=force_refresh)
    logger.info(
        "%s County: %d raw roadway feature(s) fetched (CO=%s)",
        resolved_name,
        len(roadways),
        county_number,
    )

    single_county_gdf = counties.loc[[county_row.name]]
    roadways = assign_counties_and_districts(roadways, single_county_gdf, config)
    roadways = clip_to_polygon(roadways, single_county_gdf)
    roadways = drop_invalid_geometries(roadways, context=f"{resolved_name} clipped roadways")
    roadways = classify_routes(roadways, config)

    county_city_limits = select_city_limits_for_county(city_limits, single_county_gdf)
    logger.info(
        "%s County: %d city limit feature(s) selected/clipped",
        resolved_name,
        len(county_city_limits),
    )

    if config.simplification_enabled:
        before_vertex_estimate = len(roadways)
        roadways = simplify_geometry(roadways, config.simplification_tolerance_degrees)
        logger.info(
            "%s County: simplified geometry for %d feature(s) (tolerance=%s deg)",
            resolved_name,
            before_vertex_estimate,
            config.simplification_tolerance_degrees,
        )

    style_resolver = StyleResolver(config)
    kml = build_county_detail_kml(
        district_name=district_name,
        county_name=resolved_name,
        county_attrs=county_row.to_dict(),
        county_geometry=county_row.geometry,
        roadways=roadways,
        city_limits=county_city_limits,
        config=config,
        style_resolver=style_resolver,
    )

    relative_path = county_kmz_relative_path(district_name, resolved_name)
    output_path = config.output_dir / relative_path
    save_kmz(kml, output_path)
    return output_path


def run(county_name: str, config: Config, *, force_refresh: bool = False) -> int:
    try:
        build_county(county_name, config, force_refresh=force_refresh)
    except ValueError as exc:
        logger.error(str(exc))
        return 1
    return 0
