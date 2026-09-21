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


@pytest.mark.parametrize(
    "boundary_style_attr, accessor_name",
    [
        ("district_style", "district_boundary"),
        ("county_style", "county_boundary"),
        ("city_limits_style", "city_limits_boundary"),
    ],
)
def test_admin_boundaries_have_restrained_translucent_fill(
    config, boundary_style_attr, accessor_name
):
    """Districts, counties, and cities should all render with a translucent
    fill (not outline-only, not opaque) so the polygons read spatially
    without hiding aerial imagery or roads underneath them.
    """
    style_config = getattr(config, boundary_style_attr)
    resolver = StyleResolver(config)
    style = getattr(resolver, accessor_name)()

    assert style_config.fill is True
    assert style.polystyle.fill == 1
    assert 0.0 < style_config.fill_opacity <= 0.15
    assert style.polystyle.color == hex_to_kml_color(
        style_config.fill_color, style_config.fill_opacity
    )


def test_boundary_fill_grows_more_local_to_more_specific(config):
    """District (largest, most overlap) should be the faintest fill and city
    limits (smallest, most local) the least faint, so nested polygons stay
    distinguishable from one another instead of compounding into one wash.
    """
    assert (
        config.district_style.fill_opacity
        < config.county_style.fill_opacity
        < config.city_limits_style.fill_opacity
    )


def test_state_highway_is_not_yellow_or_gold(config):
    """The previous state_highway color (#FFD700, gold) was too close to
    county_road's goldenrod (#B8860B) for a major on-system route and was
    called out as not preferred; it must have moved away from that hue.
    """
    assert config.route_styles["state_highway"].line_color.upper() != "#FFD700"


def test_major_route_widths_unchanged_and_descend_by_class(config):
    """Interstate/US Highway/State Highway/FM-RM already formed a sensible
    hierarchy and weren't flagged as too thin -- only their ordering (major
    routes read heavier than minor ones) needs to hold.
    """
    widths = {cat: cfg.line_width for cat, cfg in config.route_styles.items()}
    assert widths["interstate"] >= widths["us_highway"] >= widths["state_highway"]
    assert widths["state_highway"] > widths["fm_rm"]
    assert widths["fm_rm"] == widths["loop_spur_business"]


@pytest.mark.parametrize(
    "category",
    [
        "county_local_other",
        "county_road",
        "city_street",
        "regional_mobility_authority",
        "other_unclassified",
        "grade_separated_connector",
    ],
)
def test_no_route_category_is_effectively_invisible(config, category):
    """None of the lower-tier/off-system categories should render as a
    near-hairline in Google Earth Pro -- every TxDOT-relevant category must
    stay visible, even the deliberately-subordinate ones.
    """
    assert config.route_styles[category].line_width >= 0.75


def test_lower_tier_routes_stay_thinner_than_named_state_routes(config):
    """Widening the thin categories must not erase the major/minor
    distinction: they should still read lighter than FM/RM and above.
    """
    widths = {cat: cfg.line_width for cat, cfg in config.route_styles.items()}
    for category in (
        "county_local_other",
        "county_road",
        "city_street",
        "regional_mobility_authority",
        "other_unclassified",
        "grade_separated_connector",
    ):
        assert widths[category] < widths["fm_rm"]
