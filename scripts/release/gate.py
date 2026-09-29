"""Release completeness gate for the staging workflow.

Answers: is the generated artifact set eligible to proceed through
release-staging.yml? Reads manifest.json and requires a complete statewide
release (validation.status == "complete", 25/25 districts, 254/254
counties, no required artifact missing or invalid) whose artifact inventory
also carries the Phase 3 bulk-download contract: exactly 25 district_zip
artifacts (one per district) and exactly 1 statewide_zip.

The ZIP counts are deliberately redundant with the manifest's own
completeness verdict: manifest generation already marks both ZIP types
required, so a missing ZIP normally surfaces as required_missing and a
non-complete status. Counting them here, straight from `artifacts`, is an
independent check that the inventory actually satisfies the release
contract even if the validation summary and the inventory ever disagree.
It counts entries only; ZIP contents are validate-offline-packages' job.

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
import sys
from collections import Counter

DEFAULT_MANIFEST_PATH = "data/output/manifest.json"

EXPECTED_DISTRICTS = 25
EXPECTED_COUNTIES = 254
EXPECTED_DISTRICT_ZIPS = EXPECTED_DISTRICTS  # one bulk ZIP per district
EXPECTED_STATEWIDE_ZIPS = 1

DISTRICT_ZIP_TYPE = "district_zip"
STATEWIDE_ZIP_TYPE = "statewide_zip"


def gate_failures(manifest: dict) -> list[str]:
    """Return the reasons ``manifest`` fails the release gate (empty = pass)."""
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
        "(25/25 districts, 254/254 counties, 25 district ZIPs, 1 statewide ZIP)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
