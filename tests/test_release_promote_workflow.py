"""release-promote.yml wiring: manual confirmed input, every candidate check
(scripts/release/promote_check.py) before the one current.json write, and a
read-back after it.

Structural checks on the workflow file; nothing is executed against R2.
"""

import subprocess
import sys
from pathlib import Path

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


def test_promotion_is_manual_with_confirmation():
    workflow = _workflow()
    trigger = workflow.get("on", workflow.get(True))
    assert list(trigger) == ["workflow_dispatch"]
    inputs = trigger["workflow_dispatch"]["inputs"]
    assert inputs["release_id"]["required"] and inputs["confirm_release_id"]["required"]
    steps = _steps()
    validate = steps[_index(steps, name="Validate release_id input")]
    assert '"${RELEASE_ID}" != "${CONFIRM_RELEASE_ID}"' in validate["run"]
    # Inputs reach the script only through env, never ${{ }} in run:.
    assert all("${{" not in s.get("run", "") for s in steps)


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
