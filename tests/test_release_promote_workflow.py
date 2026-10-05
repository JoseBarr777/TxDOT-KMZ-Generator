"""release-promote.yml wiring: manual confirmed input, a reusable
workflow_call path for automatic promotion (--require-newer), every candidate
check (scripts/release/promote_check.py) before the one current.json write,
and a read-back after it.

Structural checks on the workflow file; nothing is executed against R2. The
candidate-check step's shell is run once against a stub python3 to prove when
--require-newer is passed.
"""

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github/workflows/release-promote.yml"


def _workflow():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _steps():
    return _workflow()["jobs"]["promote"]["steps"]


def _index(steps, *, name=None, run=None, uses=None):
    matches = [
        i
        for i, s in enumerate(steps)
        if (name is None or s.get("name") == name)
        and (run is None or run in s.get("run", ""))
        and (uses is None or s.get("uses", "").startswith(uses))
    ]
    assert len(matches) == 1, (name, run, uses, matches)
    return matches[0]


def _current_json_writes(steps):
    return [
        i
        for i, s in enumerate(steps)
        if "aws s3 cp" in s.get("run", "") and '"s3://${CF_R2_BUCKET}/current.json"' in s["run"]
    ]


def _triggers():
    workflow = _workflow()
    return workflow.get("on", workflow.get(True))


def test_promotion_is_manual_or_reusable_only():
    assert list(_triggers()) == ["workflow_dispatch", "workflow_call"]


def test_manual_promotion_requires_confirmation_and_cannot_require_newer():
    inputs = _triggers()["workflow_dispatch"]["inputs"]
    # No require_newer here: a manual dispatch is always rollback-capable.
    assert set(inputs) == {"release_id", "confirm_release_id"}
    assert inputs["release_id"]["required"] and inputs["confirm_release_id"]["required"]
    steps = _steps()
    validate = steps[_index(steps, name="Validate release_id input")]
    assert '"${RELEASE_ID}" != "${CONFIRM_RELEASE_ID}"' in validate["run"]
    # Inputs reach the script only through env, never ${{ }} in run:.
    assert all("${{" not in s.get("run", "") for s in steps)


def test_reusable_promotion_inputs_default_to_require_newer():
    inputs = _triggers()["workflow_call"]["inputs"]
    assert set(inputs) == {"release_id", "confirm_release_id", "require_newer"}
    for name in ("release_id", "confirm_release_id"):
        assert inputs[name] == {**inputs[name], "required": True, "type": "string"}
    # A caller that omits it gets the strict (automatic) mode, not rollback.
    assert inputs["require_newer"]["type"] == "boolean"
    assert inputs["require_newer"]["required"] is False
    assert inputs["require_newer"]["default"] is True


def test_both_triggers_run_the_same_single_job():
    assert list(_workflow()["jobs"]) == ["promote"]


def test_manual_and_reusable_promotion_share_one_job_level_concurrency_group():
    # Job-level so a workflow_call run (inside its caller's run) and a manual
    # dispatch serialize on the same group.
    assert "concurrency" not in _workflow()
    assert _workflow()["jobs"]["promote"]["concurrency"] == {
        "group": "txdot-kmz-promote",
        "cancel-in-progress": False,
    }


def test_mode_comes_from_the_input_never_from_the_triggering_event():
    text = WORKFLOW.read_text(encoding="utf-8")
    steps = _steps()
    check = steps[_index(steps, run="scripts/release/promote_check.py")]
    assert check["env"]["REQUIRE_NEWER"] == "${{ inputs.require_newer }}"
    for step in steps:
        assert "event_name" not in str(step)
    assert "github.event_name" not in text.split("\non:", 1)[1]


def _run_candidate_check(tmp_path, require_newer):
    """Run the candidate-check step's shell with python3 stubbed to record argv."""
    steps = _steps()
    check = steps[_index(steps, run="scripts/release/promote_check.py")]
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    argv_file = tmp_path / "argv"
    stub = stub_dir / "python3"
    stub.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{argv_file}"\n')
    stub.chmod(0o755)
    env = {
        "PATH": f"{stub_dir}:/usr/bin:/bin",
        "CF_R2_BUCKET": "bucket",
        "CF_ACCOUNT_ID": "acct",
        "RELEASE_ID": "2026-09-29T1412Z-57cd153",
        "REQUIRE_NEWER": require_newer,
        "GITHUB_OUTPUT": str(tmp_path / "out"),
    }
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", check["run"]],
        env=env,
        capture_output=True,
        text=True,
    )
    argv = argv_file.read_text().splitlines() if argv_file.exists() else None
    return result, argv


@pytest.mark.parametrize(
    ("require_newer", "flagged"),
    [("true", True), ("false", False), ("", False)],  # "" = workflow_dispatch
)
def test_require_newer_is_passed_only_when_requested(tmp_path, require_newer, flagged):
    result, argv = _run_candidate_check(tmp_path, require_newer)
    assert result.returncode == 0, result.stderr
    assert argv[0] == "scripts/release/promote_check.py"
    assert ("--require-newer" in argv) is flagged
    # Every pre-existing argument is still passed.
    assert argv[argv.index("--release-id") + 1] == "2026-09-29T1412Z-57cd153"
    assert argv[argv.index("--bucket") + 1] == "bucket"
    assert argv[argv.index("--github-output") + 1] == str(tmp_path / "out")
    assert "" not in argv  # an absent flag leaves no empty argument behind


def test_unexpected_require_newer_value_fails_closed(tmp_path):
    result, argv = _run_candidate_check(tmp_path, "yes")
    assert result.returncode == 1
    assert argv is None  # promote_check never ran
    assert "unexpected require_newer value 'yes'" in result.stdout


def test_repository_is_checked_out_first_with_read_only_access():
    steps = _steps()
    assert _index(steps, uses="actions/checkout") == 0
    assert _workflow()["permissions"] == {"contents": "read"}


def test_candidate_check_runs_the_release_tooling():
    steps = _steps()
    check = steps[_index(steps, run="scripts/release/promote_check.py")]
    assert check["id"] == "validate_release"
    assert check["env"]["RELEASE_ID"] == "${{ steps.validate_inputs.outputs.release_id }}"
    assert '--github-output "${GITHUB_OUTPUT}"' in check["run"]
    # promote_check reuses the gate and the shared record rules in-process.
    source = (REPO_ROOT / "scripts/release/promote_check.py").read_text(encoding="utf-8")
    assert "gate.gate_failures(manifest)" in source
    assert "record_verification.validate_record(" in source
    assert "hashlib.sha256(manifest_bytes)" in source


def test_no_legacy_prefix_fallback_remains():
    assert "releases/test-" not in "".join(s.get("run", "") for s in _steps())
    source = (REPO_ROOT / "scripts/release/promote_check.py").read_text(encoding="utf-8")
    assert 'f"releases/test-' not in source


def test_every_check_precedes_the_single_current_json_write_and_read_back_follows():
    steps = _steps()
    writes = _current_json_writes(steps)
    assert len(writes) == 1
    write = writes[0]
    for name in (
        "Validate release_id input",
        "R2 preflight (bucket name + access)",
        "Check promotion candidate",
        "Construct and validate current.json locally",
    ):
        assert _index(steps, name=name) < write
    assert _index(steps, name="Read-back verify current.json") == write + 1


def test_pointer_is_built_from_the_checked_candidate():
    steps = _steps()
    for name in (
        "Construct and validate current.json locally",
        "Read-back verify current.json",
        "Print promotion summary",
    ):
        env = steps[_index(steps, name=name)]["env"]
        assert env["RELEASE_ID"] == "${{ steps.validate_release.outputs.release_id }}"
        assert env["GIT_SHA_SHORT"] == "${{ steps.validate_release.outputs.git_sha_short }}"
        assert env["RESOLVED_PREFIX"] == "${{ steps.validate_release.outputs.release_prefix }}"


def test_no_step_can_proceed_past_a_failure():
    steps = _steps()
    assert [s["name"] for s in steps if "continue-on-error" in s or "if" in s] == []


def test_only_current_json_is_ever_written():
    steps = _steps()
    runs = "".join(s.get("run", "") for s in steps)
    for mutating in ("aws s3 sync", "put-object", "delete-object", "aws s3 rm", "aws s3 mv"):
        assert mutating not in runs
    # The one shell-level `aws s3 cp` is the current.json write (the read-back
    # downloads via subprocess in Python).
    assert runs.count("aws s3 cp") == 1
    assert len(_current_json_writes(steps)) == 1


def test_promote_check_runs_standalone_outside_pytest_path():
    # The workflow runs it with bare python3; its sibling imports must resolve.
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts/release/promote_check.py"), "--help"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr
