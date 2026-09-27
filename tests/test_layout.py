"""Locks down the artifact filesystem contract owned by `export/layout.py`.

Focus is project-level invariants (logical TxDOT name -> safe, stable,
relative artifact path), not a general test suite for `pathlib.Path` or for
`utils.slugify` in isolation -- these tests exist to prove layout.py uses the
project's existing slug contract correctly and produces paths that can never
escape the release tree, not to re-derive slugify's own semantics.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest

from txdot_overlay.export.layout import (
    ADMIN_BOUNDARIES_KMZ,
    CITY_BOUNDARIES_KMZ,
    COUNTY_BOUNDARIES_KMZ,
    DISTRICT_BOUNDARIES_KMZ,
    STATEWIDE_OFFLINE_ZIP,
    county_kmz_relative_path,
    district_kml_relative_path,
    district_offline_zip_relative_path,
    offline_county_archive_path,
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


# --- 8. Offline package release artifact paths (ZIP files themselves) -------
#
# Same path domain as county_kmz_relative_path/district_kml_relative_path
# above: slug-based, machine-stable, under the release tree. These are new
# top-level artifact paths (offline/...), not archive member names.


def test_district_offline_zip_relative_path_shape():
    assert district_offline_zip_relative_path("Tyler") == Path("offline/tyler.zip")


@pytest.mark.parametrize(
    ("district_name", "expected"),
    [
        ("Tyler", "offline/tyler.zip"),
        ("Fort Worth", "offline/fort_worth.zip"),
        ("Corpus Christi", "offline/corpus_christi.zip"),
    ],
    ids=["single-word", "multi-word", "multi-word-2"],
)
def test_district_offline_zip_relative_path_multi_word_names(district_name, expected):
    assert district_offline_zip_relative_path(district_name) == Path(expected)


def test_district_offline_zip_relative_path_is_relative():
    assert not district_offline_zip_relative_path("Tyler").is_absolute()


def test_statewide_offline_zip_constant():
    assert STATEWIDE_OFFLINE_ZIP == Path("offline/texas_statewide.zip")
    assert not STATEWIDE_OFFLINE_ZIP.is_absolute()


def test_offline_zip_paths_are_deterministic():
    assert district_offline_zip_relative_path("Tyler") == district_offline_zip_relative_path(
        "Tyler"
    )


def test_offline_zip_hostile_district_name_cannot_escape_the_offline_tree():
    """Same slug-based safety guarantee as district_kml_relative_path/
    county_kmz_relative_path -- district_offline_zip_relative_path routes
    through the same slugify() call, so the traversal-safety reasoning in
    section 3 above applies identically here.
    """
    path = district_offline_zip_relative_path("../../etc/passwd")

    assert not path.is_absolute()
    assert ".." not in path.parts
    resolved = (Path("/release-root") / path).resolve()
    assert resolved.is_relative_to(Path("/release-root"))


# --- 9. Existing release paths are unchanged by this step --------------------
#
# The offline additions above are new top-level definitions; they must not
# have altered the pre-existing artifact contract that manifest.py/
# kml_builder.py/build_distribution.py/package_poc.py already depend on.


def test_existing_release_paths_are_unchanged():
    assert district_kml_relative_path("Tyler") == Path("districts/tyler.kml")
    assert county_kmz_relative_path("Tyler", "Smith") == Path("districts/tyler/smith.kmz")


# --- 10. Offline archive member paths (human-readable, inside the ZIP) ------
#
# A deliberately different path domain from section 8/9 above: these are
# never written to the release filesystem, only used as ZIP member names,
# and are human-readable display names rather than slugs.


def test_offline_county_archive_path_shape():
    assert offline_county_archive_path("Tyler", "Smith") == PurePosixPath(
        "Tyler District/Smith County.kmz"
    )


def test_offline_county_archive_path_is_posix_path():
    # Guaranteed independent of the host OS building the archive:
    # PurePosixPath always uses "/" and never interprets "\\" as a
    # separator, unlike plain pathlib.Path on Windows.
    path = offline_county_archive_path("Tyler", "Smith")
    assert isinstance(path, PurePosixPath)
    assert str(path) == "Tyler District/Smith County.kmz"


@pytest.mark.parametrize(
    ("district_name", "county_name", "expected"),
    [
        ("Tyler", "Smith", "Tyler District/Smith County.kmz"),
        ("Fort Worth", "Wise", "Fort Worth District/Wise County.kmz"),
        ("Corpus Christi", "Nueces", "Corpus Christi District/Nueces County.kmz"),
    ],
    ids=["single-word", "district-multi-word", "district-and-county-multi-word"],
)
def test_offline_county_archive_path_multi_word_names(district_name, county_name, expected):
    assert offline_county_archive_path(district_name, county_name) == PurePosixPath(expected)


def test_offline_county_archive_path_does_not_double_up_suffixes():
    """The project's own DIST_NM/CNTY_NM display-name convention (see
    export/manifest.py's display_name=f"{name} District"/f"{name} County",
    and kml_builder.py's equivalent KML document names) already assumes
    source names never carry the "District"/"County" word themselves. This
    documents that this helper relies on the same, already-established
    assumption rather than adding new suffix-detection logic.
    """
    path = offline_county_archive_path("Tyler", "Smith")
    assert "District District" not in str(path)
    assert "County County" not in str(path)


def test_offline_county_archive_path_is_relative():
    assert not offline_county_archive_path("Tyler", "Smith").is_absolute()


def test_offline_county_archive_path_is_deterministic():
    assert offline_county_archive_path("Tyler", "Smith") == offline_county_archive_path(
        "Tyler", "Smith"
    )


def test_same_helper_naturally_groups_counties_by_district_for_statewide_use():
    """No District-vs-Statewide special case exists: the same helper, called
    across every county regardless of source district, naturally produces
    the statewide package's District-grouped structure with no additional
    wrapper directory.
    """
    tyler_smith = offline_county_archive_path("Tyler", "Smith")
    tyler_anderson = offline_county_archive_path("Tyler", "Anderson")
    abilene_borden = offline_county_archive_path("Abilene", "Borden")

    assert tyler_smith.parent == tyler_anderson.parent == PurePosixPath("Tyler District")
    assert abilene_borden.parent == PurePosixPath("Abilene District")
    # No shared "Texas TxDOT Overlay" (or any other) wrapper directory above
    # the per-district folders.
    assert len(tyler_smith.parts) == 2
    assert len(abilene_borden.parts) == 2
