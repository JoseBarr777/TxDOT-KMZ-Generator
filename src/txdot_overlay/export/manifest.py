"""Builds the deterministic distribution manifest describing generated KML/KMZ artifacts.

The manifest is the stable contract future consumers (a Cloudflare R2 publisher, a
static KMZ download browser, release tooling) will read instead of walking the
output directory or parsing filenames themselves.

Manifest generation calls export.validate's pure validator functions
directly, rather than requiring the separate `validate-output` CLI command
to have been run first. `build-all` already doesn't chain into
`validate-output` -- they're independent commands -- so making manifest
generation *require* that ordering would be new, awkward coupling between
two CLI commands. Calling the same underlying pure validation functions
gets the "never advertise a broken artifact" guarantee without that
coupling: anything that fails validation, or is simply missing, is left out
of `artifacts` and recorded in `skipped` instead.

Completeness (`validation.status`) is a separate question from per-artifact
validity, because "this artifact is broken" and "this build only covered
one district" need different responses from a publisher:

  complete -- every REQUIRED artifact is present and valid. The only state
              that should be promoted to a current release.
  partial  -- everything present is valid, but required artifacts are
              absent. The normal state of a scoped/in-progress build.
  failed   -- a required artifact exists but is invalid, or master.kml (the
              root document the whole distribution hangs off) is missing or
              invalid. Something is actually broken.

REQUIRED for a complete statewide release: master.kml, one district KML per
TxDOT district, one county KMZ per Texas county, and all four
administrative-boundary artifacts. OPTIONAL: the single-file KMZ, which is
only produced by `build-all --single-file-kmz` and is explicitly not the
primary distribution experience.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd

from txdot_overlay import __version__
from txdot_overlay.config import Config
from txdot_overlay.export.kml_builder import (
    ADMIN_BOUNDARIES_KMZ,
    CITY_BOUNDARIES_KMZ,
    COUNTY_BOUNDARIES_KMZ,
    DISTRICT_BOUNDARIES_KMZ,
    county_kmz_relative_path,
    district_kml_relative_path,
)
from txdot_overlay.export.validate import (
    ValidationReport,
    validate_kml_document,
    validate_kmz,
    validate_master_kml,
)

# 2.0: added district_kml and the four administrative boundary types, and
# replaced validation.status's passed/failed pair with the three-state
# complete/partial/failed completeness model described above.
SCHEMA_VERSION = "2.0"
GENERATOR_NAME = "txdot_overlay"
STATE = "TX"

MASTER_KML_TYPE = "master_kml"
DISTRICT_KML_TYPE = "district_kml"
COUNTY_KMZ_TYPE = "county_kmz"
DISTRICT_BOUNDARIES_TYPE = "district_boundaries_kmz"
COUNTY_BOUNDARIES_TYPE = "county_boundaries_kmz"
CITY_BOUNDARIES_TYPE = "city_boundaries_kmz"
ADMIN_BOUNDARIES_TYPE = "admin_boundaries_kmz"
SINGLE_FILE_KMZ_TYPE = "single_file_kmz"

STATUS_COMPLETE = "complete"
STATUS_PARTIAL = "partial"
STATUS_FAILED = "failed"

MISSING_REASON = "missing"

# Emitted in this fixed order, mirroring the download model: full overlay,
# browse by district, browse by county, administrative boundaries, then the
# optional single-file build last.
_ADMIN_ARTIFACTS = (
    (DISTRICT_BOUNDARIES_TYPE, "TxDOT District Boundaries", DISTRICT_BOUNDARIES_KMZ),
    (COUNTY_BOUNDARIES_TYPE, "Texas County Boundaries", COUNTY_BOUNDARIES_KMZ),
    (CITY_BOUNDARIES_TYPE, "Texas City Boundaries", CITY_BOUNDARIES_KMZ),
    (ADMIN_BOUNDARIES_TYPE, "Texas Administrative Boundaries", ADMIN_BOUNDARIES_KMZ),
)

_CHECKSUM_CHUNK_SIZE = 65536


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_CHECKSUM_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class ManifestArtifact:
    type: str
    display_name: str
    path: str  # POSIX, relative to config.output_dir
    size_bytes: int
    sha256: str
    county: str | None = None
    county_fips: str | None = None
    district: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": self.type,
            "display_name": self.display_name,
            "path": self.path,
        }
        if self.county is not None:
            payload["county"] = self.county
            payload["county_fips"] = self.county_fips
        if self.district is not None:
            payload["district"] = self.district
        payload["size_bytes"] = self.size_bytes
        payload["sha256"] = self.sha256
        return payload


@dataclass
class SkippedArtifact:
    type: str
    path: str
    reason: str
    required: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "path": self.path,
            "reason": self.reason,
            "required": self.required,
        }


@dataclass
class Manifest:
    generated_at: str
    status: str
    artifacts: list[ManifestArtifact]
    skipped: list[SkippedArtifact]
    counties_expected: int
    districts_expected: int

    @property
    def complete(self) -> bool:
        return self.status == STATUS_COMPLETE

    def _count(self, artifact_type: str) -> int:
        return sum(1 for a in self.artifacts if a.type == artifact_type)

    def to_dict(self) -> dict[str, Any]:
        required_skips = [s for s in self.skipped if s.required]
        return {
            "schema_version": SCHEMA_VERSION,
            "generator": GENERATOR_NAME,
            "generator_version": __version__,
            "generated_at": self.generated_at,
            "state": STATE,
            "validation": {
                "status": self.status,
                "counties_included": self._count(COUNTY_KMZ_TYPE),
                "counties_expected": self.counties_expected,
                "districts_included": self._count(DISTRICT_KML_TYPE),
                "districts_expected": self.districts_expected,
                "required_missing": sum(1 for s in required_skips if s.reason == MISSING_REASON),
                "required_invalid": sum(1 for s in required_skips if s.reason != MISSING_REASON),
            },
            "artifacts": [a.to_dict() for a in self.artifacts],
            "skipped": [s.to_dict() for s in self.skipped],
        }


def _artifact_from_file(
    artifact_type: str,
    display_name: str,
    path: Path,
    output_dir: Path,
    **extra: str,
) -> ManifestArtifact:
    return ManifestArtifact(
        type=artifact_type,
        display_name=display_name,
        path=path.relative_to(output_dir).as_posix(),
        size_bytes=path.stat().st_size,
        sha256=sha256_of(path),
        **extra,
    )


class _Collector:
    """Accumulates artifacts/skips so each artifact follows the same rule.

    Present and valid -> advertised. Missing or invalid -> recorded in
    `skipped` with a reason and whether its absence blocks a release.
    """

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.artifacts: list[ManifestArtifact] = []
        self.skipped: list[SkippedArtifact] = []

    def add(
        self,
        *,
        artifact_type: str,
        display_name: str,
        relative_path: Path,
        validator: Callable[[Path], ValidationReport],
        required: bool,
        **extra: str,
    ) -> None:
        path = self.output_dir / relative_path
        posix_path = relative_path.as_posix()

        if not path.exists():
            self.skipped.append(
                SkippedArtifact(
                    type=artifact_type,
                    path=posix_path,
                    reason=MISSING_REASON,
                    required=required,
                )
            )
            return

        report = validator(path)
        if not report.ok:
            self.skipped.append(
                SkippedArtifact(
                    type=artifact_type,
                    path=posix_path,
                    reason="; ".join(report.errors),
                    required=required,
                )
            )
            return

        self.artifacts.append(
            _artifact_from_file(artifact_type, display_name, path, self.output_dir, **extra)
        )


def _resolve_status(collector: _Collector) -> str:
    required_skips = [s for s in collector.skipped if s.required]
    master_ok = any(a.type == MASTER_KML_TYPE for a in collector.artifacts)
    invalid = [s for s in required_skips if s.reason != MISSING_REASON]

    if invalid or not master_ok:
        return STATUS_FAILED
    if required_skips:
        return STATUS_PARTIAL
    return STATUS_COMPLETE


def build_manifest(
    config: Config, districts: gpd.GeoDataFrame, counties: gpd.GeoDataFrame
) -> Manifest:
    """Assemble the manifest from whatever valid artifacts currently exist on disk.

    Ordering is fully determined by the source reference data, never by
    filesystem enumeration: districts alphabetically, counties
    alphabetically within their district (the same order
    build_district_details_folder uses for master.kml), and the
    administrative artifacts in a fixed declared order.
    """
    collector = _Collector(config.output_dir)
    district_fields = config.sources["districts"].fields
    county_fields = config.sources["counties"].fields

    collector.add(
        artifact_type=MASTER_KML_TYPE,
        display_name="TxDOT Reference Overlay — Master",
        relative_path=Path(config.master_kml_name),
        validator=lambda path: validate_master_kml(path, config),
        required=True,
    )

    district_names = sorted(districts[district_fields["name"]].dropna().unique())
    for district_name in district_names:
        collector.add(
            artifact_type=DISTRICT_KML_TYPE,
            display_name=f"{district_name} District",
            relative_path=district_kml_relative_path(str(district_name)),
            validator=validate_kml_document,
            required=True,
            district=str(district_name),
        )

    for district_name in sorted(counties[county_fields["district_name"]].dropna().unique()):
        district_counties = counties[
            counties[county_fields["district_name"]] == district_name
        ].sort_values(county_fields["name"], kind="stable")
        for _, county_row in district_counties.iterrows():
            county_name = county_row[county_fields["name"]]
            collector.add(
                artifact_type=COUNTY_KMZ_TYPE,
                display_name=f"{county_name} County",
                relative_path=county_kmz_relative_path(str(district_name), str(county_name)),
                validator=validate_kmz,
                required=True,
                county=str(county_name),
                county_fips=str(county_row[county_fields["fips"]]),
                district=str(district_name),
            )

    for artifact_type, display_name, relative_path in _ADMIN_ARTIFACTS:
        collector.add(
            artifact_type=artifact_type,
            display_name=display_name,
            relative_path=relative_path,
            validator=validate_kmz,
            required=True,
        )

    # Optional: only produced by `build-all --single-file-kmz`, so its
    # absence is silent rather than a skip entry a publisher must triage.
    single_file_path = config.output_dir / config.single_file_kmz_name
    if single_file_path.exists():
        collector.add(
            artifact_type=SINGLE_FILE_KMZ_TYPE,
            display_name="TxDOT Reference Overlay — Single-File",
            relative_path=Path(config.single_file_kmz_name),
            validator=validate_kmz,
            required=False,
        )

    return Manifest(
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        status=_resolve_status(collector),
        artifacts=collector.artifacts,
        skipped=collector.skipped,
        counties_expected=len(counties),
        districts_expected=len(district_names),
    )
