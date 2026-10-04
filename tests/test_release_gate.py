"""Behavior of scripts/release/gate.py, the staging workflow's completeness gate.

The gate first requires a supported manifest schema (a "MAJOR.MINOR" string,
major 2), then checks the validation summary (status, 25/25 districts,
254/254 counties, zero required missing/invalid) and, independently, counts
artifact types in the inventory (exactly 25 district_zip, exactly 1
statewide_zip, exactly 1 each of master_kml and the four boundary KMZs),
and requires county_kmz and district_zip to agree on (district,
district_number) identity.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from release import gate

REPO_ROOT = Path(__file__).resolve().parents[1]


EXACTLY_ONE_TYPES = [
    "master_kml",
    "district_boundaries_kmz",
    "county_boundaries_kmz",
    "city_boundaries_kmz",
    "admin_boundaries_kmz",
]


def _manifest(
    *,
    schema_version="2.1",
    district_zips=25,
    statewide_zips=1,
    single_counts=None,
    **validation_overrides,
):
    validation = {
        "status": "complete",
        "counties_included": 254,
        "counties_expected": 254,
        "districts_included": 25,
        "districts_expected": 25,
        "required_missing": 0,
        "required_invalid": 0,
    }
    validation.update(validation_overrides)
    counts = {t: 1 for t in EXACTLY_ONE_TYPES}
    counts.update(single_counts or {})
    artifacts = [
        {"type": t, "path": f"{t}-{i}"} for t in EXACTLY_ONE_TYPES for i in range(counts[t])
    ]
    artifacts += [
        {
            "type": "district_zip",
            "path": f"offline/districts/d{i:02d}.zip",
            "district": f"D{i:02d}",
            "district_number": i + 1,
        }
        for i in range(district_zips)
    ]
    # 254 counties spread round-robin over the district ZIPs that exist, so
    # every identity is matched and no ZIP is empty; the county/district
    # identity checks are exercised by their own tests below.
    if district_zips:
        artifacts += [
            {
                "type": "county_kmz",
                "path": f"districts/c{i:03d}.kmz",
                "county": f"C{i:03d}",
                "district": f"D{i % district_zips:02d}",
                "district_number": i % district_zips + 1,
            }
            for i in range(254)
        ]
    artifacts += [
        {"type": "statewide_zip", "path": f"offline/statewide-{i}.zip"}
        for i in range(statewide_zips)
    ]
    return {"schema_version": schema_version, "validation": validation, "artifacts": artifacts}


def _write(tmp_path, manifest):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_complete_manifest_passes(tmp_path, capsys):
    path = _write(tmp_path, _manifest())
    assert gate.main(["--manifest", str(path)]) == 0
    out = capsys.readouterr().out
    assert "  status:             complete" in out
    assert "  counties:           254/254" in out
    assert "  districts:          25/25" in out
    assert "  district_zip:       25/25" in out
    assert "  statewide_zip:      1/1" in out
    for artifact_type in EXACTLY_ONE_TYPES:
        assert f"  {artifact_type}: 1/1" in out
    assert "  artifact_count:     285" in out
    assert (
        "Release gate passed: complete statewide release "
        "(25/25 districts, 254/254 counties, 25 district ZIPs, 1 statewide ZIP, "
        "master KML, 4 boundary KMZs)"
    ) in out
    assert "::error::" not in out


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"status": "incomplete"}, "validation.status is 'incomplete', expected 'complete'"),
        ({"status": "partial"}, "validation.status is 'partial', expected 'complete'"),
        ({"districts_included": 24}, "districts 24/25, expected 25/25"),
        ({"districts_expected": 24, "districts_included": 24}, "districts 24/24, expected 25/25"),
        ({"counties_included": 253}, "counties 253/254, expected 254/254"),
        ({"counties_expected": 1, "counties_included": 1}, "counties 1/1, expected 254/254"),
        ({"required_missing": 2}, "2 required artifact(s) missing"),
        ({"required_invalid": 1}, "1 required artifact(s) invalid"),
    ],
)
def test_each_gate_condition_fails_independently(tmp_path, capsys, overrides, reason):
    path = _write(tmp_path, _manifest(**overrides))
    assert gate.main(["--manifest", str(path)]) == 1
    out = capsys.readouterr().out
    assert f"::error::Release gate failed: {reason}" in out
    assert out.count("::error::") == 1
    # The summary is still printed ahead of the failure.
    assert out.index("Manifest validation summary") < out.index("::error::")
    assert "Release gate passed" not in out


def test_all_failures_reported_together(tmp_path, capsys):
    manifest = _manifest(
        status="incomplete",
        districts_included=0,
        counties_included=0,
        required_missing=3,
        required_invalid=4,
        district_zips=0,
        statewide_zips=0,
    )
    assert gate.gate_failures(manifest) == [
        "validation.status is 'incomplete', expected 'complete'",
        "districts 0/25, expected 25/25",
        "counties 0/254, expected 254/254",
        "3 required artifact(s) missing",
        "4 required artifact(s) invalid",
        "expected 25 district_zip artifacts, found 0",
        "expected 1 statewide_zip artifact, found 0",
    ]


# --- Phase 3 bulk-download contract -----------------------------------------
#
# Every manifest below otherwise claims a complete release (status complete,
# 25/25, 254/254, nothing required missing/invalid), so the ZIP counts are
# the only thing that can fail it. That is also the defense-in-depth
# scenario: the gate does not take the validation summary's word for it.


@pytest.mark.parametrize(
    ("district_zips", "statewide_zips", "reasons"),
    [
        (24, 1, ["expected 25 district_zip artifacts, found 24"]),
        (26, 1, ["expected 25 district_zip artifacts, found 26"]),
        (25, 0, ["expected 1 statewide_zip artifact, found 0"]),
        (25, 2, ["expected 1 statewide_zip artifact, found 2"]),
        (
            24,
            0,
            [
                "expected 25 district_zip artifacts, found 24",
                "expected 1 statewide_zip artifact, found 0",
            ],
        ),
    ],
)
def test_wrong_zip_counts_fail_despite_complete_summary(
    tmp_path, capsys, district_zips, statewide_zips, reasons
):
    manifest = _manifest(district_zips=district_zips, statewide_zips=statewide_zips)
    assert manifest["validation"]["status"] == "complete"
    assert manifest["validation"]["required_missing"] == 0
    assert manifest["validation"]["required_invalid"] == 0

    path = _write(tmp_path, manifest)
    assert gate.main(["--manifest", str(path)]) == 1
    out = capsys.readouterr().out
    assert [line for line in out.splitlines() if line.startswith("::error::")] == [
        f"::error::Release gate failed: {reason}" for reason in reasons
    ]
    assert f"  district_zip:       {district_zips}/25" in out
    assert f"  statewide_zip:      {statewide_zips}/1" in out
    assert "Release gate passed" not in out


def test_zip_counts_are_by_type_not_path():
    # Other artifact types, including one that merely lives under offline/,
    # do not count toward the ZIP contract.
    manifest = _manifest(district_zips=24)
    manifest["artifacts"].append(
        {
            "type": "county_kmz",
            "path": "offline/districts/extra.zip",
            "county": "Extra",
            "district": "D00",
            "district_number": 1,
        }
    )
    assert gate.gate_failures(manifest) == ["expected 25 district_zip artifacts, found 24"]


def test_missing_manifest_fails(tmp_path, capsys):
    missing = tmp_path / "manifest.json"
    assert gate.main(["--manifest", str(missing)]) == 1
    out = capsys.readouterr().out
    assert f"::error::{missing} not found -- generate-manifest did not produce output" in out


def test_malformed_manifest_raises_before_printing_summary(tmp_path, capsys):
    manifest = _manifest()
    del manifest["validation"]["required_invalid"]
    path = _write(tmp_path, manifest)
    with pytest.raises(KeyError):
        gate.main(["--manifest", str(path)])
    assert "Manifest validation summary" not in capsys.readouterr().out


def test_runs_as_standalone_script(tmp_path):
    # The workflow invokes it with the runner's bare python3, outside uv.
    path = _write(tmp_path, _manifest(status="incomplete"))
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts/release/gate.py"), "--manifest", str(path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "::error::Release gate failed: validation.status is 'incomplete'" in result.stdout


# --- Exactly-one artifact types ------------------------------------------------
#
# A type the producer stopped registering would be in neither `artifacts`
# nor `skipped`, so the otherwise-complete summary below cannot catch it.


@pytest.mark.parametrize("artifact_type", EXACTLY_ONE_TYPES)
@pytest.mark.parametrize("count", [0, 2])
def test_exactly_one_types_fail_on_zero_or_duplicates(artifact_type, count):
    manifest = _manifest(single_counts={artifact_type: count})
    assert manifest["validation"]["status"] == "complete"
    assert gate.gate_failures(manifest) == [f"expected 1 {artifact_type} artifact, found {count}"]


# --- Manifest schema major version ---------------------------------------------


@pytest.mark.parametrize("version", ["2.0", "2.1", "2.2", "2.37"])
def test_any_2x_schema_version_is_accepted(version):
    assert gate.gate_failures(_manifest(schema_version=version)) == []


@pytest.mark.parametrize(
    ("version", "reason"),
    [
        ("3.0", "manifest schema major version 3 ('3.0') is not supported"),
        ("1.9", "manifest schema major version 1 ('1.9') is not supported"),
        (2.1, "schema_version 2.1 is not a 'MAJOR.MINOR' string"),
        ("2", "schema_version '2' is not a 'MAJOR.MINOR' string"),
        ("2.x", "schema_version '2.x' is not a 'MAJOR.MINOR' string"),
        ("2.1.0", "schema_version '2.1.0' is not a 'MAJOR.MINOR' string"),
        (None, "schema_version None is not a 'MAJOR.MINOR' string"),
    ],
)
def test_unsupported_or_malformed_schema_version_is_rejected(tmp_path, capsys, version, reason):
    path = _write(tmp_path, _manifest(schema_version=version))
    assert gate.main(["--manifest", str(path)]) == 1
    out = capsys.readouterr().out
    errors = [line for line in out.splitlines() if line.startswith("::error::")]
    assert len(errors) == 1
    assert errors[0].startswith(f"::error::Release gate failed: {reason}")


def test_missing_schema_version_is_rejected():
    manifest = _manifest()
    del manifest["schema_version"]
    assert gate.gate_failures(manifest) == ["manifest has no schema_version"]


def test_unknown_major_is_rejected_before_its_structure_is_read(tmp_path, capsys):
    # A future major may not have `validation`/`artifacts` at all; the gate
    # must reject it cleanly, not crash or print a 2.x summary.
    path = _write(tmp_path, {"schema_version": "3.0", "release": {}})
    assert gate.main(["--manifest", str(path)]) == 1
    out = capsys.readouterr().out
    assert "Manifest validation summary" not in out
    assert "not supported" in out


# --- County/district identity agreement ----------------------------------------
#
# The frontend joins county_kmz.district_number to district_zip.district_number,
# so the gate requires the manifest's two views of district identity to agree.
# Actual ZIP membership is validate-offline-packages' job, not the gate's.


def _of_type(manifest, artifact_type):
    return [a for a in manifest["artifacts"] if a["type"] == artifact_type]


def test_matching_identities_pass_on_a_realistic_manifest():
    manifest = _manifest()
    zips = _of_type(manifest, "district_zip")
    zips[0].update(district="Tyler", district_number=10)
    for county in _of_type(manifest, "county_kmz"):
        if county["district"] == "D00":
            county.update(district="Tyler", district_number=10)
    assert gate.gate_failures(manifest) == []


def test_orphan_county_fails():
    manifest = _manifest()
    county = _of_type(manifest, "county_kmz")[0]
    county.update(county="Smith", district="Tyler", district_number=10)
    assert gate.gate_failures(manifest) == [
        "county Smith / district Tyler / 10 has no matching district_zip"
    ]


def test_district_number_mismatch_fails():
    manifest = _manifest()
    county = _of_type(manifest, "county_kmz")[0]
    _of_type(manifest, "district_zip")[0].update(district="Tyler", district_number=11)
    for c in _of_type(manifest, "county_kmz"):
        if c["district"] == "D00":
            c.update(district="Tyler", district_number=11)
    county.update(county="Smith", district="Tyler", district_number=10)
    assert gate.gate_failures(manifest) == [
        "county Smith / district Tyler / 10 has no matching district_zip"
    ]


def test_district_name_mismatch_with_same_number_fails():
    manifest = _manifest()
    _of_type(manifest, "district_zip")[0].update(district="Some Other Name", district_number=10)
    for c in _of_type(manifest, "county_kmz"):
        if c["district"] == "D00":
            c.update(district="Some Other Name", district_number=10)
    county = _of_type(manifest, "county_kmz")[0]
    county.update(county="Smith", district="Tyler", district_number=10)
    assert gate.gate_failures(manifest) == [
        "county Smith / district Tyler / 10 has no matching district_zip"
    ]


def test_duplicate_district_zip_identity_fails():
    manifest = _manifest()
    zips = _of_type(manifest, "district_zip")
    # D01's counties move to D00 so the only failure is the duplicate itself.
    for c in _of_type(manifest, "county_kmz"):
        if c["district"] == "D01":
            c.update(district="D00", district_number=1)
    zips[1].update(district="D00", district_number=1)
    assert gate.gate_failures(manifest) == ["duplicate district_zip identity: D00 / 1"]


def test_district_zip_without_counties_fails():
    manifest = _manifest()
    for c in _of_type(manifest, "county_kmz"):
        if c["district"] == "D24":
            c.update(district="D00", district_number=1)
    assert gate.gate_failures(manifest) == ["district_zip D24 / 25 has no county_kmz members"]


def test_orphan_county_reports_are_capped(tmp_path, capsys):
    # A manifest whose ZIP identities are absent entirely (e.g. pre-2.1) must
    # not print one error per county.
    manifest = _manifest()
    for z in _of_type(manifest, "district_zip"):
        del z["district"], z["district_number"]
    failures = gate.district_identity_failures(manifest["artifacts"])
    assert failures[0] == "duplicate district_zip identity: None / None"
    orphans = [f for f in failures if f.endswith("has no matching district_zip")]
    assert len(orphans) == gate.MAX_ORPHAN_COUNTIES_REPORTED
    assert "... and 244 more county_kmz with no matching district_zip" in failures
    assert failures[-1] == "district_zip None / None has no county_kmz members"

    path = _write(tmp_path, manifest)
    assert gate.main(["--manifest", str(path)]) == 1
    assert "Release gate passed" not in capsys.readouterr().out
