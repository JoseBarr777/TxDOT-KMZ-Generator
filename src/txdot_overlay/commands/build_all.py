"""`build-all`: build master.kml plus every (or a scoped set of) county detail KMZ.

Scope with --district to keep this to a proof-of-concept subset (e.g. just
Tyler) instead of all 254 counties statewide -- see the project README for
why the statewide run should be validated at small scale first.
"""

from __future__ import annotations

import geopandas as gpd

from txdot_overlay.commands.build_county import build_county, select_city_limits_for_county
from txdot_overlay.commands.build_distribution import build_distribution_artifacts
from txdot_overlay.config import Config
from txdot_overlay.export.kml_builder import build_master_kml, build_single_file_kml
from txdot_overlay.export.kmz_writer import save_kml, save_kmz
from txdot_overlay.logging_setup import get_logger
from txdot_overlay.pipeline import (
    get_cache,
    load_city_limits,
    load_counties,
    load_districts,
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


def run(
    config: Config,
    *,
    districts_filter: list[str] | None = None,
    single_file: bool = False,
    force_refresh: bool = False,
) -> int:
    cache = get_cache(config)
    districts = load_districts(config, cache, force_refresh=force_refresh)
    counties = load_counties(config, cache, force_refresh=force_refresh)
    city_limits = load_city_limits(config, cache, force_refresh=force_refresh)

    style_resolver = StyleResolver(config)

    master_kml = build_master_kml(districts, counties, config, style_resolver)
    save_kml(master_kml, config.output_dir / config.master_kml_name)

    # Boundary-only products: free here, since the three source GeoDataFrames
    # they need are already loaded above.
    build_distribution_artifacts(config, districts, counties, city_limits, style_resolver)

    if districts_filter:
        scope = counties[
            counties[config.sources["counties"].fields["district_name"]]
            .str.lower()
            .isin([d.lower() for d in districts_filter])
        ]
    else:
        scope = counties
        logger.warning(
            "No --district filter given: building all %d counties statewide. "
            "This downloads the full TxDOT Roadway Inventory and will take a while.",
            len(counties),
        )

    if scope.empty:
        logger.error("No counties matched district filter: %s", districts_filter)
        return 1

    county_field = config.sources["counties"].fields["name"]
    county_roadways: dict[str, gpd.GeoDataFrame] = {}
    county_city_limits: dict[str, gpd.GeoDataFrame] = {}
    exit_code = 0

    for _, county_row in scope.iterrows():
        county_name = county_row[county_field]
        try:
            build_county(
                county_name,
                config,
                counties=counties,
                city_limits=city_limits,
                force_refresh=force_refresh,
            )
            if single_file:
                roadways, clipped_city_limits = _rebuild_processed_roadways(
                    county_row, counties, city_limits, config, cache, force_refresh
                )
                county_roadways[county_name] = roadways
                county_city_limits[county_name] = clipped_city_limits
        except Exception as exc:  # noqa: BLE001 - continue building remaining counties
            logger.error("Failed to build county %s: %s", county_name, exc)
            exit_code = 1

    if single_file:
        single_kml = build_single_file_kml(
            districts, counties, county_roadways, county_city_limits, config, style_resolver
        )
        save_kmz(single_kml, config.output_dir / config.single_file_kmz_name)

    return exit_code


def _rebuild_processed_roadways(county_row, counties, city_limits, config, cache, force_refresh):
    """Re-run the same processing pipeline build_county used, for single-file assembly.

    Kept intentionally separate from build_county (which saves its own KMZ)
    so single-file assembly doesn't require build_county to return internal
    state -- the cache makes the repeated fetch cheap.
    """
    county_fields = config.sources["counties"].fields
    county_number = county_row[county_fields["number"]]
    roadways = load_roadways_for_county(config, cache, county_number, force_refresh=force_refresh)
    single_county_gdf = counties.loc[[county_row.name]]
    roadways = assign_counties_and_districts(roadways, single_county_gdf, config)
    roadways = clip_to_polygon(roadways, single_county_gdf)
    roadways = drop_invalid_geometries(
        roadways, context=f"{county_row[county_fields['name']]} (single-file)"
    )
    roadways = classify_routes(roadways, config)
    if config.simplification_enabled:
        roadways = simplify_geometry(roadways, config.simplification_tolerance_degrees)
    clipped_city_limits = select_city_limits_for_county(city_limits, single_county_gdf)
    return roadways, clipped_city_limits
