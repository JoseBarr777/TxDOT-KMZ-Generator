"""Release-prefix collision guard for the staging workflow.

Answers: is releases/<release_id>/ unused, so this release can be uploaded
without touching an existing one? Release prefixes are immutable -- only
current.json is ever repointed -- and the upload step's `aws s3 sync` has
no --delete, so syncing into an occupied prefix would overwrite matching
paths in place, keep stale ones, and (when the path set is unchanged) still
pass verification. This check runs immediately before upload and refuses
any prefix that already holds even one object: complete, partial, failed,
verified or promoted are deliberately not distinguished. It never deletes,
repairs or resumes anything; a rerun of the workflow gets a new release ID.

The query asks for at most one key (`--page-size 1 --max-items 1`: one
ListObjectsV2 call with MaxKeys=1), so an existing release is never
enumerated. The prefix always ends in "/" so one release ID can never
prefix-match a longer one (e.g. ...-abc1234 vs ...-abc12345).

Fails closed: an aws CLI failure (credentials, permissions, endpoint,
network, API error) or a response that is not a JSON object with a list of
Contents is a failure, never "empty". Empty stdout with a zero exit is the
one exception -- some aws CLI versions print nothing for an empty paginated
listing -- and is read as no objects, matching verify.py.

With --verification-record, the same check guards the write-once
verified-candidate record instead: it requires that no object exists under
`verified/<release_id>.json` (see record_verification.py) before staging writes
one, so an existing record is never overwritten.

Exit status: 0 when the prefix (or record key) is unused, 1 otherwise.
Standard library only.

Usage:
    python3 scripts/release/check_prefix.py [--verification-record] \
        --bucket B --release-id ID --endpoint-url URL
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable

# Runs `aws <args> --endpoint-url <endpoint>` and returns stdout; raises on a
# non-zero exit. Same shape as verify.py's runner.
RunAws = Callable[[list[str]], str]


class PrefixCheckError(Exception):
    """The prefix could not be confirmed empty."""


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


def release_prefix(release_id: str) -> str:
    return f"releases/{release_id}/"


def verification_record_key(release_id: str) -> str:
    # Must match record_verification.verification_record_key (the scripts
    # are standalone, so each defines it; a test pins them together).
    return f"verified/{release_id}.json"


def first_existing_key(bucket: str, prefix: str, run_aws: RunAws) -> str | None:
    """Return one key under ``prefix`` if any exists, else None.

    Raises PrefixCheckError whenever emptiness cannot be established.
    """
    args = [
        "s3api",
        "list-objects-v2",
        "--bucket",
        bucket,
        "--prefix",
        prefix,
        "--page-size",
        "1",
        "--max-items",
        "1",
        "--output",
        "json",
    ]
    try:
        stdout = run_aws(args)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip() or f"exit status {exc.returncode}"
        raise PrefixCheckError(f"aws s3api list-objects-v2 failed: {detail}") from exc
    except OSError as exc:
        raise PrefixCheckError(f"could not run the aws CLI: {exc}") from exc

    if not stdout.strip():
        return None
    try:
        listing = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise PrefixCheckError(f"list-objects-v2 returned non-JSON output: {exc}") from exc
    if not isinstance(listing, dict):
        raise PrefixCheckError("list-objects-v2 returned JSON that is not an object")

    contents = listing.get("Contents", [])
    if not isinstance(contents, list):
        raise PrefixCheckError("list-objects-v2 returned a non-list Contents field")
    if contents:
        key = contents[0].get("Key") if isinstance(contents[0], dict) else None
        return key if isinstance(key, str) else "<unnamed object>"
    # A NextToken means more items exist beyond --max-items, so never "empty".
    if "NextToken" in listing:
        return "<object beyond first page>"
    return None


def check_prefix(
    bucket: str, release_id: str, run_aws: RunAws, *, verification_record: bool = False
) -> int:
    """Exit status 0 if releases/<release_id>/ is empty in ``bucket``, else 1.

    With ``verification_record``, checks verified/<release_id>.json instead.
    """
    if verification_record:
        return _check_verification_record(bucket, release_id, run_aws)

    prefix = release_prefix(release_id)
    print("Release prefix check")
    print(f"  bucket:  {bucket}")
    print(f"  prefix:  {prefix}")

    try:
        existing_key = first_existing_key(bucket, prefix, run_aws)
    except PrefixCheckError as exc:
        print(f"::error::Release prefix check failed for {prefix}: {exc}")
        print(
            "::error::Could not confirm the release prefix is empty, so nothing will be "
            "uploaded. Fix the R2 access problem and re-run the workflow."
        )
        return 1

    if existing_key is not None:
        print(
            f"::error::Release prefix {prefix} already contains objects in bucket "
            f"'{bucket}' (found: {existing_key})."
        )
        print(
            "::error::Release prefixes are immutable and are never reused, overwritten or "
            "cleaned up by staging; nothing will be uploaded into this prefix. "
            "Re-run the staging workflow to generate a new release ID."
        )
        return 1

    print(f"Release prefix check passed: {prefix} is empty.")
    return 0


def _check_verification_record(bucket: str, release_id: str, run_aws: RunAws) -> int:
    key = verification_record_key(release_id)
    print("Verification record check")
    print(f"  bucket:  {bucket}")
    print(f"  key:     {key}")

    try:
        existing_key = first_existing_key(bucket, key, run_aws)
    except PrefixCheckError as exc:
        print(f"::error::Verification record check failed for {key}: {exc}")
        print(
            "::error::Could not confirm no verification record exists, so none will be "
            "written. The release stays unverified; re-run the staging workflow."
        )
        return 1

    if existing_key is not None:
        print(
            f"::error::Verification record {key} already exists in bucket '{bucket}' "
            f"(found: {existing_key})."
        )
        print(
            "::error::Verification records are write-once; the existing record will not be "
            "overwritten. Re-run the staging workflow to generate a new release ID."
        )
        return 1

    print(f"Verification record check passed: {key} does not exist.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--endpoint-url", required=True)
    parser.add_argument(
        "--verification-record",
        action="store_true",
        help="check verified/<release_id>.json instead of releases/<release_id>/",
    )
    args = parser.parse_args(argv)
    return check_prefix(
        args.bucket,
        args.release_id,
        make_run_aws(args.endpoint_url),
        verification_record=args.verification_record,
    )


if __name__ == "__main__":
    sys.exit(main())
