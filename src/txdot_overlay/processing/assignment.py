"""Assigns each roadway feature to a county/district, preferring existing attributes.

The roadway inventory's CO/DI fields are numeric codes with no name text on
that layer. CO has been verified to match the county layer's CNTY_NBR (e.g.
Smith County: CNTY_NBR=212, roadway CO=212), so the attribute join below is
reliable and used first. A spatial join against county polygons is used only
as a fallback for rows where the code is missing or does not match any known
county -- this keeps the common case fast (no geometry operations) while
still handling bad/unmapped codes correctly.
"""
from __future__ import annotations

import geopandas as gpd

from txdot_overlay.config import Config
from txdot_overlay.logging_setup import get_logger

logger = get_logger(__name__)


def assign_county_by_code(
    roadways: gpd.GeoDataFrame, counties: gpd.GeoDataFrame, config: Config
) -> gpd.GeoDataFrame:
    """Attach county name/number/district columns to roadways via the CO code."""
    county_fields = config.sources["counties"].fields
    road_fields = config.sources["roadways"].fields

    county_lookup = counties[
        [
            county_fields["number"],
            county_fields["name"],
            county_fields["district_name"],
            county_fields["district_number"],
        ]
    ].rename(
        columns={
            county_fields["number"]: "_assigned_county_number",
            county_fields["name"]: "assigned_county_name",
            county_fields["district_name"]: "assigned_district_name",
            county_fields["district_number"]: "assigned_district_number",
        }
    )

    result = roadways.merge(
        county_lookup,
        how="left",
        left_on=road_fields["county_code"],
        right_on="_assigned_county_number",
    ).drop(columns=["_assigned_county_number"])

    unmatched = result["assigned_county_name"].isna().sum()
    if unmatched:
        logger.warning(
            "%d roadway feature(s) had a county code with no matching county "
            "(will fall back to spatial join)",
            unmatched,
        )
    return gpd.GeoDataFrame(result, geometry="geometry", crs=roadways.crs)


def assign_county_by_spatial_join(
    roadways: gpd.GeoDataFrame, counties: gpd.GeoDataFrame, config: Config
) -> gpd.GeoDataFrame:
    """Fill in county/district assignment for rows the attribute join missed."""
    county_fields = config.sources["counties"].fields
    needs_join = roadways["assigned_county_name"].isna()
    if not needs_join.any():
        return roadways

    joined = gpd.sjoin(
        roadways[needs_join].drop(
            columns=[
                "assigned_county_name",
                "assigned_district_name",
                "assigned_district_number",
            ]
        ),
        counties[
            [
                county_fields["name"],
                county_fields["district_name"],
                county_fields["district_number"],
                "geometry",
            ]
        ].rename(
            columns={
                county_fields["name"]: "assigned_county_name",
                county_fields["district_name"]: "assigned_district_name",
                county_fields["district_number"]: "assigned_district_number",
            }
        ),
        how="left",
        predicate="intersects",
    ).drop(columns=["index_right"], errors="ignore")

    # sjoin can duplicate rows for features that intersect multiple counties
    # (e.g. right on a boundary); keep the first match deterministically.
    joined = joined[~joined.index.duplicated(keep="first")]

    result = roadways.copy()
    result.update(joined)
    still_unmatched = result["assigned_county_name"].isna().sum()
    if still_unmatched:
        logger.warning(
            "%d roadway feature(s) could not be assigned to any county", still_unmatched
        )
    return result


def assign_counties_and_districts(
    roadways: gpd.GeoDataFrame, counties: gpd.GeoDataFrame, config: Config
) -> gpd.GeoDataFrame:
    by_code = assign_county_by_code(roadways, counties, config)
    return assign_county_by_spatial_join(by_code, counties, config)
