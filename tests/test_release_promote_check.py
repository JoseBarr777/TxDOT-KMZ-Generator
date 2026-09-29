"""Behavior of scripts/release/promote_check.py, the promotion candidate check.

R2 is an in-memory fake answering the read-only aws calls the check makes
(head-object, s3 cp downloads, list-objects-v2). No network.
"""

import json
import subprocess
from pathlib import Path

import pytest

from release import promote_check, record_verification

BUCKET = "test-bucket"
RELEASE_ID = "2026-09-29T1412Z-57cd153"
OTHER_ID = "2026-09-20T0900Z-1b8b3cc"
GIT_SHA = "57cd153" + "a" * 33
PREFIX = f"releases/{RELEASE_ID}/"
RECORD_KEY = f"verified/{RELEASE_ID}.json"

EXACTLY_ONE = [
    ("master_kml", "master.kml"),
    ("district_boundaries_kmz", "boundaries/district_boundaries.kmz"),
    ("county_boundaries_kmz", "boundaries/county_boundaries.kmz"),
    ("city_boundaries_kmz", "boundaries/city_boundaries.kmz"),
    ("admin_boundaries_kmz", "boundaries/administrative_boundaries.kmz"),
]


def _manifest(*, schema_version="2.1", district_zips=25, drop_type=None):
    artifacts = [{"type": t, "path": p} for t, p in EXACTLY_ONE if t != drop_type]
    artifacts += [
        {"type": "district_zip", "path": f"offline/d{i:02d}.zip"} for i in range(district_zips)
    ]
    artifacts.append({"type": "statewide_zip", "path": "offline/texas_statewide.zip"})
    return {
        "schema_version": schema_version,
        "validation": {
            "status": "complete",
            "counties_included": 254,
            "counties_expected": 254,
            "districts_included": 25,
            "districts_expected": 25,
            "required_missing": 0,
            "required_invalid": 0,
        },
        "artifacts": artifacts,
    }


def _record(manifest_bytes, **overrides):
    record = record_verification.build_record(
        release_id=RELEASE_ID,
        manifest_bytes=manifest_bytes,
        git_sha=GIT_SHA,
        run_url="https://github.com/o/r/actions/runs/1",
        verified_at="2026-09-29T14:30:05Z",
    )
    record.update(overrides)
    return record


class FakeR2:
    """Objects keyed by full S3 key; records every aws call."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.calls: list[list[str]] = []
        self.denied: set[str] = set()

    def put_release(self, release_id, manifest, *, prefix=None, record=True, record_body=None):
        prefix = prefix or f"releases/{release_id}/"
        manifest_bytes = json.dumps(manifest).encode()
        self.objects[prefix + "manifest.json"] = manifest_bytes
        for artifact in manifest["artifacts"]:
            self.objects[prefix + artifact["path"]] = b"x"
        if record:
            body = record_body if record_body is not None else _record(manifest_bytes)
            if not isinstance(body, bytes):
                body = json.dumps(body).encode()
            self.objects[f"verified/{release_id}.json"] = body
        return manifest_bytes

    def __call__(self, args):
        self.calls.append(args)
        if args[:2] == ["s3api", "head-object"]:
            key = args[args.index("--key") + 1]
            if key in self.denied:
                raise subprocess.CalledProcessError(
                    255,
                    args,
                    stderr="An error occurred (403) when calling the HeadObject operation: Forbidden",
                )
            if key not in self.objects:
                raise subprocess.CalledProcessError(
                    254,
                    args,
                    stderr="An error occurred (404) when calling the HeadObject operation: Not Found",
                )
            return json.dumps({"ContentLength": len(self.objects[key])})
        if args[:2] == ["s3", "cp"]:
            key = args[2].removeprefix(f"s3://{BUCKET}/")
            Path(args[3]).write_bytes(self.objects[key])
            return ""
        if args[:2] == ["s3api", "list-objects-v2"]:
            prefix = args[args.index("--prefix") + 1]
            contents = [
                {"Key": k, "Size": len(v)}
                for k, v in sorted(self.objects.items())
                if k.startswith(prefix)
            ]
            return json.dumps({"Contents": contents} if contents else {})
        raise AssertionError(f"unexpected aws call: {args}")


@pytest.fixture
def r2():
    fake = FakeR2()
    fake.put_release(RELEASE_ID, _manifest())
    return fake


def _check(r2, tmp_path, capsys, release_id=RELEASE_ID):
    status, outputs = promote_check.check_candidate(BUCKET, release_id, r2, tmp_path)
    out = capsys.readouterr().out
    errors = [line for line in out.splitlines() if line.startswith("::error::")]
    return status, outputs, errors


def _set_current(r2, release_id):
    r2.objects["current.json"] = json.dumps(
        {"schema_version": 1, "release_id": release_id}
    ).encode()


# --- Promotable ------------------------------------------------------------------


def test_verified_contract_compliant_release_is_promotable(r2, tmp_path, capsys):
    _set_current(r2, OTHER_ID)
    status, outputs, errors = _check(r2, tmp_path, capsys)
    assert (status, errors) == (0, [])
    assert outputs == {
        "release_id": RELEASE_ID,
        "release_prefix": PREFIX,
        "git_sha_short": "57cd153",
        "current_release_id": OTHER_ID,
    }


def test_first_promotion_has_no_current_release(r2, tmp_path, capsys):
    status, outputs, _ = _check(r2, tmp_path, capsys)
    assert status == 0
    assert outputs["current_release_id"] == ""


def test_check_is_read_only(r2, tmp_path, capsys):
    _check(r2, tmp_path, capsys)
    for call in r2.calls:
        assert call[:2] in (["s3api", "head-object"], ["s3", "cp"], ["s3api", "list-objects-v2"])
        if call[:2] == ["s3", "cp"]:
            assert call[2].startswith("s3://") and not call[3].startswith("s3://")  # downloads only


# --- Refused before the candidate is examined ----------------------------------------


def test_already_current_release_is_refused(r2, tmp_path, capsys):
    _set_current(r2, RELEASE_ID)
    status, outputs, errors = _check(r2, tmp_path, capsys)
    assert (status, outputs) == (1, {})
    assert "already the current release" in errors[0]
    assert not any(PREFIX in " ".join(c) for c in r2.calls)  # never looked further


def test_malformed_current_pointer_is_refused(r2, tmp_path, capsys):
    r2.objects["current.json"] = b"{not json"
    status, _, errors = _check(r2, tmp_path, capsys)
    assert status == 1
    assert "current.json is not valid JSON" in errors[0]


def test_unreadable_object_is_never_treated_as_absent(r2, tmp_path, capsys):
    r2.denied.add("current.json")
    status, _, errors = _check(r2, tmp_path, capsys)
    assert status == 1
    assert "could not check current.json" in errors[0]


def test_path_like_release_id_is_refused_before_any_r2_call(r2, tmp_path, capsys):
    status, _, errors = _check(r2, tmp_path, capsys, release_id="../current")
    assert status == 1
    assert r2.calls == []


def test_missing_release_manifest_is_refused(tmp_path, capsys):
    status, _, errors = _check(FakeR2(), tmp_path, capsys)
    assert status == 1
    assert f"no {PREFIX}manifest.json" in errors[0]


def test_legacy_test_prefix_release_is_refused_without_fallback(tmp_path, capsys):
    r2 = FakeR2()
    r2.put_release(RELEASE_ID, _manifest(), prefix=f"releases/test-{RELEASE_ID}/")
    status, _, errors = _check(r2, tmp_path, capsys)
    assert status == 1
    assert "legacy releases/test-<release_id>/" in errors[0]
    assert not any("releases/test-" in " ".join(c) for c in r2.calls)


# --- Artifact gate ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("manifest", "reason"),
    [
        (_manifest(schema_version="3.0"), "manifest schema major version 3"),
        (_manifest(district_zips=0), "expected 25 district_zip artifacts, found 0"),  # pre-Phase-3
        (_manifest(drop_type="admin_boundaries_kmz"), "expected 1 admin_boundaries_kmz"),
    ],
)
def test_gate_rejection_blocks_promotion(tmp_path, capsys, manifest, reason):
    r2 = FakeR2()
    r2.put_release(RELEASE_ID, manifest)
    status, _, errors = _check(r2, tmp_path, capsys)
    assert status == 1
    assert any(
        e.startswith("::error::Promotion refused: artifact gate:") and reason in e for e in errors
    )


def test_malformed_2x_manifest_is_refused_not_crashed(tmp_path, capsys):
    manifest = _manifest()
    del manifest["validation"]["status"]
    r2 = FakeR2()
    r2.put_release(RELEASE_ID, manifest)
    status, _, errors = _check(r2, tmp_path, capsys)
    assert status == 1
    assert any("manifest is malformed" in e for e in errors)


# --- Verification record -------------------------------------------------------


def test_missing_verification_record_is_refused(tmp_path, capsys):
    r2 = FakeR2()
    r2.put_release(RELEASE_ID, _manifest(), record=False)
    status, _, errors = _check(r2, tmp_path, capsys)
    assert status == 1
    assert any("no verification record verified/" in e for e in errors)


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda r: b"{not json", "not valid JSON"),
        (lambda r: {**r, "schema_version": "1"}, "schema_version '1' is not 1"),
        (lambda r: {**r, "schema_version": True}, "schema_version True is not 1"),
        (lambda r: {k: v for k, v in r.items() if k != "run_url"}, "fields"),
        (lambda r: {**r, "extra": 1}, "fields"),
        (lambda r: {**r, "manifest_sha256": "ABC"}, "manifest_sha256"),
        (lambda r: {**r, "verified_at": "yesterday"}, "verified_at"),
        (lambda r: {**r, "run_url": "http://x"}, "run_url"),
        (lambda r: {**r, "release_id": OTHER_ID}, "!= requested release"),
        (
            lambda r: {**r, "git_sha": "1234567" + "a" * 33},
            "does not match the release ID's short SHA",
        ),
    ],
)
def test_invalid_verification_record_is_refused(tmp_path, capsys, mutate, reason):
    manifest = _manifest()
    manifest_bytes = json.dumps(manifest).encode()
    r2 = FakeR2()
    r2.put_release(RELEASE_ID, manifest, record_body=mutate(_record(manifest_bytes)))
    status, _, errors = _check(r2, tmp_path, capsys)
    assert status == 1
    assert any(reason in e for e in errors), errors


def test_record_for_different_manifest_bytes_is_refused(tmp_path, capsys):
    manifest = _manifest()
    r2 = FakeR2()
    # The record binds bytes, not meaning: re-serialized JSON is a different manifest.
    other_bytes = json.dumps(manifest, indent=2).encode()
    r2.put_release(RELEASE_ID, manifest, record_body=_record(other_bytes))
    status, _, errors = _check(r2, tmp_path, capsys)
    assert status == 1
    assert any("remote manifest sha256" in e and "!= verified manifest_sha256" in e for e in errors)


# --- Remote object count ---------------------------------------------------------


def test_extra_remote_object_is_refused(r2, tmp_path, capsys):
    r2.objects[PREFIX + ".gitkeep"] = b""
    status, _, errors = _check(r2, tmp_path, capsys)
    assert status == 1
    assert any("remote object count" in e for e in errors)


def test_missing_remote_artifact_is_refused(r2, tmp_path, capsys):
    del r2.objects[PREFIX + "offline/d03.zip"]
    status, _, errors = _check(r2, tmp_path, capsys)
    assert status == 1
    assert any("remote object count 31 != expected 32" in e for e in errors)


def test_all_candidate_failures_are_reported_together(tmp_path, capsys):
    r2 = FakeR2()
    r2.put_release(RELEASE_ID, _manifest(district_zips=0), record=False)
    r2.objects[PREFIX + "stray"] = b""
    status, _, errors = _check(r2, tmp_path, capsys)
    assert status == 1
    assert any("artifact gate" in e for e in errors)
    assert any("no verification record" in e for e in errors)
    assert any("remote object count" in e for e in errors)


# --- CLI outputs ----------------------------------------------------------------------


def test_main_writes_outputs_only_when_promotable(r2, tmp_path, monkeypatch):
    monkeypatch.setattr(promote_check, "make_run_aws", lambda endpoint: r2)
    out = tmp_path / "github_output"
    args = [
        "--bucket",
        BUCKET,
        "--release-id",
        RELEASE_ID,
        "--endpoint-url",
        "https://e",
        "--github-output",
        str(out),
    ]

    assert promote_check.main(args) == 0
    assert out.read_text().splitlines() == [
        f"release_id={RELEASE_ID}",
        f"release_prefix={PREFIX}",
        "git_sha_short=57cd153",
        "current_release_id=",
    ]

    out.unlink()
    del r2.objects[RECORD_KEY]
    assert promote_check.main(args) == 1
    assert not out.exists()
