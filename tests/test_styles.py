import pytest

from txdot_overlay.styling.colors import hex_to_kml_color
from txdot_overlay.styling.styles import StyleResolver


def test_district_boundary_matches_config(config):
    resolver = StyleResolver(config)
    style = resolver.district_boundary()
    assert style.linestyle.color == hex_to_kml_color(config.district_style.line_color)
    assert style.linestyle.width == config.district_style.line_width


def test_county_boundary_matches_config(config):
    resolver = StyleResolver(config)
    style = resolver.county_boundary()
    assert style.linestyle.color == hex_to_kml_color(config.county_style.line_color)
    assert style.linestyle.width == config.county_style.line_width


def test_city_limits_boundary_matches_config(config):
    resolver = StyleResolver(config)
    style = resolver.city_limits_boundary()
    assert style.linestyle.color == hex_to_kml_color(config.city_limits_style.line_color)
    assert style.polystyle.fill == 1  # city limits are configured with fill=true


@pytest.mark.parametrize(
    "category", ["interstate", "us_highway", "county_road", "grade_separated_connector"]
)
def test_route_style_matches_config(config, category):
    resolver = StyleResolver(config)
    route_cfg = config.route_styles[category]
    style = resolver.route(category)
    assert style.linestyle.color == hex_to_kml_color(route_cfg.line_color)
    assert style.linestyle.width == route_cfg.line_width


def test_route_covers_every_configured_category(config):
    resolver = StyleResolver(config)
    for category in config.route_styles:
        assert resolver.route(category) is not None


def test_unknown_route_category_raises_keyerror(config):
    resolver = StyleResolver(config)
    with pytest.raises(KeyError):
        resolver.route("not_a_real_category")


def test_resolver_returns_stable_instances_for_reuse(config):
    """Placemarks sharing one Style instance is what makes simplekml emit a
    single shared <Style> with styleUrl references instead of inlining a
    copy per placemark -- the resolver must not rebuild styles per call.
    """
    resolver = StyleResolver(config)
    assert resolver.district_boundary() is resolver.district_boundary()
    assert resolver.county_boundary() is resolver.county_boundary()
    assert resolver.city_limits_boundary() is resolver.city_limits_boundary()
    assert resolver.route("interstate") is resolver.route("interstate")
