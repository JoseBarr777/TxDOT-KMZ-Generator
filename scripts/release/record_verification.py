"""Build the verified-candidate record for a release that passed staging.

Answers: what durable proof does R2 hold that releases/<release_id>/ passed
remote verification? After verify.py succeeds, the staging workflow writes
this record, write-once, to `verified/<release_id>.json` at the bucket root.
That key is outside the immutable release prefix: the record is release-process
metadata, not an artifact, so the release itself stays exactly manifest.json +
manifest-listed artifacts.

The record binds a release ID to the exact manifest bytes that were verified.
`manifest_sha256` is the SHA-256 of release-stage/manifest.json, the file
uploaded as releases/<release_id>/manifest.json and hash-checked against its
remote copy by verify.py. Promotion can therefore download the remote manifest,
hash it, and require a match. The record claims nothing else: not that the
release is promoted, current, or still unmodified since verification.

This script only validates inputs and writes the record to a local file; the
workflow does the existence check (check_prefix.py --verification-record) and
the upload. `validate_record` is the single definition of a valid record: it
applies the same field rules `build_record` does, and promote_check.py uses it
on the record it downloads. Standard library only.

Exit status: 0 when the record was written, 1 on invalid input or a missing
manifest.

Usage:
    python3 scripts/release/record_verification.py --release-id ID \\
        --manifest release-stage/manifest.json --git-sha SHA --run-url URL --output PATH
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1

# The exact shape "Compute release ID" produces (UTC timestamp to the minute +
# git short SHA); the same pattern release-promote.yml validates. It admits no
# "/", "\\" or "..", so verified/<release_id>.json can never name another key.
RELEASE_ID_RE = re.compile(
    r"[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])T([01][0-9]|2[0-3])[0-5][0-9]Z-[0-9a-f]{7,40}"
)
GIT_SHA_RE = re.compile(r"[0-9a-f]{40}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
RECORD_FIELDS = (
    "schema_version",
    "release_id",
    "manifest_sha256",
    "git_sha",
    "verified_at",
    "run_url",
)


class RecordError(ValueError):
    """An input the record must not be built from."""


def verification_record_key(release_id: str) -> str:
    return f"verified/{release_id}.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime(TIMESTAMP_FORMAT)


def _is_str(value) -> bool:
    return isinstance(value, str)


def check_release_id(release_id) -> None:
    if not (_is_str(release_id) and RELEASE_ID_RE.fullmatch(release_id)):
        raise RecordError(
            f"release_id {release_id!r} does not match <UTC timestamp>-<git short sha>"
        )


def _check_git_sha(git_sha, release_id: str) -> None:
    if not (_is_str(git_sha) and GIT_SHA_RE.fullmatch(git_sha)):
        raise RecordError(f"git_sha {git_sha!r} is not a full 40-character lowercase hex SHA")
    short_sha = release_id.rsplit("-", 1)[1]
    if not git_sha.startswith(short_sha):
        raise RecordError(
            f"git_sha {git_sha} does not match the release ID's short SHA {short_sha}"
        )


def _check_run_url(run_url) -> None:
    if not (_is_str(run_url) and run_url.startswith("https://")):
        raise RecordError(f"run_url {run_url!r} is not an https URL")


def _check_verified_at(verified_at) -> None:
    try:
        datetime.strptime(verified_at, TIMESTAMP_FORMAT)
    except (TypeError, ValueError) as exc:
        raise RecordError(
            f"verified_at {verified_at!r} is not a UTC timestamp like 2026-09-29T14:30:05Z"
        ) from exc


def validate_record(record, *, release_id: str) -> None:
    """Raise RecordError unless ``record`` is a valid record for ``release_id``.

    The same field rules build_record applies, plus the exact field set, the
    schema version and the expected release ID.
    """
    if not isinstance(record, dict):
        raise RecordError("verification record is not a JSON object")
    if set(record) != set(RECORD_FIELDS):
        raise RecordError(
            f"verification record fields {sorted(record)} != expected {sorted(RECORD_FIELDS)}"
        )
    version = record["schema_version"]
    if type(version) is not int or version != SCHEMA_VERSION:
        raise RecordError(f"schema_version {version!r} is not {SCHEMA_VERSION}")
    check_release_id(record["release_id"])
    if record["release_id"] != release_id:
        raise RecordError(
            f"record release_id {record['release_id']!r} != requested release {release_id!r}"
        )
    sha = record["manifest_sha256"]
    if not (_is_str(sha) and SHA256_RE.fullmatch(sha)):
        raise RecordError(f"manifest_sha256 {sha!r} is not 64 lowercase hex characters")
    _check_git_sha(record["git_sha"], release_id)
    _check_verified_at(record["verified_at"])
    _check_run_url(record["run_url"])


def build_record(
    *,
    release_id: str,
    manifest_bytes: bytes,
    git_sha: str,
    run_url: str,
    verified_at: str,
) -> dict:
    """The verification record for ``release_id``; raises RecordError on bad input."""
    check_release_id(release_id)
    _check_git_sha(git_sha, release_id)
    _check_run_url(run_url)
    _check_verified_at(verified_at)
    if not manifest_bytes:
        raise RecordError("manifest is empty")

    return {
        "schema_version": SCHEMA_VERSION,
        "release_id": release_id,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "git_sha": git_sha,
        "verified_at": verified_at,
        "run_url": run_url,
    }


def serialize(record: dict) -> str:
    return json.dumps(record, indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--git-sha", required=True)
    parser.add_argument("--run-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        manifest_bytes = args.manifest.read_bytes()
    except FileNotFoundError:
        print(f"::error::{args.manifest} not found -- nothing was verified to record")
        return 1

    try:
        record = build_record(
            release_id=args.release_id,
            manifest_bytes=manifest_bytes,
            git_sha=args.git_sha,
            run_url=args.run_url,
            verified_at=utc_now(),
        )
    except RecordError as exc:
        print(f"::error::Verification record not created: {exc}")
        return 1

    args.output.write_text(serialize(record), encoding="utf-8")
    print(f"Verification record for {verification_record_key(args.release_id)}:")
    print(serialize(record), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
