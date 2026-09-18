"""Geometry conversion, coordinate reprojection, clipping, and simplification.

All Google Earth output must be WGS84 lon/lat (EPSG:4326). ArcGIS returns
GeoJSON already in EPSG:4326 per the GeoJSON spec, but we verify/enforce
this explicitly here rather than trusting it silently, and this is the one
place reprojection happens so callers never juggle coordinate systems.
"""

from __future__ import annotations

from typing import Any

import geopandas as gpd
from shapely.validation import make_valid

from txdot_overlay.logging_setup import get_logger

logger = get_logger(__name__)

WGS84_EPSG = 4326


def geojson_to_geodataframe(
    geojson: dict[str, Any], *, assumed_source_epsg: int = WGS84_EPSG
) -> gpd.GeoDataFrame:
    """Build a GeoDataFrame from an ArcGIS GeoJSON response.

    ArcGIS's `f=geojson` output carries no CRS member because GeoJSON's
    default CRS (per RFC 7946) is WGS84 -- so `assumed_source_epsg` should
    normally stay at 4326. It is exposed so a caller working from a
    different source format can still route through the same reprojection
    and gets an explicit, auditable conversion rather than a silent guess.
    """
    features = geojson.get("features", [])
    gdf = gpd.GeoDataFrame.from_features(features, crs=f"EPSG:{assumed_source_epsg}")
    return ensure_wgs84(gdf)


def ensure_wgs84(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Reproject to EPSG:4326 if needed; assign it if the frame has no CRS set."""
    if gdf.crs is None:
        logger.warning("GeoDataFrame has no CRS set; assuming EPSG:%d", WGS84_EPSG)
        return gdf.set_crs(epsg=WGS84_EPSG)
    if gdf.crs.to_epsg() != WGS84_EPSG:
        logger.info("Reprojecting from %s to EPSG:%d", gdf.crs, WGS84_EPSG)
        return gdf.to_crs(epsg=WGS84_EPSG)
    return gdf


def clip_to_polygon(
    gdf: gpd.GeoDataFrame, boundary: gpd.GeoDataFrame | gpd.GeoSeries
) -> gpd.GeoDataFrame:
    """Clip features to a boundary polygon, splitting geometries that cross it.

    Used to cut roads that cross county boundaries and to exclude roadway
    geometry outside the selected output area.
    """
    if gdf.empty:
        return gdf
    clipped = gpd.clip(gdf, boundary)
    clipped = clipped[~clipped.geometry.is_empty & clipped.geometry.notna()]
    dropped = len(gdf) - len(clipped)
    if dropped > 0:
        logger.info("Clipping removed %d feature(s) outside the boundary", dropped)
    return clipped


def simplify_geometry(gdf: gpd.GeoDataFrame, tolerance_degrees: float) -> gpd.GeoDataFrame:
    """Simplify geometry (topology-preserving) to reduce vertex count for performance."""
    if gdf.empty or tolerance_degrees <= 0:
        return gdf
    result = gdf.copy()
    result["geometry"] = result.geometry.simplify(tolerance_degrees, preserve_topology=True)
    return result


def repair_geometry(geometry):
    """Attempt to repair an invalid geometry with shapely's `make_valid`.

    Returns the repaired geometry, or None if it is null/empty/unrepairable
    (still invalid, or repairs to empty). Never mutates the input.
    """
    if geometry is None or geometry.is_empty:
        return None
    if geometry.is_valid:
        return geometry
    repaired = make_valid(geometry)
    if repaired is None or repaired.is_empty or not repaired.is_valid:
        return None
    return repaired


def drop_invalid_geometries(gdf: gpd.GeoDataFrame, *, context: str = "") -> gpd.GeoDataFrame:
    """Remove null/empty/invalid geometries, logging how many were skipped."""
    if gdf.empty:
        return gdf
    # Checked per-geometry (rather than vectorized .notna()/.is_empty()) to
    # avoid ambiguous None-vs-empty handling across geopandas versions.
    valid_mask = gdf.geometry.apply(
        lambda geom: geom is not None and not geom.is_empty and geom.is_valid
    )
    invalid_count = (~valid_mask).sum()
    if invalid_count:
        logger.warning(
            "Skipping %d invalid/empty geometr%s%s",
            invalid_count,
            "y" if invalid_count == 1 else "ies",
            f" ({context})" if context else "",
        )
    return gdf[valid_mask]
