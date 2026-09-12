"""Builds simplekml Style objects from configured colors/widths."""
from __future__ import annotations

import simplekml

from txdot_overlay.config import Config, PolygonStyleConfig, RouteStyleConfig
from txdot_overlay.styling.colors import hex_to_kml_color


def polygon_style(style_config: PolygonStyleConfig) -> simplekml.Style:
    """Build an outline-only (or filled) polygon style, e.g. district/county boundaries."""
    style = simplekml.Style()
    style.linestyle.color = hex_to_kml_color(style_config.line_color)
    style.linestyle.width = style_config.line_width
    style.polystyle.fill = 1 if style_config.fill else 0
    style.polystyle.outline = 1
    style.polystyle.color = hex_to_kml_color(
        style_config.fill_color, style_config.fill_opacity
    )
    return style


def route_style(style_config: RouteStyleConfig) -> simplekml.Style:
    """Build a line style for one roadway category (interstate, US highway, etc.)."""
    style = simplekml.Style()
    style.linestyle.color = hex_to_kml_color(style_config.line_color)
    style.linestyle.width = style_config.line_width
    return style


def build_all_styles(config: Config) -> dict[str, simplekml.Style]:
    """Build every configured style up front, keyed for reuse across placemarks."""
    styles: dict[str, simplekml.Style] = {
        "district_boundary": polygon_style(config.district_style),
        "county_boundary": polygon_style(config.county_style),
    }
    for category, route_cfg in config.route_styles.items():
        styles[f"route_{category}"] = route_style(route_cfg)
    return styles
