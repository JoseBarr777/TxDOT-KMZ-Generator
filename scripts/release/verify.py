"""Post-upload verification of a staged R2 release.

Answers: did the uploaded candidate release contain what the staging
workflow expected? Compares the remote releases/<release_id>/ prefix
against the local release-stage/ tree (which is exactly manifest.json + the
manifest-declared artifacts, so "remote == local" means "remote == the
manifest contract"):

  1. remote object count == local staged file count
  2. remote object count == manifest artifacts + 1 (manifest.json)
  3. every manifest artifact is present remotely with its manifest size_bytes,
     and manifest.json is present
  4. re-downloaded sha256 of the representative set -- manifest.json,
     master.kml, the first county_kmz, the first district_zip, and the
     statewide_zip -- matches the local copy / manifest
  5. content-type of that same representative set

Checks 1-3 cover every artifact; 4-5 go deep on one artifact per upload
pass/product type. Every District ZIP is uploaded by the same pass and is
already count/size-checked here and deeply validated locally by
validate-offline-packages, so one representative District ZIP proves the
remote path; the Statewide ZIP is unique, so it is checked directly.

Extracted verbatim in behavior from the former inline heredoc in
.github/workflows/release-staging.yml ("Verify staged release"). Remote
access still goes through the aws CLI, exactly as before; the checks
themselves are plain functions so they can be tested without R2.
Standard library only.

Exit status: 0 when verification passes, 1 when any check fails. An aws CLI
failure, or a malformed/missing local manifest, raises and exits 1 with a
traceback, exactly as the inline version did.

Usage:
    python3 scripts/release/verify.py --bucket B --release-id ID --endpoint-url URL \\
        [--stage-dir release-stage]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

DEFAULT_STAGE_DIR = "release-stage"
MANIFEST_NAME = "manifest.json"
MASTER_KML = "master.kml"

KML_CONTENT_TYPE = "application/vnd.google-earth.kml+xml"
KMZ_CONTENT_TYPE = "application/vnd.google-earth.kmz"
JSON_CONTENT_TYPE = "application/json"
ZIP_CONTENT_TYPE = "application/zip"

COUNTY_KMZ_TYPE = "county_kmz"
DISTRICT_ZIP_TYPE = "district_zip"
STATEWIDE_ZIP_TYPE = "statewide_zip"

# Cap on individually listed size mismatches, so a wholesale failure does
# not bury the log.
MAX_SIZE_MISMATCHES_REPORTED = 10

# Runs `aws <args> --endpoint-url <endpoint>` and returns stdout; raises on a
# non-zero exit.
RunAws = Callable[[list[str]], str]


class VerificationAborted(Exception):
    """A precondition failed that makes the remaining checks meaningless."""


def make_run_aws(endpoint: str) -> RunAws:
    def run_aws(args: list[str]) -> str:
        result = subprocess.run(
            ["aws", *args, "--endpoint-url", endpoint],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout

    return run_aws


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def remote_sizes_from_listing(listing: dict, prefix: str) -> dict[str, int]:
    """Map prefix-relative key -> size from a list-objects-v2 response.

    Raises VerificationAborted on a truncated listing, since this check does
    not paginate and a partial listing would under-count.
    """
    if listing.get("IsTruncated"):
        raise VerificationAborted(
            "Object listing was truncated (>1000 objects); this check does not paginate"
        )
    return {obj["Key"][len(prefix) :]: obj["Size"] for obj in listing.get("Contents", [])}


def count_failures(
    remote_count: int, local_file_count: int, expected_remote_count: int
) -> list[str]:
    failures = []
    if remote_count != local_file_count:
        failures.append(
            f"remote object count {remote_count} != local file count {local_file_count}"
        )
    if remote_count != expected_remote_count:
        failures.append(
            f"remote object count {remote_count} != expected {expected_remote_count} "
            "(manifest artifacts + manifest.json)"
        )
    return failures


def size_mismatches(manifest: dict, remote_sizes: dict[str, int]) -> list[str]:
    mismatches = []
    for artifact in manifest["artifacts"]:
        path = artifact["path"]
        expected_size = artifact["size_bytes"]
        remote_size = remote_sizes.get(path)
        if remote_size is None:
            mismatches.append(f"{path}: missing from remote listing")
        elif remote_size != expected_size:
            mismatches.append(f"{path}: remote size {remote_size} != manifest size {expected_size}")
    if MANIFEST_NAME not in remote_sizes:
        mismatches.append(f"{MANIFEST_NAME}: missing from remote listing")
    return mismatches


def representative(manifest: dict, artifact_type: str) -> dict:
    """The first ``artifact_type`` artifact in manifest order."""
    for artifact in manifest["artifacts"]:
        if artifact["type"] == artifact_type:
            return artifact
    raise VerificationAborted(f"No {artifact_type} artifacts found in manifest")


def verify(
    stage_dir: Path,
    bucket: str,
    release_id: str,
    run_aws: RunAws,
) -> int:
    """Verify releases/<release_id>/ in ``bucket`` against ``stage_dir``; return exit status."""
    prefix = f"releases/{release_id}/"

    manifest_path = stage_dir / MANIFEST_NAME
    with manifest_path.open(encoding="utf-8") as fh:
        manifest = json.load(fh)

    local_manifest_sha256 = sha256_file(manifest_path)
    local_file_count = sum(1 for p in stage_dir.rglob("*") if p.is_file())
    expected_remote_count = len(manifest["artifacts"]) + 1  # +1 for manifest.json itself

    print("Verification")
    print(f"  release id:          {release_id}")
    print(f"  bucket:              {bucket}")
    print(f"  prefix:              {prefix}")
    print(f"  local file count:    {local_file_count}")
    print(f"  manifest artifacts:  {len(manifest['artifacts'])}")

    failures = []

    try:
        # 1 & 2: remote object count vs. manifest artifact count / local file count
        listing_raw = run_aws(
            ["s3api", "list-objects-v2", "--bucket", bucket, "--prefix", prefix, "--output", "json"]
        )
        listing = json.loads(listing_raw) if listing_raw.strip() else {}
        remote_sizes = remote_sizes_from_listing(listing, prefix)
        remote_count = len(listing.get("Contents", []))
        print(f"  remote object count: {remote_count}")
        failures.extend(count_failures(remote_count, local_file_count, expected_remote_count))

        # 3: per-artifact size comparison against manifest size_bytes
        mismatches = size_mismatches(manifest, remote_sizes)
        print(f"  size mismatches:     {len(mismatches)}")
        failures.extend(mismatches[:MAX_SIZE_MISMATCHES_REPORTED])
        if len(mismatches) > MAX_SIZE_MISMATCHES_REPORTED:
            failures.append(
                f"...and {len(mismatches) - MAX_SIZE_MISMATCHES_REPORTED} more size mismatches"
            )

        # Resolved before any download, so an impossible release aborts
        # without partial verification.
        county = representative(manifest, COUNTY_KMZ_TYPE)
        district_zip = representative(manifest, DISTRICT_ZIP_TYPE)
        statewide_zip = representative(manifest, STATEWIDE_ZIP_TYPE)
    except VerificationAborted as exc:
        print(f"::error::{exc}")
        return 1

    # 4: re-download and hash the representative set
    targets = {
        MANIFEST_NAME: local_manifest_sha256,
        MASTER_KML: None,  # hashed from the local staged copy
        county["path"]: county["sha256"],
        district_zip["path"]: district_zip["sha256"],
        statewide_zip["path"]: statewide_zip["sha256"],
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        for remote_path, expected_hash in targets.items():
            if expected_hash is None:
                expected_hash = sha256_file(stage_dir / remote_path)

            dest_path = Path(tmpdir) / Path(remote_path).name
            run_aws(["s3", "cp", f"s3://{bucket}/{prefix}{remote_path}", str(dest_path)])
            downloaded_hash = sha256_file(dest_path)

            ok = downloaded_hash == expected_hash
            print(f"  hash check {remote_path}: {'OK' if ok else 'MISMATCH'}")
            if not ok:
                failures.append(
                    f"{remote_path}: sha256 mismatch (local {expected_hash}, remote {downloaded_hash})"
                )

    # 5: content-type checks for the same representative set
    content_type_checks = {
        MASTER_KML: KML_CONTENT_TYPE,
        county["path"]: KMZ_CONTENT_TYPE,
        district_zip["path"]: ZIP_CONTENT_TYPE,
        statewide_zip["path"]: ZIP_CONTENT_TYPE,
        MANIFEST_NAME: JSON_CONTENT_TYPE,
    }
    for remote_path, expected_ct in content_type_checks.items():
        head_raw = run_aws(
            [
                "s3api",
                "head-object",
                "--bucket",
                bucket,
                "--key",
                f"{prefix}{remote_path}",
                "--output",
                "json",
            ]
        )
        actual_ct = json.loads(head_raw).get("ContentType")
        print(f"  content-type {remote_path}: {actual_ct}")
        if actual_ct != expected_ct:
            failures.append(
                f"{remote_path}: content-type '{actual_ct}' != expected '{expected_ct}'"
            )

    if failures:
        for reason in failures:
            print(f"::error::Verification failed: {reason}")
        return 1

    print("Verification passed: staged release is complete and consistent.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--endpoint-url", required=True)
    parser.add_argument("--stage-dir", type=Path, default=Path(DEFAULT_STAGE_DIR))
    args = parser.parse_args(argv)
    return verify(args.stage_dir, args.bucket, args.release_id, make_run_aws(args.endpoint_url))


if __name__ == "__main__":
    sys.exit(main())
