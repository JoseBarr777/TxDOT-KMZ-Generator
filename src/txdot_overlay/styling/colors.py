"""Converts standard #RRGGBB web colors to KML's aabbggrr color format.

KML colors are `aabbggrr` hex strings: alpha, then blue/green/red -- the
reverse byte order from CSS/#RRGGBB, with alpha first instead of last.
"""

from __future__ import annotations

import re

_HEX_COLOR_RE = re.compile(r"^#?([0-9A-Fa-f]{6})$")


def _opacity_to_alpha_byte(opacity: float) -> int:
    if not 0.0 <= opacity <= 1.0:
        raise ValueError(f"opacity must be between 0.0 and 1.0, got {opacity}")
    return round(opacity * 255)


def hex_to_kml_color(hex_color: str, opacity: float = 1.0) -> str:
    """Convert `#RRGGBB` (or `RRGGBB`) plus an opacity (0.0-1.0) to `aabbggrr`.

    Example: hex_to_kml_color("#FF0000", 1.0) == "ff0000ff"  # opaque red
    """
    match = _HEX_COLOR_RE.match(hex_color.strip())
    if not match:
        raise ValueError(f"Invalid #RRGGBB color: {hex_color!r}")
    rr, gg, bb = match.group(1)[0:2], match.group(1)[2:4], match.group(1)[4:6]
    alpha = _opacity_to_alpha_byte(opacity)
    return f"{alpha:02x}{bb}{gg}{rr}".lower()


def kml_color_to_hex(kml_color: str) -> tuple[str, float]:
    """Inverse of hex_to_kml_color: `aabbggrr` -> (`#RRGGBB`, opacity)."""
    kml_color = kml_color.strip().lower()
    if len(kml_color) != 8 or not all(c in "0123456789abcdef" for c in kml_color):
        raise ValueError(f"Invalid KML aabbggrr color: {kml_color!r}")
    aa, bb, gg, rr = kml_color[0:2], kml_color[2:4], kml_color[4:6], kml_color[6:8]
    opacity = int(aa, 16) / 255
    return f"#{rr}{gg}{bb}".upper(), opacity
