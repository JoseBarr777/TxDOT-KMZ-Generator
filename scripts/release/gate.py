"""Release completeness gate for the staging workflow.

Answers: is the generated artifact set eligible to proceed through
release-staging.yml? Reads manifest.json and requires (see
docs/ARTIFACT_CONTRACT.md):

  - a supported manifest schema: a "MAJOR.MINOR" string with major 2 (any
    2.x minor is accepted; an unknown major is rejected before anything
    else is read, since its structure is not known)
  - a complete statewide release: validation.status == "complete", 25/25
    districts, 254/254 counties, no required artifact missing or invalid
  - explicit inventory cardinalities: exactly 25 district_zip, exactly 1
    statewide_zip, and exactly 1 each of master_kml and the four boundary
    KMZ types
  - county/district identity agreement: unique (district, district_number)
    per district_zip, every county_kmz's pair matching exactly one
    district_zip, and no district_zip without a county_kmz

The inventory counts are deliberately redundant with the manifest's own
completeness verdict: the producer marks all of these types required, so
a missing one normally surfaces as required_missing and a non-complete
status. But an artifact type the producer stopped registering at all would
appear in neither `artifacts` nor `skipped` and evade those counters, so
the gate counts them straight from `artifacts`. It counts entries only;
artifact contents are the validators' job.

Originally extracted from the inline heredoc in
.github/workflows/release-staging.yml ("Enforce release completeness
gate"). Standard library only, so it runs under the runner's bare python3
without `uv sync`.

Exit status: 0 when the gate passes, 1 when it fails or the manifest is
absent. A malformed manifest (bad JSON, missing keys) raises and exits 1
with a traceback, exactly as the inline version did.

Usage:
    python3 scripts/release/gate.py [--manifest data/output/manifest.json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter

DEFAULT_MANIFEST_PATH = "data/output/manifest.json"

EXPECTED_DISTRICTS = 25
EXPECTED_COUNTIES = 254
EXPECTED_DISTRICT_ZIPS = EXPECTED_DISTRICTS  # one bulk ZIP per district
EXPECTED_STATEWIDE_ZIPS = 1

DISTRICT_ZIP_TYPE = "district_zip"
STATEWIDE_ZIP_TYPE = "statewide_zip"
COUNTY_KMZ_TYPE = "county_kmz"

# Cap on individually listed orphan counties, so a wholesale mismatch (e.g. a
# manifest with no district ZIPs at all) does not bury the log.
MAX_ORPHAN_COUNTIES_REPORTED = 10

# Types a complete release carries exactly one of.
EXACTLY_ONE_TYPES = (
    "master_kml",
    "district_boundaries_kmz",
    "county_boundaries_kmz",
    "city_boundaries_kmz",
    "admin_boundaries_kmz",
)

SUPPORTED_SCHEMA_MAJOR = 2
_SCHEMA_VERSION_RE = re.compile(r"([0-9]+)\.([0-9]+)")


def schema_version_failure(manifest: dict) -> str | None:
    """Why ``manifest``'s schema_version is unsupported, or None if it is 2.x."""
    if "schema_version" not in manifest:
        return "manifest has no schema_version"
    version = manifest["schema_version"]
    match = _SCHEMA_VERSION_RE.fullmatch(version) if isinstance(version, str) else None
    if match is None:
        return f"schema_version {version!r} is not a 'MAJOR.MINOR' string"
    major = int(match.group(1))
    if major != SUPPORTED_SCHEMA_MAJOR:
        return (
            f"manifest schema major version {major} ({version!r}) is not supported; "
            f"this release tooling supports {SUPPORTED_SCHEMA_MAJOR}.x"
        )
    return None


def gate_failures(manifest: dict) -> list[str]:
    """Return the reasons ``manifest`` fails the release gate (empty = pass)."""
    version_problem = schema_version_failure(manifest)
    if version_problem is not None:
        # An unsupported schema's structure is unknown; judge nothing else.
        return [version_problem]

    v = manifest["validation"]
    status = v["status"]
    counties_included = v["counties_included"]
    counties_expected = v["counties_expected"]
    districts_included = v["districts_included"]
    districts_expected = v["districts_expected"]
    required_missing = v["required_missing"]
    required_invalid = v["required_invalid"]
    type_counts = Counter(artifact["type"] for artifact in manifest["artifacts"])
    district_zips = type_counts[DISTRICT_ZIP_TYPE]
    statewide_zips = type_counts[STATEWIDE_ZIP_TYPE]

    failures = []
    if status != "complete":
        failures.append(f"validation.status is '{status}', expected 'complete'")
    if districts_expected != EXPECTED_DISTRICTS or districts_included != EXPECTED_DISTRICTS:
        failures.append(f"districts {districts_included}/{districts_expected}, expected 25/25")
    if counties_expected != EXPECTED_COUNTIES or counties_included != EXPECTED_COUNTIES:
        failures.append(f"counties {counties_included}/{counties_expected}, expected 254/254")
    if required_missing != 0:
        failures.append(f"{required_missing} required artifact(s) missing")
    if required_invalid != 0:
        failures.append(f"{required_invalid} required artifact(s) invalid")
    if district_zips != EXPECTED_DISTRICT_ZIPS:
        failures.append(
            f"expected {EXPECTED_DISTRICT_ZIPS} {DISTRICT_ZIP_TYPE} artifacts, found {district_zips}"
        )
    if statewide_zips != EXPECTED_STATEWIDE_ZIPS:
        failures.append(
            f"expected {EXPECTED_STATEWIDE_ZIPS} {STATEWIDE_ZIP_TYPE} artifact, found {statewide_zips}"
        )
    for artifact_type in EXACTLY_ONE_TYPES:
        if type_counts[artifact_type] != 1:
            failures.append(
                f"expected 1 {artifact_type} artifact, found {type_counts[artifact_type]}"
            )
    failures += district_identity_failures(manifest["artifacts"])
    return failures


def _district_identity(artifact: dict) -> tuple:
    return (artifact.get("district"), artifact.get("district_number"))


def _format_identity(identity: tuple) -> str:
    return f"{identity[0]} / {identity[1]}"


def district_identity_failures(artifacts: list[dict]) -> list[str]:
    """Why county_kmz and district_zip disagree on district identity (empty = agree).

    Manifest data only: every district_zip has a unique (district,
    district_number) pair, every county_kmz's pair matches exactly one
    district_zip, and every district_zip is matched by at least one
    county_kmz. Actual ZIP membership is validate-offline-packages' job.
    """
    zip_counts = Counter(_district_identity(a) for a in artifacts if a["type"] == DISTRICT_ZIP_TYPE)
    counties = [a for a in artifacts if a["type"] == COUNTY_KMZ_TYPE]
    referenced = Counter(_district_identity(c) for c in counties)

    failures = [
        f"duplicate {DISTRICT_ZIP_TYPE} identity: {_format_identity(identity)}"
        for identity, count in zip_counts.items()
        if count > 1
    ]

    orphans = [
        f"county {c.get('county')} / district {_format_identity(_district_identity(c))} "
        f"has no matching {DISTRICT_ZIP_TYPE}"
        for c in counties
        if _district_identity(c) not in zip_counts
    ]
    failures += orphans[:MAX_ORPHAN_COUNTIES_REPORTED]
    if len(orphans) > MAX_ORPHAN_COUNTIES_REPORTED:
        failures.append(
            f"... and {len(orphans) - MAX_ORPHAN_COUNTIES_REPORTED} more county_kmz "
            f"with no matching {DISTRICT_ZIP_TYPE}"
        )

    failures += [
        f"{DISTRICT_ZIP_TYPE} {_format_identity(identity)} has no {COUNTY_KMZ_TYPE} members"
        for identity in zip_counts
        if identity not in referenced
    ]
    return failures


def print_summary(manifest: dict) -> None:
    v = manifest["validation"]
    artifact_count = len(manifest["artifacts"])
    type_counts = Counter(artifact["type"] for artifact in manifest["artifacts"])
    print("Manifest validation summary")
    print(f"  status:             {v['status']}")
    print(f"  counties:           {v['counties_included']}/{v['counties_expected']}")
    print(f"  districts:          {v['districts_included']}/{v['districts_expected']}")
    print(f"  required_missing:   {v['required_missing']}")
    print(f"  required_invalid:   {v['required_invalid']}")
    print(f"  district_zip:       {type_counts[DISTRICT_ZIP_TYPE]}/{EXPECTED_DISTRICT_ZIPS}")
    print(f"  statewide_zip:      {type_counts[STATEWIDE_ZIP_TYPE]}/{EXPECTED_STATEWIDE_ZIPS}")
    for artifact_type in EXACTLY_ONE_TYPES:
        print(f"  {artifact_type}: {type_counts[artifact_type]}/1")
    print(f"  artifact_count:     {artifact_count}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST_PATH)
    args = parser.parse_args(argv)

    try:
        with open(args.manifest, encoding="utf-8") as fh:
            manifest = json.load(fh)
    except FileNotFoundError:
        print(f"::error::{args.manifest} not found -- generate-manifest did not produce output")
        return 1

    # An unsupported schema is rejected before the summary, which assumes
    # the 2.x structure.
    version_problem = schema_version_failure(manifest)
    if version_problem is not None:
        print(f"::error::Release gate failed: {version_problem}")
        return 1

    # Evaluate before printing so a malformed manifest (missing key) raises
    # before any summary output, as the inline step did; the summary is
    # still printed ahead of the itemized failures.
    failures = gate_failures(manifest)
    print_summary(manifest)

    if failures:
        for reason in failures:
            print(f"::error::Release gate failed: {reason}")
        return 1

    print(
        "Release gate passed: complete statewide release "
        "(25/25 districts, 254/254 counties, 25 district ZIPs, 1 statewide ZIP, "
        "master KML, 4 boundary KMZs)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
