"""Classifies roadway features into styling categories from their HSYS code."""
from __future__ import annotations

import geopandas as gpd

from txdot_overlay.config import Config


def classify_routes(roadways: gpd.GeoDataFrame, config: Config) -> gpd.GeoDataFrame:
    """Add a `route_category` column derived from the HSYS field via config mapping."""
    hsys_field = config.sources["roadways"].fields["highway_system"]
    result = roadways.copy()
    result["route_category"] = result[hsys_field].apply(config.route_category)
    return result
