"""Owns the artifact filesystem contract: where every generated KML/KMZ artifact lives,
relative to the configured output directory.

Extracted from `export/kml_builder.py`, which previously mixed these path/layout
definitions with rendering logic. This module has no rendering responsibility --
it is imported by both the builders that write artifacts to these paths
(`kml_builder.py`, `commands/build_distribution.py`) and the code that reads
artifacts back from them (`export/manifest.py`, `commands/package_poc.py`),
so both sides agree on the same paths by construction rather than by
convention.
"""

from __future__ import annotations

from pathlib import Path

from txdot_overlay.utils import slugify


def county_kmz_relative_path(district_name: str, county_name: str) -> Path:
    """The path (relative to the output directory) a county's detail KMZ lives at."""
    return Path("districts") / slugify(district_name) / f"{slugify(county_name)}.kmz"


def district_kml_relative_path(district_name: str) -> Path:
    """The path (relative to the output directory) a district's NetworkLink KML lives at.

    Deliberately a sibling of the district's own county directory
    (districts/tyler.kml next to districts/tyler/), so its NetworkLink hrefs
    are short relative paths ("tyler/smith.kmz") that keep resolving when the
    whole output tree is moved, zipped, or served from an object store.
    """
    return Path("districts") / f"{slugify(district_name)}.kml"


# Administrative-only artifacts ship as KMZ: these are statewide polygon
# collections whose plain-KML form is megabytes of coordinate text and
# compresses ~3x (measured: the combined document is ~15MB of KML in a
# ~4.9MB KMZ). Paths live here, next to the other artifact path
# conventions, so both the builder command and the manifest agree on them.
DISTRICT_BOUNDARIES_KMZ = Path("boundaries") / "district_boundaries.kmz"
COUNTY_BOUNDARIES_KMZ = Path("boundaries") / "county_boundaries.kmz"
CITY_BOUNDARIES_KMZ = Path("boundaries") / "city_boundaries.kmz"
ADMIN_BOUNDARIES_KMZ = Path("boundaries") / "administrative_boundaries.kmz"
