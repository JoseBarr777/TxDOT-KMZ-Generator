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

from pathlib import Path, PurePosixPath

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


def district_offline_zip_relative_path(district_name: str) -> Path:
    """The path (relative to the output directory) a district's offline ZIP
    package lives at.

    A sibling of the existing `districts/` and `boundaries/` trees, not
    nested under either: this is a distribution-layer artifact (a ZIP
    wrapping already-built county KMZs), not another KML/KMZ artifact type,
    so it gets its own top-level `offline/` directory in the release tree.
    """
    return Path("offline") / f"{slugify(district_name)}.zip"


# The statewide offline ZIP has no per-district parameter, so it's a
# constant, matching the pattern the four boundary artifacts already use
# above -- one fixed, known-in-advance path, not a function.
STATEWIDE_OFFLINE_ZIP = Path("offline") / "texas_statewide.zip"


def offline_county_archive_path(district_name: str, county_name: str) -> PurePosixPath:
    """Where a county's KMZ appears *inside* a District or Statewide offline ZIP.

    Deliberately a different path domain from `county_kmz_relative_path`:
    that function answers "where does this county's KMZ live in the release
    tree" (a slug-based, machine-stable filesystem path); this function
    answers "what does a person see after extracting the ZIP" (a
    human-readable archive member name, built from the same display names
    already used everywhere else a county/district is shown to a person --
    see `export/manifest.py`'s `display_name=f"{county_name} County"` /
    `f"{district_name} District"` and `kml_builder.py`'s equivalent KML
    document names). Those names are already established, tested TxDOT
    display names that never themselves contain the word "District" or
    "County" -- confirmed by every existing caller of that convention -- so
    no suffix-detection logic is needed to avoid a doubled
    "Tyler District District" name.

    Always a `PurePosixPath`, never a plain `Path`: a ZIP archive's member
    names are forward-slash-separated by format regardless of the host OS
    (these archives are built on macOS/Linux and consumed primarily by
    Windows users), so this must not pick up `\\` from `pathlib.Path` on a
    Windows build machine.

    Not traversal-safe against a hostile name the way the slug-based release
    paths are: these are human-readable names, not slugs, so this
    deliberately does not sanitize through `slugify()`. Real TxDOT
    `DIST_NM`/`CNTY_NM` values are controlled source data and never contain
    path separators or "..", so this is an accepted, documented boundary,
    not an oversight.
    """
    return PurePosixPath(f"{district_name} District") / f"{county_name} County.kmz"
