"""Builds simplekml Style objects from configured colors/widths."""

from __future__ import annotations

import simplekml

from txdot_overlay.config import Config, PolygonStyleConfig, RouteStyleConfig
from txdot_overlay.logging_setup import get_logger
from txdot_overlay.styling.colors import hex_to_kml_color

logger = get_logger(__name__)


def polygon_style(style_config: PolygonStyleConfig) -> simplekml.Style:
    """Build an outline-only (or filled) polygon style, e.g. district/county boundaries."""
    style = simplekml.Style()
    style.linestyle.color = hex_to_kml_color(style_config.line_color)
    style.linestyle.width = style_config.line_width
    style.polystyle.fill = 1 if style_config.fill else 0
    style.polystyle.outline = 1
    style.polystyle.color = hex_to_kml_color(style_config.fill_color, style_config.fill_opacity)
    return style


def route_style(style_config: RouteStyleConfig) -> simplekml.Style:
    """Build a line style for one roadway category (interstate, US highway, etc.).

    `dashed` is honored only in spirit: standard KML 2.2 LineStyle has no
    dash-pattern property, and Google Earth Pro does not reliably render
    dashed polylines through any documented extension. Requesting it here
    does not silently no-op -- it logs so the gap is visible -- and falls
    back to the configured solid line at its configured (already thin/muted)
    width, which is what actually ships.
    """
    if style_config.dashed:
        logger.warning(
            "Style %r requests a dashed line, but KML 2.2 has no reliable "
            "dash-pattern support in Google Earth Pro; rendering solid instead.",
            style_config.label,
        )
    style = simplekml.Style()
    style.linestyle.color = hex_to_kml_color(style_config.line_color)
    style.linestyle.width = style_config.line_width
    return style


def build_all_styles(config: Config) -> dict[str, simplekml.Style]:
    """Build every configured style up front, keyed for reuse across placemarks."""
    styles: dict[str, simplekml.Style] = {
        "district_boundary": polygon_style(config.district_style),
        "county_boundary": polygon_style(config.county_style),
        "city_limits_boundary": polygon_style(config.city_limits_style),
    }
    for category, route_cfg in config.route_styles.items():
        styles[f"route_{category}"] = route_style(route_cfg)
    return styles
