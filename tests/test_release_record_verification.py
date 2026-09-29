"""Behavior of scripts/release/record_verification.py, the verified-candidate record.

The record binds a release ID to the exact manifest bytes that passed remote
verification (plus the full commit SHA and the run), so promotion can later
require that the remote manifest hashes to `manifest_sha256`.
"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from release import check_prefix, record_verification
from release.record_verification import RecordError, build_record

REPO_ROOT = Path(__file__).resolve().parents[1]
RELEASE_ID = "2026-09-29T1412Z-57cd153"
GIT_SHA = "57cd153" + "a" * 33
RUN_URL = "https://github.com/jfbarr777/txdot/actions/runs/123456"
VERIFIED_AT = "2026-09-29T14:30:05Z"
MANIFEST = b'{"schema_version": "2.1", "artifacts": []}\n'


def _record(**overrides):
    kwargs = {
        "release_id": RELEASE_ID,
        "manifest_bytes": MANIFEST,
        "git_sha": GIT_SHA,
        "run_url": RUN_URL,
        "verified_at": VERIFIED_AT,
        **overrides,
    }
    return build_record(**kwargs)


def test_record_has_exactly_the_schema_fields():
    assert _record() == {
        "schema_version": 1,
        "release_id": RELEASE_ID,
        "manifest_sha256": hashlib.sha256(MANIFEST).hexdigest(),
        "git_sha": GIT_SHA,
        "verified_at": VERIFIED_AT,
        "run_url": RUN_URL,
    }


def test_manifest_sha256_is_of_the_exact_bytes():
    # Any byte difference -- even whitespace -- is a different manifest.
    assert _record(manifest_bytes=b"abc")["manifest_sha256"] == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
    assert (
        _record(manifest_bytes=MANIFEST)["manifest_sha256"]
        != _record(manifest_bytes=MANIFEST.rstrip())["manifest_sha256"]
    )


def test_serialized_record_round_trips_as_clean_json():
    text = record_verification.serialize(_record())
    assert text.endswith("\n")
    assert json.loads(text) == _record()


@pytest.mark.parametrize(
    "release_id",
    ["2026-09-29T1412Z-57cd153", "2026-12-31T2359Z-" + "a" * 40],
)
def test_valid_release_ids_are_accepted(release_id):
    short = release_id.rsplit("-", 1)[1]
    git_sha = (short + "0" * 40)[:40]
    assert _record(release_id=release_id, git_sha=git_sha)["release_id"] == release_id


@pytest.mark.parametrize(
    "release_id",
    [
        "",
        "../2026-09-29T1412Z-57cd153",
        "2026-09-29T1412Z-57cd153/../x",
        "2026-09-29T1412Z-57cd153\\x",
        "releases/2026-09-29T1412Z-57cd153",
        "2026-09-29T1412Z-57CD153",  # uppercase hex
        "2026-09-29T1412Z-57cd15",  # SHA too short
        "2026-13-29T1412Z-57cd153",  # month 13
        "2026-09-29T1412-57cd153",  # no Z
        "2026-09-29T1412Z-57cd153 ",
    ],
)
def test_malformed_or_path_like_release_ids_are_rejected(release_id):
    with pytest.raises(RecordError, match="release_id"):
        _record(release_id=release_id)


@pytest.mark.parametrize("git_sha", ["57cd153", "57CD153" + "a" * 33, "57cd153" + "g" * 33, ""])
def test_git_sha_must_be_a_full_lowercase_sha(git_sha):
    with pytest.raises(RecordError, match="git_sha"):
        _record(git_sha=git_sha)


def test_git_sha_must_match_the_release_ids_short_sha():
    with pytest.raises(RecordError, match="does not match the release ID's short SHA"):
        _record(git_sha="1234567" + "a" * 33)


def test_run_url_must_be_https():
    with pytest.raises(RecordError, match="run_url"):
        _record(run_url="http://example.test/run")


def test_empty_manifest_is_rejected():
    with pytest.raises(RecordError, match="manifest is empty"):
        _record(manifest_bytes=b"")


def test_verified_at_is_a_utc_second_resolution_timestamp():
    stamp = record_verification.utc_now()
    assert len(stamp) == 20 and stamp.endswith("Z")
    from datetime import datetime

    datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ")


def test_record_key_matches_the_write_once_check():
    assert record_verification.verification_record_key(RELEASE_ID) == (
        f"verified/{RELEASE_ID}.json"
    )
    assert check_prefix.verification_record_key(RELEASE_ID) == (
        record_verification.verification_record_key(RELEASE_ID)
    )


# --- CLI -----------------------------------------------------------------------


def _run(tmp_path, *extra, manifest=MANIFEST):
    manifest_path = tmp_path / "manifest.json"
    if manifest is not None:
        manifest_path.write_bytes(manifest)
    output = tmp_path / "record.json"
    args = [
        "--release-id",
        RELEASE_ID,
        "--manifest",
        str(manifest_path),
        "--git-sha",
        GIT_SHA,
        "--run-url",
        RUN_URL,
        "--output",
        str(output),
        *extra,
    ]
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts/release/record_verification.py"), *args],
        capture_output=True,
        text=True,
    )
    return result, output


def test_cli_writes_the_record_for_the_staged_manifest(tmp_path):
    result, output = _run(tmp_path)
    assert result.returncode == 0, result.stdout
    record = json.loads(output.read_text(encoding="utf-8"))
    assert set(record) == {
        "schema_version",
        "release_id",
        "manifest_sha256",
        "git_sha",
        "verified_at",
        "run_url",
    }
    assert record["manifest_sha256"] == hashlib.sha256(MANIFEST).hexdigest()
    assert f"verified/{RELEASE_ID}.json" in result.stdout


def test_cli_fails_without_writing_on_missing_manifest(tmp_path):
    result, output = _run(tmp_path, manifest=None)
    assert result.returncode == 1
    assert "::error::" in result.stdout
    assert not output.exists()


def test_cli_fails_without_writing_on_invalid_input(tmp_path):
    result, output = _run(tmp_path, "--release-id", "../escape")
    assert result.returncode == 1
    assert "::error::Verification record not created" in result.stdout
    assert not output.exists()
