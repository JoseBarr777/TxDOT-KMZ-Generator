"""Packages already-built county KMZs into District/Statewide offline ZIPs.

This is a transport/container layer, not a GIS transformation layer: it
never queries ArcGIS, never rebuilds county KML/KMZ content, and never
touches roadway/boundary geometry. It only reads bytes that
`commands/build_county.py` already wrote to disk, via the same
`export.layout.county_kmz_relative_path` every other reader of those files
already uses, and re-packages those exact bytes as opaque ZIP members
through the shared deterministic writer (`export.zip_utils`).

District/county *membership* here means the same thing it means everywhere
else in this project: `district_name`/`county_name` (DIST_NM/CNTY_NM) are
human-readable display identity, used only for the archive's folder/file
names -- never `district_number` (DIST_NBR) or a slug. Which counties
belong to which district comes from the same `districts`/`counties`
GeoDataFrames and the same district-then-county lookup pattern
`commands/build_distribution.py` already uses, not from scanning directory
names or KMZ filenames.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import geopandas as gpd

from txdot_overlay.config import Config
from txdot_overlay.export.layout import (
    STATEWIDE_OFFLINE_ZIP,
    county_kmz_relative_path,
    district_offline_zip_relative_path,
    offline_county_archive_path,
)
from txdot_overlay.export.zip_utils import write_deterministic_zip
from txdot_overlay.logging_setup import get_logger

logger = get_logger(__name__)

# A ZIP member's own file-permission bits, independent of whatever
# permissions the source county KMZ happens to have on disk right now (a
# packaged file being handed to someone else warrants its own fixed,
# sensible default -- not an accidental copy of the build machine's umask).
# Regular file, owner read/write, everyone else read-only.
_ARCHIVE_MEMBER_EXTERNAL_ATTR = 0o644 << 16


@dataclass
class DistrictPackageResult:
    district_name: str
    # None means skipped -- see missing_counties for why.
    path: Path | None
    missing_counties: list[str] = field(default_factory=list)

    @property
    def built(self) -> bool:
        return self.path is not None


@dataclass
class OfflinePackageResult:
    districts: list[DistrictPackageResult]
    # None means skipped -- see statewide_missing_counties for why.
    statewide_path: Path | None
    statewide_missing_counties: list[str] = field(default_factory=list)

    @property
    def statewide_built(self) -> bool:
        return self.statewide_path is not None

    @property
    def built_districts(self) -> list[DistrictPackageResult]:
        return [d for d in self.districts if d.built]

    @property
    def skipped_districts(self) -> list[DistrictPackageResult]:
        return [d for d in self.districts if not d.built]


def district_county_names(
    counties: gpd.GeoDataFrame, county_fields: dict[str, str], district_name: str
) -> list[str]:
    """The expected counties for one district, in the same stable alphabetical
    order manifest.py/build_distribution.py already use -- so package
    membership order matches the rest of the project's artifact ordering.

    Public (not prefixed `_`) because `export/offline_package_validate.py`
    needs the exact same authoritative membership computation this builder
    uses -- the validator must ask the same question the builder did, not a
    parallel/reimplemented one.
    """
    district_counties = counties[
        counties[county_fields["district_name"]] == district_name
    ].sort_values(county_fields["name"], kind="stable")
    return [str(name) for name in district_counties[county_fields["name"]]]


def _remove_if_present(path: Path) -> None:
    """Delete a stale package so an incomplete run can never leave behind a
    ZIP from an earlier, complete run at the same path -- a state that would
    look indistinguishable from a fresh, correct package to anything reading
    the release tree afterward.
    """
    if path.exists():
        path.unlink()
        logger.warning("Removed stale offline package (now incomplete): %s", path)


def _build_district_package(
    config: Config,
    district_name: str,
    county_names: list[str],
) -> tuple[DistrictPackageResult, list[tuple[str, bytes, int]]]:
    """Returns the district's result plus the (arcname, data, external_attr)
    entries it read, so a statewide build can reuse those already-read bytes
    instead of reading every county KMZ from disk a second time.
    """
    zip_path = config.output_dir / district_offline_zip_relative_path(district_name)

    entries: list[tuple[str, bytes, int]] = []
    missing: list[str] = []
    for county_name in county_names:
        source_path = config.output_dir / county_kmz_relative_path(district_name, county_name)
        if not source_path.exists():
            missing.append(county_name)
            continue
        arcname = offline_county_archive_path(district_name, county_name).as_posix()
        entries.append((arcname, source_path.read_bytes(), _ARCHIVE_MEMBER_EXTERNAL_ATTR))

    if missing:
        _remove_if_present(zip_path)
        logger.warning(
            "%s District offline package skipped: missing %d of %d county KMZ(s): %s",
            district_name,
            len(missing),
            len(county_names),
            ", ".join(missing),
        )
        result = DistrictPackageResult(
            district_name=district_name, path=None, missing_counties=missing
        )
        return result, []

    zip_path.parent.mkdir(parents=True, exist_ok=True)
    write_deterministic_zip(entries, zip_path, compress_type=zipfile.ZIP_STORED)
    logger.info(
        "%s District offline package: %d county KMZ(s) -> %s",
        district_name,
        len(entries),
        zip_path,
    )
    result = DistrictPackageResult(district_name=district_name, path=zip_path, missing_counties=[])
    return result, entries


def build_offline_packages(
    config: Config,
    districts: gpd.GeoDataFrame,
    counties: gpd.GeoDataFrame,
) -> OfflinePackageResult:
    """Package every district's already-built county KMZs into offline ZIPs,
    plus one statewide ZIP if every district is complete.

    A district's ZIP is built only if every county KMZ that district's
    source data says it should have is already present on disk; the
    statewide ZIP is built only if every district is. Neither ever contains
    a placeholder for a missing county, and an incomplete run never leaves a
    stale ZIP from an earlier, complete run sitting at that path (see
    `_remove_if_present`).

    Districts are the full authoritative list from `districts` (all 25 TxDOT
    districts), never inferred from what happens to already be on disk --
    the same "district that isn't built yet is incomplete, not absent"
    philosophy `build_distribution_artifacts` already uses for district
    KMLs.
    """
    district_fields = config.sources["districts"].fields
    county_fields = config.sources["counties"].fields

    district_names = sorted(districts[district_fields["name"]].dropna().unique())

    district_results: list[DistrictPackageResult] = []
    statewide_entries: list[tuple[str, bytes, int]] = []
    statewide_missing: list[str] = []

    for district_name in district_names:
        district_name = str(district_name)
        county_names = district_county_names(counties, county_fields, district_name)

        result, entries = _build_district_package(config, district_name, county_names)
        district_results.append(result)

        if result.built:
            statewide_entries.extend(entries)
        else:
            statewide_missing.extend(
                f"{district_name}/{county_name}" for county_name in result.missing_counties
            )

    statewide_zip_path = config.output_dir / STATEWIDE_OFFLINE_ZIP
    if statewide_missing:
        _remove_if_present(statewide_zip_path)
        logger.warning(
            "Statewide offline package skipped: %d county KMZ(s) missing across %d district(s)",
            len(statewide_missing),
            len([d for d in district_results if not d.built]),
        )
        statewide_path = None
    else:
        statewide_zip_path.parent.mkdir(parents=True, exist_ok=True)
        write_deterministic_zip(
            statewide_entries, statewide_zip_path, compress_type=zipfile.ZIP_STORED
        )
        logger.info(
            "Statewide offline package: %d county KMZ(s) across %d district(s) -> %s",
            len(statewide_entries),
            len(district_results),
            statewide_zip_path,
        )
        statewide_path = statewide_zip_path

    return OfflinePackageResult(
        districts=district_results,
        statewide_path=statewide_path,
        statewide_missing_counties=statewide_missing,
    )
