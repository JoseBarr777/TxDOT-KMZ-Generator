"""`build-distribution`: build the browse-by-district KMLs and administrative-only artifacts.

These are all pure boundary products -- they need districts, counties, and
city limits, and nothing from the roadway inventory. `build-all` already
loads exactly those three GeoDataFrames, so it calls
`build_distribution_artifacts` directly with them rather than re-fetching;
this command exists as a standalone entry point so the distribution set can
be regenerated in seconds without rebuilding all 254 county KMZs.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd

from txdot_overlay.config import Config
from txdot_overlay.export.kml_builder import (
    ADMIN_BOUNDARIES_KMZ,
    CITY_BOUNDARIES_KMZ,
    COUNTY_BOUNDARIES_KMZ,
    DISTRICT_BOUNDARIES_KMZ,
    build_admin_boundaries_kml,
    build_city_boundaries_kml,
    build_county_boundaries_kml,
    build_district_boundaries_kml,
    build_district_kml,
    district_kml_relative_path,
)
from txdot_overlay.export.kmz_writer import save_kml, save_kmz
from txdot_overlay.logging_setup import get_logger
from txdot_overlay.pipeline import get_cache, load_city_limits, load_counties, load_districts
from txdot_overlay.styling.styles import StyleResolver

logger = get_logger(__name__)


def build_distribution_artifacts(
    config: Config,
    districts: gpd.GeoDataFrame,
    counties: gpd.GeoDataFrame,
    city_limits: gpd.GeoDataFrame,
    style_resolver: StyleResolver,
) -> list[Path]:
    """Write every district KML and administrative-only artifact. Returns paths written.

    Districts are emitted for the full statewide district list regardless of
    any county-build scope, exactly like master.kml's NetworkLinks: a
    district KML that references a not-yet-built county is a resolvable-later
    link, not an error (the manifest is what decides whether the release is
    complete).
    """
    district_fields = config.sources["districts"].fields
    county_fields = config.sources["counties"].fields
    written: list[Path] = []

    district_names = sorted(districts[district_fields["name"]].dropna().unique())
    for district_name in district_names:
        district_row = districts[districts[district_fields["name"]] == district_name].iloc[0]
        district_counties = counties[counties[county_fields["district_name"]] == district_name]
        kml = build_district_kml(
            district_name=str(district_name),
            district_attrs=district_row.to_dict(),
            district_geometry=district_row.geometry,
            district_counties=district_counties,
            config=config,
            style_resolver=style_resolver,
        )
        written.append(
            save_kml(kml, config.output_dir / district_kml_relative_path(str(district_name)))
        )

    written.append(
        save_kmz(
            build_district_boundaries_kml(districts, config, style_resolver),
            config.output_dir / DISTRICT_BOUNDARIES_KMZ,
        )
    )
    written.append(
        save_kmz(
            build_county_boundaries_kml(counties, config, style_resolver),
            config.output_dir / COUNTY_BOUNDARIES_KMZ,
        )
    )
    written.append(
        save_kmz(
            build_city_boundaries_kml(city_limits, config, style_resolver),
            config.output_dir / CITY_BOUNDARIES_KMZ,
        )
    )
    written.append(
        save_kmz(
            build_admin_boundaries_kml(districts, counties, city_limits, config, style_resolver),
            config.output_dir / ADMIN_BOUNDARIES_KMZ,
        )
    )

    logger.info(
        "Distribution artifacts: %d district KML(s) + 4 administrative boundary artifact(s)",
        len(district_names),
    )
    return written


def run(config: Config, *, force_refresh: bool = False) -> int:
    cache = get_cache(config)
    districts = load_districts(config, cache, force_refresh=force_refresh)
    counties = load_counties(config, cache, force_refresh=force_refresh)
    city_limits = load_city_limits(config, cache, force_refresh=force_refresh)

    style_resolver = StyleResolver(config)
    written = build_distribution_artifacts(config, districts, counties, city_limits, style_resolver)

    print(f"Wrote {len(written)} distribution artifact(s) under {config.output_dir}")
    for path in written:
        size_kb = path.stat().st_size / 1024
        print(f"  {path.relative_to(config.output_dir)}  ({size_kb:.0f} KB)")
    return 0
