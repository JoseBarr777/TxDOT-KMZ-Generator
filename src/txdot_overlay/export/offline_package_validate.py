"""Independently verifies District/Statewide offline ZIP packages already on
disk -- never builds or repairs one. See `export/offline_package.py` for the
builder; this module answers a different question:

    builder:    "can we create the packages correctly?"
    validator:  "are the packages currently on disk complete, structurally
                 correct, and composed of the exact canonical county KMZs
                 currently on disk?"

The byte-identity authority is deliberately the standalone county KMZ file
on disk (`districts/<district>/<county>.kmz`), never `manifest.json` -- the
manifest will eventually compute *its* hashes from these same files, so the
county KMZ itself is the primal source of truth, and this validator must not
depend on a document derived from it. This mirrors `export/validate.py`'s
existing KML/KMZ checks, which likewise validate files directly rather than
trusting a prior tool's report about them.

Reuses `export.validate.ValidationReport` (errors/warnings + `.ok`) as the
per-package result container -- the project's one existing convention for
"is this artifact valid", not a new parallel error model -- and
`export.offline_package.district_county_names` for expected membership, so
the validator asks the builder's exact question about what a district should
contain, not a re-derived one.
"""

from __future__ import annotations

import hashlib
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
from txdot_overlay.export.offline_package import district_county_names
from txdot_overlay.export.validate import ValidationReport

_CHECKSUM_CHUNK_SIZE = 65536


@dataclass
class PackageValidationResult:
    label: str
    path: Path
    report: ValidationReport = field(default_factory=ValidationReport)

    @property
    def ok(self) -> bool:
        return self.report.ok


@dataclass
class OfflinePackageValidationResult:
    districts: list[PackageValidationResult]
    statewide: PackageValidationResult

    @property
    def ok(self) -> bool:
        return all(d.ok for d in self.districts) and self.statewide.ok


def _sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_CHECKSUM_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_of_zip_member(zf: zipfile.ZipFile, info: zipfile.ZipInfo) -> str:
    digest = hashlib.sha256()
    with zf.open(info) as member:
        for chunk in iter(lambda: member.read(_CHECKSUM_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _expected_members(
    district_name: str, county_names: list[str], *, output_dir: Path
) -> dict[str, Path]:
    """arcname -> the standalone canonical county KMZ path it must match."""
    return {
        offline_county_archive_path(district_name, county_name).as_posix(): (
            output_dir / county_kmz_relative_path(district_name, county_name)
        )
        for county_name in county_names
    }


def _validate_package(
    label: str, zip_path: Path, expected_members: dict[str, Path]
) -> PackageValidationResult:
    report = ValidationReport()

    # Checked independent of whether the ZIP exists or is valid: a missing
    # canonical source is a failure regardless of what the package happens
    # to contain -- the package's own embedded copy is never treated as an
    # acceptable substitute for its source.
    for arcname, source_path in sorted(expected_members.items()):
        if not source_path.exists():
            report.add_error(f"{label}: canonical source county KMZ missing: {source_path}")

    if not zip_path.exists():
        report.add_error(f"{label}: offline package not found: {zip_path}")
        return PackageValidationResult(label=label, path=zip_path, report=report)

    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        report.add_error(f"{label}: not a valid ZIP archive: {zip_path}: {exc}")
        return PackageValidationResult(label=label, path=zip_path, report=report)

    with zf:
        infos = zf.infolist()

        directory_entries = [info.filename for info in infos if info.is_dir()]
        for name in sorted(directory_entries):
            report.add_error(f"{label}: unexpected explicit directory entry: {name}")

        file_names = [info.filename for info in infos if not info.is_dir()]
        seen: set[str] = set()
        duplicates: set[str] = set()
        for name in file_names:
            if name in seen:
                duplicates.add(name)
            seen.add(name)
        for name in sorted(duplicates):
            report.add_error(f"{label}: duplicate archive member: {name}")

        actual_names = set(file_names)
        expected_names = set(expected_members)

        for name in sorted(expected_names - actual_names):
            report.add_error(f"{label}: missing archive member: {name}")
        for name in sorted(actual_names - expected_names):
            report.add_error(f"{label}: unexpected archive member: {name}")

        for info in infos:
            name = info.filename
            if info.is_dir() or name not in expected_members:
                continue

            if info.compress_type != zipfile.ZIP_STORED:
                report.add_error(
                    f"{label}: {name}: wrong compression method "
                    f"(expected ZIP_STORED, got {info.compress_type})"
                )

            source_path = expected_members[name]
            if not source_path.exists():
                # Already reported above; hashing against a nonexistent
                # source would only duplicate that finding.
                continue

            expected_hash = _sha256_of_file(source_path)
            actual_hash = _sha256_of_zip_member(zf, info)
            if actual_hash != expected_hash:
                report.add_error(
                    f"{label}: {name}: embedded KMZ does not match source {source_path} "
                    f"(sha256 {actual_hash} != {expected_hash})"
                )

    return PackageValidationResult(label=label, path=zip_path, report=report)


def validate_district_package(
    config: Config, counties: gpd.GeoDataFrame, district_name: str
) -> PackageValidationResult:
    county_fields = config.sources["counties"].fields
    county_names = district_county_names(counties, county_fields, district_name)
    expected = _expected_members(district_name, county_names, output_dir=config.output_dir)
    zip_path = config.output_dir / district_offline_zip_relative_path(district_name)
    return _validate_package(f"{district_name} District", zip_path, expected)


def validate_statewide_package(
    config: Config, districts: gpd.GeoDataFrame, counties: gpd.GeoDataFrame
) -> PackageValidationResult:
    district_fields = config.sources["districts"].fields
    county_fields = config.sources["counties"].fields
    district_names = sorted(districts[district_fields["name"]].dropna().unique())

    expected: dict[str, Path] = {}
    for district_name in district_names:
        district_name = str(district_name)
        county_names = district_county_names(counties, county_fields, district_name)
        expected.update(
            _expected_members(district_name, county_names, output_dir=config.output_dir)
        )

    zip_path = config.output_dir / STATEWIDE_OFFLINE_ZIP
    return _validate_package("Statewide", zip_path, expected)


def validate_offline_packages(
    config: Config, districts: gpd.GeoDataFrame, counties: gpd.GeoDataFrame
) -> OfflinePackageValidationResult:
    """Validate every district's offline package plus the statewide package,
    against the same authoritative district/county source metadata Step 6's
    builder uses -- never against a prior manifest or the packages' own
    contents.
    """
    district_fields = config.sources["districts"].fields
    district_names = sorted(districts[district_fields["name"]].dropna().unique())

    district_results = [
        validate_district_package(config, counties, str(name)) for name in district_names
    ]
    statewide_result = validate_statewide_package(config, districts, counties)

    return OfflinePackageValidationResult(districts=district_results, statewide=statewide_result)
