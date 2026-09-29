"""Behavior of scripts/release/check_prefix.py, the release-prefix collision guard.

No R2: the aws CLI is replaced by an in-process fake runner, or (for the
subprocess path) by a fake `aws` executable on PATH.
"""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from release import check_prefix

REPO_ROOT = Path(__file__).resolve().parents[1]
BUCKET = "test-bucket"
RELEASE_ID = "2026-09-28T1412Z-57cd153"
PREFIX = f"releases/{RELEASE_ID}/"
ENDPOINT = "https://acct.r2.cloudflarestorage.com"


class FakeAws:
    """Returns canned stdout (or raises) for the single list-objects-v2 call."""

    def __init__(self, stdout="", exc=None):
        self.stdout = stdout
        self.exc = exc
        self.calls = []

    def __call__(self, args):
        self.calls.append(args)
        if self.exc is not None:
            raise self.exc
        return self.stdout


def _listing(*keys, **extra):
    body = {"RequestCharged": None, "Prefix": PREFIX, **extra}
    if keys:
        body["Contents"] = [{"Key": k, "Size": 1} for k in keys]
    return json.dumps(body)


def _run(fake, capsys):
    rc = check_prefix.check_prefix(BUCKET, RELEASE_ID, fake)
    return rc, capsys.readouterr().out


def _errors(out):
    return [line for line in out.splitlines() if line.startswith("::error::")]


# --- Empty prefix -------------------------------------------------------------


@pytest.mark.parametrize("stdout", [_listing(), "", "  \n", _listing(KeyCount=0)])
def test_empty_prefix_passes(capsys, stdout):
    rc, out = _run(FakeAws(stdout), capsys)
    assert rc == 0
    assert _errors(out) == []
    assert f"Release prefix check passed: {PREFIX} is empty." in out


# --- Existing prefix ----------------------------------------------------------


@pytest.mark.parametrize(
    "key",
    [
        f"{PREFIX}manifest.json",  # complete-looking release
        f"{PREFIX}districts/tyler/smith.kmz",  # partial upload: no manifest.json
        f"{PREFIX}offline/abilene.zip",
    ],
)
def test_any_existing_object_fails(capsys, key):
    rc, out = _run(FakeAws(_listing(key)), capsys)
    assert rc == 1
    errors = " ".join(_errors(out))
    assert PREFIX in errors
    assert key in errors
    assert "immutable" in errors
    assert "new release ID" in errors
    assert "passed" not in out


def test_next_token_without_contents_still_counts_as_existing(capsys):
    rc, _ = _run(FakeAws(_listing(NextToken="abc")), capsys)
    assert rc == 1


# --- Fail closed --------------------------------------------------------------


def test_aws_failure_fails_closed(capsys):
    exc = subprocess.CalledProcessError(
        254, ["aws"], stderr="An error occurred (AccessDenied) when calling ListObjectsV2"
    )
    rc, out = _run(FakeAws(exc=exc), capsys)
    assert rc == 1
    errors = " ".join(_errors(out))
    assert "AccessDenied" in errors
    assert "Could not confirm the release prefix is empty" in errors
    assert "passed" not in out


def test_missing_aws_cli_fails_closed(capsys):
    rc, out = _run(FakeAws(exc=FileNotFoundError("aws")), capsys)
    assert rc == 1
    assert "could not run the aws CLI" in " ".join(_errors(out))


@pytest.mark.parametrize(
    "stdout",
    [
        "not json",
        "[]",
        json.dumps({"Contents": "oops"}),
        json.dumps({"Contents": None}),
    ],
)
def test_malformed_response_fails_closed(capsys, stdout):
    rc, out = _run(FakeAws(stdout), capsys)
    assert rc == 1
    assert _errors(out)
    assert "passed" not in out


# --- Query shape --------------------------------------------------------------


def test_queries_one_key_under_the_slash_terminated_prefix(capsys):
    fake = FakeAws(_listing())
    _run(fake, capsys)
    assert fake.calls == [
        [
            "s3api",
            "list-objects-v2",
            "--bucket",
            BUCKET,
            "--prefix",
            PREFIX,
            "--page-size",
            "1",
            "--max-items",
            "1",
            "--output",
            "json",
        ]
    ]
    # The trailing slash keeps ...-57cd153 from matching ...-57cd1534/.
    assert fake.calls[0][fake.calls[0].index("--prefix") + 1].endswith(f"{RELEASE_ID}/")


def test_release_prefix_always_ends_with_slash():
    assert check_prefix.release_prefix("2026-09-28T1412Z-57cd153") == (
        "releases/2026-09-28T1412Z-57cd153/"
    )


# --- Real subprocess path, fake aws on PATH ------------------------------------


def _fake_aws_on_path(tmp_path, *, stdout, returncode, stderr=""):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    argv_log = tmp_path / "argv.json"
    script = bin_dir / "aws"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        f"open({str(argv_log)!r}, 'w').write(json.dumps(sys.argv[1:]))\n"
        f"sys.stdout.write({stdout!r})\n"
        f"sys.stderr.write({stderr!r})\n"
        f"sys.exit({returncode})\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    return env, argv_log


def _run_script(env):
    return subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts/release/check_prefix.py"),
            "--bucket",
            BUCKET,
            "--release-id",
            RELEASE_ID,
            "--endpoint-url",
            ENDPOINT,
        ],
        capture_output=True,
        text=True,
        env=env,
    )


def test_script_passes_bucket_and_endpoint_to_aws(tmp_path):
    env, argv_log = _fake_aws_on_path(tmp_path, stdout=_listing(), returncode=0)
    result = _run_script(env)
    assert result.returncode == 0, result.stdout
    argv = json.loads(argv_log.read_text())
    assert argv[argv.index("--bucket") + 1] == BUCKET
    assert argv[argv.index("--prefix") + 1] == PREFIX
    assert argv[-2:] == ["--endpoint-url", ENDPOINT]


def test_script_fails_closed_on_nonzero_aws_exit(tmp_path):
    env, _ = _fake_aws_on_path(
        tmp_path,
        stdout="",
        returncode=255,
        stderr="Could not connect to the endpoint URL",
    )
    result = _run_script(env)
    assert result.returncode == 1
    assert "Could not connect to the endpoint URL" in result.stdout


# --- Write-once verification record (--verification-record) --------------------

RECORD_KEY = f"verified/{RELEASE_ID}.json"


def _run_record(fake, capsys):
    rc = check_prefix.check_prefix(BUCKET, RELEASE_ID, fake, verification_record=True)
    return rc, capsys.readouterr().out


def test_record_check_queries_exactly_the_record_key(capsys):
    fake = FakeAws(_listing())
    rc, out = _run_record(fake, capsys)
    assert rc == 0
    assert f"Verification record check passed: {RECORD_KEY} does not exist." in out
    (args,) = fake.calls
    assert args[args.index("--prefix") + 1] == RECORD_KEY
    assert args[args.index("--max-items") + 1] == "1"
    # Never the release prefix.
    assert not any(a.startswith("releases/") for a in args)


def test_existing_record_is_never_overwritten(capsys):
    rc, out = _run_record(FakeAws(_listing(RECORD_KEY)), capsys)
    assert rc == 1
    errors = " ".join(_errors(out))
    assert RECORD_KEY in errors
    assert "write-once" in errors
    assert "passed" not in out


def test_record_check_fails_closed_on_aws_error(capsys):
    exc = subprocess.CalledProcessError(254, ["aws"], stderr="AccessDenied")
    rc, out = _run_record(FakeAws(exc=exc), capsys)
    assert rc == 1
    assert "Could not confirm no verification record exists" in " ".join(_errors(out))


def test_record_check_fails_closed_on_malformed_response(capsys):
    rc, _ = _run_record(FakeAws("not json"), capsys)
    assert rc == 1


def test_script_record_mode_passes_flag_through(tmp_path):
    env, argv_log = _fake_aws_on_path(tmp_path, stdout=_listing(), returncode=0)
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts/release/check_prefix.py"),
            "--verification-record",
            "--bucket",
            BUCKET,
            "--release-id",
            RELEASE_ID,
            "--endpoint-url",
            ENDPOINT,
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stdout
    argv = json.loads(argv_log.read_text())
    assert argv[argv.index("--prefix") + 1] == RECORD_KEY
