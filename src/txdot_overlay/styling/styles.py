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


class StyleResolver:
    """Single point of lookup from a feature/category to its KML style.

    Built once per run (styles are shared simplekml.Style instances so
    placemarks reuse them rather than each inlining its own copy) and
    threaded through the exporters in place of a raw dict, so call sites
    ask for a style by logical name (`resolver.route("interstate")`)
    instead of constructing dict keys themselves.

    This is also the seam a later change adds highlight StyleMaps at:
    `route()`/the boundary accessors can start returning StyleMap-backed
    references without any exporter call site changing.
    """

    def __init__(self, config: Config) -> None:
        self._district_boundary = polygon_style(config.district_style)
        self._county_boundary = polygon_style(config.county_style)
        self._city_limits_boundary = polygon_style(config.city_limits_style)
        self._routes: dict[str, simplekml.Style] = {
            category: route_style(route_cfg) for category, route_cfg in config.route_styles.items()
        }

    def district_boundary(self) -> simplekml.Style:
        return self._district_boundary

    def county_boundary(self) -> simplekml.Style:
        return self._county_boundary

    def city_limits_boundary(self) -> simplekml.Style:
        return self._city_limits_boundary

    def route(self, category: str) -> simplekml.Style:
        """Style for one roadway category (interstate, county_road, grade_separated_connector, ...)."""
        try:
            return self._routes[category]
        except KeyError:
            raise KeyError(f"No style configured for route category {category!r}") from None
