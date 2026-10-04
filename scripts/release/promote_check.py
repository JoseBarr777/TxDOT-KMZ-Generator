"""Promotion candidate check: may current.json be pointed at this release?

A release is promotable only if all of these hold, checked read-only against R2
before release-promote.yml writes current.json:

  1. the release ID has the staging format (no path content);
  2. it is not already the current release (re-promoting is refused) and,
     with --require-newer (automatic promotion), it is strictly newer than the
     current release, so a stale rerun can never replace a newer release;
     manual promotion omits the flag, which is what keeps rollback possible;
  3. releases/<release_id>/manifest.json exists -- the current release layout
     only; legacy releases/test-<release_id>/ prefixes are not promotable;
  4. the manifest passes the release gate (scripts/release/gate.py): a
     supported 2.x schema, a complete release, and every artifact
     cardinality staging requires;
  5. verified/<release_id>.json exists -- the durable proof, written by staging
     only after remote verification passed -- and is a valid record for this
     release (record_verification.validate_record: the same rules staging
     used to write it);
  6. the record's manifest_sha256 equals the SHA-256 of the exact manifest
     bytes downloaded in (3), binding the verification to what is promoted;
  7. the remote prefix holds exactly len(artifacts) + 1 objects.

Full remote verification is not repeated: (5) and (6) prove it already
happened for exactly this manifest. Checks 4-7 are all evaluated and reported
together. An unexpected AWS/R2 error fails the check; nothing is ever treated
as absent unless the service says 404.

Outputs, appended as key=value lines to --github-output when the check passes:
release_id, release_prefix, git_sha_short, current_release_id ("" if there is
no current release).

Exit status: 0 if the release is promotable, 1 otherwise. Standard library
only.

Usage:
    python3 scripts/release/promote_check.py --bucket B --release-id ID \\
        --endpoint-url URL [--require-newer] [--github-output PATH]
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

# The release scripts run standalone (python3 scripts/release/<name>.py); make
# the sibling gate and record modules importable so their rules are reused,
# never restated.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import gate  # noqa: E402
import record_verification  # noqa: E402

CURRENT_POINTER_KEY = "current.json"

# Runs `aws <args> --endpoint-url <endpoint>` and returns stdout; raises
# CalledProcessError on a non-zero exit. Same shape as verify.py's runner.
RunAws = Callable[[list[str]], str]


class PromotionRefused(Exception):
    """The candidate cannot be evaluated (or must not be) -- promotion stops."""


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


# --- Read-only R2 access ----------------------------------------------------


def _is_not_found(exc: subprocess.CalledProcessError) -> bool:
    stderr = exc.stderr or ""
    return "(404)" in stderr or "Not Found" in stderr


def fetch_optional(run_aws: RunAws, bucket: str, key: str, workdir: Path) -> bytes | None:
    """The object's bytes, None if R2 reports it does not exist (404).

    Any other failure (credentials, permissions, network) raises
    PromotionRefused -- an unreadable object is never treated as absent.
    """
    try:
        run_aws(["s3api", "head-object", "--bucket", bucket, "--key", key, "--output", "json"])
    except subprocess.CalledProcessError as exc:
        if _is_not_found(exc):
            return None
        raise PromotionRefused(f"could not check {key}: {(exc.stderr or '').strip()}") from exc

    dest = workdir / key.replace("/", "__")
    try:
        run_aws(["s3", "cp", f"s3://{bucket}/{key}", str(dest)])
    except subprocess.CalledProcessError as exc:
        raise PromotionRefused(f"could not download {key}: {(exc.stderr or '').strip()}") from exc
    return dest.read_bytes()


def count_remote_objects(run_aws: RunAws, bucket: str, prefix: str) -> int:
    # No pagination options: the aws CLI fetches and merges every page itself,
    # so this is the whole prefix.
    try:
        stdout = run_aws(
            ["s3api", "list-objects-v2", "--bucket", bucket, "--prefix", prefix, "--output", "json"]
        )
    except subprocess.CalledProcessError as exc:
        raise PromotionRefused(f"could not list {prefix}: {(exc.stderr or '').strip()}") from exc
    if not stdout.strip():
        return 0
    try:
        listing = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise PromotionRefused(f"listing of {prefix} is not JSON: {exc}") from exc
    contents = listing.get("Contents", []) if isinstance(listing, dict) else None
    if not isinstance(contents, list):
        raise PromotionRefused(f"listing of {prefix} has no usable Contents")
    return len(contents)


# --- Pure checks ---------------------------------------------------------------


def release_timestamp(release_id: str) -> str:
    """The release ID's UTC timestamp, e.g. 2026-09-29T1412Z.

    Fixed-width and zero-padded (date -u +'%Y-%m-%dT%H%MZ' in
    release-staging.yml), so these strings sort chronologically. Only this part
    is compared: within one minute, comparing whole IDs would fall through to
    the git SHAs, whose order means nothing.
    """
    return release_id.rsplit("-", 1)[0]


def ordering_failure(release_id: str, current_id: str | None) -> str | None:
    """Why ``release_id`` is not newer than the current release, or None if it is.

    Used only with --require-newer. No current release is not a failure (first
    promotion). A same-minute candidate is not newer: refused, never guessed.
    """
    if current_id is None:
        return None
    try:
        record_verification.check_release_id(current_id)
    except record_verification.RecordError:
        return f"current release_id {current_id!r} has no comparable timestamp"
    if release_timestamp(release_id) <= release_timestamp(current_id):
        return (
            f"candidate release {release_id} is not newer than current release {current_id} "
            "-- automatic promotion only moves forward"
        )
    return None


def current_release_id_from(current_bytes: bytes | None) -> str | None:
    """The release current.json points at, or None if there is no current.json."""
    if current_bytes is None:
        return None
    try:
        doc = json.loads(current_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise PromotionRefused(f"current.json is not valid JSON: {exc}") from exc
    release_id = doc.get("release_id") if isinstance(doc, dict) else None
    if not isinstance(release_id, str):
        raise PromotionRefused("current.json has no string release_id")
    return release_id


def candidate_failures(
    *,
    release_id: str,
    manifest_bytes: bytes,
    record_bytes: bytes | None,
    remote_count: int,
) -> list[str]:
    """Every reason the downloaded candidate is not promotable (empty = promotable)."""
    try:
        manifest = json.loads(manifest_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return [f"manifest.json is not valid JSON: {exc}"]
    if not isinstance(manifest, dict):
        return ["manifest.json is not a JSON object"]

    failures = []

    try:
        failures += [f"artifact gate: {reason}" for reason in gate.gate_failures(manifest)]
    except (KeyError, TypeError) as exc:
        failures.append(f"artifact gate: manifest is malformed ({exc!r})")

    if record_bytes is None:
        failures.append(
            f"no verification record verified/{release_id}.json -- this release never "
            "passed staging verification"
        )
    else:
        try:
            record = json.loads(record_bytes)
            record_verification.validate_record(record, release_id=release_id)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            failures.append(f"verification record is not valid JSON: {exc}")
        except record_verification.RecordError as exc:
            failures.append(f"verification record invalid: {exc}")
        else:
            actual = hashlib.sha256(manifest_bytes).hexdigest()
            if actual != record["manifest_sha256"]:
                failures.append(
                    f"remote manifest sha256 {actual} != verified manifest_sha256 "
                    f"{record['manifest_sha256']}"
                )

    artifacts = manifest.get("artifacts")
    if isinstance(artifacts, list):
        expected = len(artifacts) + 1  # + manifest.json
        if remote_count != expected:
            failures.append(
                f"remote object count {remote_count} != expected {expected} "
                "(manifest artifacts + manifest.json)"
            )
    else:
        failures.append("manifest has no artifacts list; remote object count unchecked")

    return failures


# --- Orchestration -------------------------------------------------------------


def check_candidate(
    bucket: str, release_id: str, run_aws: RunAws, workdir: Path, *, require_newer: bool = False
) -> tuple[int, dict[str, str]]:
    """(exit status, outputs). Only read-only AWS calls are made."""
    prefix = release_prefix(release_id)
    print("Promotion candidate check")
    print(f"  bucket:     {bucket}")
    print(f"  release_id: {release_id}")
    print(f"  prefix:     {prefix}")

    try:
        record_verification.check_release_id(release_id)

        current_id = current_release_id_from(
            fetch_optional(run_aws, bucket, CURRENT_POINTER_KEY, workdir)
        )
        print(f"  current:    {current_id or '(none -- first promotion)'}")
        if current_id == release_id:
            raise PromotionRefused(
                f"release '{release_id}' is already the current release -- nothing to promote"
            )
        if require_newer:
            stale = ordering_failure(release_id, current_id)
            if stale is not None:
                raise PromotionRefused(stale)

        manifest_bytes = fetch_optional(run_aws, bucket, f"{prefix}manifest.json", workdir)
        if manifest_bytes is None:
            raise PromotionRefused(
                f"no {prefix}manifest.json -- not a promotable release (only the "
                "releases/<release_id>/ layout is; legacy releases/test-<release_id>/ "
                "releases are not)"
            )
        record_bytes = fetch_optional(
            run_aws, bucket, record_verification.verification_record_key(release_id), workdir
        )
        remote_count = count_remote_objects(run_aws, bucket, prefix)
    except (PromotionRefused, record_verification.RecordError) as exc:
        print(f"::error::Promotion refused: {exc}")
        return 1, {}

    failures = candidate_failures(
        release_id=release_id,
        manifest_bytes=manifest_bytes,
        record_bytes=record_bytes,
        remote_count=remote_count,
    )
    if failures:
        for reason in failures:
            print(f"::error::Promotion refused: {reason}")
        return 1, {}

    outputs = {
        "release_id": release_id,
        "release_prefix": prefix,
        # The release ID's short SHA; validate_record already required the
        # verified full git_sha to start with it.
        "git_sha_short": release_id.rsplit("-", 1)[1],
        "current_release_id": current_id or "",
    }
    print(f"  remote objects: {remote_count}")
    print("Promotion candidate check: PASSED (verified, gate-clean, manifest bound)")
    return 0, outputs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--endpoint-url", required=True)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument(
        "--require-newer",
        action="store_true",
        help="refuse unless the candidate is newer than the current release (automatic promotion)",
    )
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory() as tmpdir:
        status, outputs = check_candidate(
            args.bucket,
            args.release_id,
            make_run_aws(args.endpoint_url),
            Path(tmpdir),
            require_newer=args.require_newer,
        )

    if status == 0 and args.github_output is not None:
        with args.github_output.open("a", encoding="utf-8") as fh:
            for key, value in outputs.items():
                fh.write(f"{key}={value}\n")
    return status


if __name__ == "__main__":
    sys.exit(main())
