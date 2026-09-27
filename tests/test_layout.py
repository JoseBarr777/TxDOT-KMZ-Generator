"""Locks down the artifact filesystem contract owned by `export/layout.py`.

Focus is project-level invariants (logical TxDOT name -> safe, stable,
relative artifact path), not a general test suite for `pathlib.Path` or for
`utils.slugify` in isolation -- these tests exist to prove layout.py uses the
project's existing slug contract correctly and produces paths that can never
escape the release tree, not to re-derive slugify's own semantics.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from txdot_overlay.export.layout import (
    ADMIN_BOUNDARIES_KMZ,
    CITY_BOUNDARIES_KMZ,
    COUNTY_BOUNDARIES_KMZ,
    DISTRICT_BOUNDARIES_KMZ,
    county_kmz_relative_path,
    district_kml_relative_path,
)

# --- 1. Expected path shapes ------------------------------------------------


def test_district_kml_relative_path_shape():
    assert district_kml_relative_path("Tyler") == Path("districts/tyler.kml")


def test_county_kmz_relative_path_shape():
    assert county_kmz_relative_path("Tyler", "Smith") == Path("districts/tyler/smith.kmz")


@pytest.mark.parametrize(
    ("district_name", "county_name", "expected"),
    [
        ("Tyler", "Smith", "districts/tyler/smith.kmz"),
        ("Fort Worth", "Wise", "districts/fort_worth/wise.kmz"),
        ("Corpus Christi", "Nueces", "districts/corpus_christi/nueces.kmz"),
    ],
    ids=["single-word", "district-multi-word", "district-and-county-multi-word"],
)
def test_county_kmz_relative_path_multi_word_names(district_name, county_name, expected):
    assert county_kmz_relative_path(district_name, county_name) == Path(expected)


# --- 2. Relative-path invariant ----------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        district_kml_relative_path("Tyler"),
        county_kmz_relative_path("Tyler", "Smith"),
        DISTRICT_BOUNDARIES_KMZ,
        COUNTY_BOUNDARIES_KMZ,
        CITY_BOUNDARIES_KMZ,
        ADMIN_BOUNDARIES_KMZ,
    ],
    ids=[
        "district_kml",
        "county_kmz",
        "district_boundaries",
        "county_boundaries",
        "city_boundaries",
        "admin_boundaries",
    ],
)
def test_artifact_paths_are_relative(path):
    assert not path.is_absolute()


# --- 3. Parent-directory / traversal safety ----------------------------------
#
# slugify() (src/txdot_overlay/utils.py) lowercases, then collapses every run
# of characters outside [a-z0-9] -- which includes ".", "/", "\\", and ":" --
# into a single "_", then strips leading/trailing "_". A "." or "/" character
# can therefore never survive into a path segment produced by layout.py: a
# traversal-shaped input degrades to an ordinary slug instead of escaping
# upward or producing an absolute path. Verified here rather than assumed.


@pytest.mark.parametrize(
    ("district_name", "county_name"),
    [
        ("../../etc", "passwd"),
        ("Tyler", "../../../etc/passwd"),
        ("/etc/passwd", "Smith"),
        ("..", ".."),
        ("C:\\Windows", "System32"),
    ],
    ids=[
        "traversal-in-district",
        "traversal-in-county",
        "leading-slash",
        "dot-dot-only",
        "windows-drive-and-backslash",
    ],
)
def test_hostile_names_cannot_escape_the_districts_tree(district_name, county_name):
    path = county_kmz_relative_path(district_name, county_name)

    assert not path.is_absolute()
    assert ".." not in path.parts
    # Demonstrates the actual invariant we care about: joining onto a real
    # release root and resolving it never leaves that root.
    resolved = (Path("/release-root") / path).resolve()
    assert resolved.is_relative_to(Path("/release-root"))


def test_hostile_district_name_cannot_escape_district_kml_tree():
    path = district_kml_relative_path("../../etc/passwd")

    assert not path.is_absolute()
    assert ".." not in path.parts
    resolved = (Path("/release-root") / path).resolve()
    assert resolved.is_relative_to(Path("/release-root"))


# --- 4. Determinism -----------------------------------------------------------


def test_repeated_calls_are_deterministic():
    assert county_kmz_relative_path("Tyler", "Smith") == county_kmz_relative_path("Tyler", "Smith")
    assert district_kml_relative_path("Tyler") == district_kml_relative_path("Tyler")


# --- 5. Boundary artifact constants -------------------------------------------


def test_boundary_artifact_constants_retain_established_paths():
    assert DISTRICT_BOUNDARIES_KMZ == Path("boundaries/district_boundaries.kmz")
    assert COUNTY_BOUNDARIES_KMZ == Path("boundaries/county_boundaries.kmz")
    assert CITY_BOUNDARIES_KMZ == Path("boundaries/city_boundaries.kmz")
    assert ADMIN_BOUNDARIES_KMZ == Path("boundaries/administrative_boundaries.kmz")


# --- 6. Layout uses the project's actual slug contract ------------------------


@pytest.mark.parametrize(
    ("name", "expected_slug"),
    [
        ("Tyler", "tyler"),
        ("Fort Worth", "fort_worth"),
        ("St. Augustine", "st_augustine"),
        ("O'Brien", "o_brien"),
        ("  Leading Trailing  ", "leading_trailing"),
    ],
    ids=[
        "plain",
        "space",
        "punctuation-period",
        "punctuation-apostrophe",
        "surrounding-whitespace",
    ],
)
def test_layout_uses_the_projects_slug_contract(name, expected_slug):
    assert district_kml_relative_path(name) == Path(f"districts/{expected_slug}.kml")


# --- 7. Slug-collision behavior (not universal uniqueness) --------------------
#
# layout.py adds no collision detection of its own -- it is a thin, pure
# wrapper around slugify. Proving slug uniqueness across the real 25
# TxDOT districts / 254 Texas counties requires the actual dataset and
# belongs in a later package-level check against that live data, not here.
# What *is* a layout-level fact worth locking down is that layout.py does not
# silently paper over a collision slugify itself would produce -- two names
# differing only in characters slugify discards map to the same path.


def test_names_differing_only_in_discarded_punctuation_collide():
    assert district_kml_relative_path("St. Augustine") == district_kml_relative_path("St Augustine")
    assert district_kml_relative_path("ST-AUGUSTINE") == district_kml_relative_path("st augustine")
