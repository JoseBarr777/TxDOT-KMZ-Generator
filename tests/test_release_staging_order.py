"""release-staging.yml runs the release pipeline's commands in order, and a
failing validation step stops everything after it.

Structural checks on the workflow file only; nothing is executed.
"""

from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/release-staging.yml"

# Substrings identifying each pipeline stage's step by what it runs.
PIPELINE = [
    "txdot_overlay build-all",
    "txdot_overlay validate-output",
    "txdot_overlay validate-offline-packages",
    "txdot_overlay generate-manifest",
    "scripts/release/gate.py",
    "scripts/release/package.py",
    "aws s3 sync release-stage/",
    "scripts/release/verify.py",
]


def _steps():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return workflow["jobs"]["release"]["steps"]


def _step_index(steps, needle):
    matches = [i for i, step in enumerate(steps) if needle in step.get("run", "")]
    assert len(matches) == 1, f"expected exactly one step running {needle!r}, found {matches}"
    return matches[0]


def test_pipeline_stages_run_in_order():
    steps = _steps()
    indices = [_step_index(steps, needle) for needle in PIPELINE]
    assert indices == sorted(indices), dict(zip(PIPELINE, indices))


def test_offline_package_validation_failure_stops_the_release():
    steps = _steps()
    i = _step_index(steps, "txdot_overlay validate-offline-packages")
    # A plain failing step fails the job; later steps then run only if they
    # opt in with an `if:` (e.g. always()), and this step's own failure is
    # only tolerated with continue-on-error.
    assert "continue-on-error" not in steps[i]
    assert "if" not in steps[i]
    assert [s["name"] for s in steps[i + 1 :] if "if" in s] == []
