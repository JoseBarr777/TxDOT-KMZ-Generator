"""Adapts shapely geometries into simplekml placemarks.

Isolated from kml_builder so the "how do I turn a shapely Polygon/LineString
(incl. Multi* variants) into simplekml calls" logic has one place to live
and one place to test.
"""
from __future__ import annotations

from typing import Any

import simplekml
from shapely.geometry.base import BaseGeometry

from txdot_overlay.logging_setup import get_logger

logger = get_logger(__name__)


def _polygon_boundaries(polygon) -> tuple[list[tuple[float, float]], list[list[tuple[float, float]]]]:
    outer = list(polygon.exterior.coords)
    inner = [list(ring.coords) for ring in polygon.interiors]
    return outer, inner


def add_polygon_placemark(
    container: Any,
    *,
    name: str,
    geometry: BaseGeometry,
    style: simplekml.Style,
    description: str | None = None,
    visibility: bool = True,
) -> simplekml.Placemark | None:
    """Add a Polygon or MultiPolygon as a placemark. Returns None if unsupported."""
    geom_type = geometry.geom_type
    if geom_type == "Polygon":
        placemark = container.newpolygon(name=name)
        outer, inner = _polygon_boundaries(geometry)
        placemark.outerboundaryis = outer
        if inner:
            placemark.innerboundaryis = inner
    elif geom_type == "MultiPolygon":
        placemark = container.newmultigeometry(name=name)
        for part in geometry.geoms:
            poly = placemark.newpolygon()
            outer, inner = _polygon_boundaries(part)
            poly.outerboundaryis = outer
            if inner:
                poly.innerboundaryis = inner
    else:
        logger.warning("Skipping unsupported polygon geometry type: %s", geom_type)
        return None

    placemark.style = style
    placemark.visibility = 1 if visibility else 0
    if description is not None:
        placemark.description = description
    return placemark


def add_line_placemark(
    container: Any,
    *,
    name: str,
    geometry: BaseGeometry,
    style: simplekml.Style,
    description: str | None = None,
    visibility: bool = True,
) -> simplekml.Placemark | None:
    """Add a LineString or MultiLineString as a placemark. Returns None if unsupported."""
    geom_type = geometry.geom_type
    if geom_type == "LineString":
        placemark = container.newlinestring(name=name)
        placemark.coords = list(geometry.coords)
    elif geom_type == "MultiLineString":
        placemark = container.newmultigeometry(name=name)
        for part in geometry.geoms:
            line = placemark.newlinestring()
            line.coords = list(part.coords)
    else:
        logger.warning("Skipping unsupported line geometry type: %s", geom_type)
        return None

    placemark.style = style
    placemark.visibility = 1 if visibility else 0
    if description is not None:
        placemark.description = description
    return placemark
