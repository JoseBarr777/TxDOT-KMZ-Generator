import pytest

from txdot_overlay.styling.colors import hex_to_kml_color, kml_color_to_hex


def test_opaque_primary_colors():
    assert hex_to_kml_color("#FF0000", 1.0) == "ff0000ff"  # red
    assert hex_to_kml_color("#00FF00", 1.0) == "ff00ff00"  # green
    assert hex_to_kml_color("#0000FF", 1.0) == "ffff0000"  # blue


def test_accepts_hash_or_bare_hex():
    assert hex_to_kml_color("#FFC000") == hex_to_kml_color("FFC000")


def test_opacity_controls_alpha_byte():
    assert hex_to_kml_color("#FFFFFF", 0.0) == "00ffffff"
    assert hex_to_kml_color("#FFFFFF", 0.5) == "80ffffff"
    assert hex_to_kml_color("#FFFFFF", 1.0) == "ffffffff"


def test_output_is_lowercase():
    assert hex_to_kml_color("#ABCDEF") == hex_to_kml_color("#ABCDEF").lower()


def test_invalid_hex_raises():
    with pytest.raises(ValueError):
        hex_to_kml_color("not-a-color")
    with pytest.raises(ValueError):
        hex_to_kml_color("#12345")  # too short


def test_invalid_opacity_raises():
    with pytest.raises(ValueError):
        hex_to_kml_color("#FFFFFF", 1.5)
    with pytest.raises(ValueError):
        hex_to_kml_color("#FFFFFF", -0.1)


def test_round_trip():
    hex_color, opacity = kml_color_to_hex(hex_to_kml_color("#123456", 0.75))
    assert hex_color == "#123456"
    assert opacity == pytest.approx(0.75, abs=1 / 255)


def test_kml_color_to_hex_invalid_length():
    with pytest.raises(ValueError):
        kml_color_to_hex("ff0000")
