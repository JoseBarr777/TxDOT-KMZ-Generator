"""release-staging.yml runs the release pipeline's commands in order, a
failing guard step (cold GIS cache, package validation, prefix check,
verification) stops everything after it, the verified-candidate record is
written only after verification, and the production source-freshness
assumptions hold.

Structural checks on the workflow file; the only thing executed is the
cold-cache step's own shell script, against temporary directories.
"""

import subprocess
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/release-staging.yml"

# Each pipeline stage's step, identified by a substring of what it runs, or
# by exact step name with a "name:" prefix where the command is shared.
COLD_CACHE_CHECK = "find data/cache"
RELEASE_PREFIX_CHECK = "name:Check release prefix is unused"
RECORD_CREATE = "scripts/release/record_verification.py"
RECORD_CHECK = "check_prefix.py --verification-record"
RECORD_UPLOAD = "name:Upload verification record"

PIPELINE = [
    COLD_CACHE_CHECK,  # Assert cold GIS source cache
    "txdot_overlay build-all",
    "txdot_overlay validate-output",
    "txdot_overlay validate-offline-packages",
    "txdot_overlay generate-manifest",
    "scripts/release/gate.py",
    "scripts/release/package.py",
    "git rev-parse --short HEAD",  # Compute release ID
    RELEASE_PREFIX_CHECK,
    "aws s3 sync release-stage/",
    "scripts/release/verify.py",
    RECORD_CREATE,
    RECORD_CHECK,
    RECORD_UPLOAD,
]


def _steps():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return workflow["jobs"]["release"]["steps"]


def _step_index(steps, needle):
    if needle.startswith("name:"):
        matches = [i for i, step in enumerate(steps) if step.get("name") == needle[5:]]
    else:
        matches = [i for i, step in enumerate(steps) if needle in step.get("run", "")]
    assert len(matches) == 1, f"expected exactly one step matching {needle!r}, found {matches}"
    return matches[0]


def test_pipeline_stages_run_in_order():
    steps = _steps()
    indices = [_step_index(steps, needle) for needle in PIPELINE]
    assert indices == sorted(indices), dict(zip(PIPELINE, indices))


@pytest.mark.parametrize(
    "needle",
    [
        COLD_CACHE_CHECK,
        "txdot_overlay validate-offline-packages",
        RELEASE_PREFIX_CHECK,
        "scripts/release/verify.py",
        RECORD_CREATE,
        RECORD_CHECK,
        RECORD_UPLOAD,
    ],
)
def test_guard_step_failure_stops_the_release(needle):
    steps = _steps()
    i = _step_index(steps, needle)
    # A plain failing step fails the job; later steps then run only if they
    # opt in with an `if:` (e.g. always()), and this step's own failure is
    # only tolerated with continue-on-error.
    assert "continue-on-error" not in steps[i]
    assert "if" not in steps[i]
    assert [s["name"] for s in steps[i + 1 :] if "if" in s] == []


def test_prefix_check_runs_immediately_before_upload():
    steps = _steps()
    check = _step_index(steps, RELEASE_PREFIX_CHECK)
    upload = _step_index(steps, "aws s3 sync release-stage/")
    assert upload == check + 1
    # Same R2 target configuration as the upload it guards.
    for key in ("CF_R2_BUCKET", "CF_ACCOUNT_ID", "RELEASE_ID", "AWS_ACCESS_KEY_ID"):
        assert steps[check]["env"][key] == steps[upload]["env"][key]


# --- Verified-candidate record (Step 17) ---------------------------------------
#
# verified/<release_id>.json is durable proof that releases/<release_id>/
# passed remote verification, so it must never be written unless verify.py
# succeeded, and must never be overwritten.


def test_verification_record_steps_directly_follow_verification():
    steps = _steps()
    verify = _step_index(steps, "scripts/release/verify.py")
    assert [
        _step_index(steps, RECORD_CREATE),
        _step_index(steps, RECORD_CHECK),
        _step_index(steps, RECORD_UPLOAD),
    ] == [verify + 1, verify + 2, verify + 3]
    # Nothing else runs after the record is written.
    assert _step_index(steps, RECORD_UPLOAD) == len(steps) - 1


def test_record_hashes_the_manifest_that_verification_checked():
    steps = _steps()
    verify_run = steps[_step_index(steps, "scripts/release/verify.py")]["run"]
    create_run = steps[_step_index(steps, RECORD_CREATE)]["run"]
    assert "--stage-dir release-stage" in verify_run
    assert "--manifest release-stage/manifest.json" in create_run
    assert '--release-id "${RELEASE_ID}"' in create_run
    assert '--git-sha "${GITHUB_SHA}"' in create_run  # full commit SHA


def test_record_is_uploaded_once_under_verified_as_json():
    steps = _steps()
    upload_run = steps[_step_index(steps, RECORD_UPLOAD)]["run"]
    assert upload_run.count("aws s3 cp") == 1
    assert '"s3://${CF_R2_BUCKET}/verified/${RELEASE_ID}.json"' in upload_run
    assert "releases/" not in upload_run
    assert '--content-type "application/json"' in upload_run
    # The existence check guards exactly the key being written, in the same bucket.
    check, upload = _step_index(steps, RECORD_CHECK), _step_index(steps, RECORD_UPLOAD)
    for key in ("CF_R2_BUCKET", "CF_ACCOUNT_ID", "RELEASE_ID", "AWS_ACCESS_KEY_ID"):
        assert steps[check]["env"][key] == steps[upload]["env"][key]


def test_nothing_but_the_record_upload_writes_outside_the_release_upload():
    # The release prefix is written only by the four sync passes; the record is
    # the only other object staging writes.
    writers = [
        s["name"]
        for s in _steps()
        if "aws s3 cp" in s.get("run", "") or "aws s3 sync" in s.get("run", "")
    ]
    assert writers == ["Upload release to R2 (staging)", "Upload verification record"]


# --- Production source freshness (Step 14) -----------------------------------
#
# Staging must fetch all GIS source data during the run. That relies on a
# fresh GitHub-hosted runner with nothing restored into data/cache, and on
# no --force-refresh (which, on post-build commands, would re-fetch
# districts/counties and split the release across two source snapshots).


def test_cold_cache_check_runs_immediately_before_build():
    steps = _steps()
    assert _step_index(steps, "txdot_overlay build-all") == (
        _step_index(steps, COLD_CACHE_CHECK) + 1
    )


def test_no_step_forces_a_source_refresh():
    offenders = [s.get("name") for s in _steps() if "--force-refresh" in s.get("run", "")]
    assert offenders == []


def test_nothing_restores_the_gis_cache():
    for step in _steps():
        uses = step.get("uses", "")
        assert not uses.startswith(("actions/cache", "actions/download-artifact")), step
        assert "data/cache" not in str(step.get("with", {})), step


def test_staging_runs_on_a_github_hosted_ubuntu_runner():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    runs_on = workflow["jobs"]["release"]["runs-on"]
    # A plain label, not a list/group that could select a self-hosted
    # (persistent-workspace) runner.
    assert isinstance(runs_on, str)
    assert runs_on.startswith("ubuntu-")
    assert "self-hosted" not in runs_on


def _run_cold_cache_check(workdir):
    steps = _steps()
    script = steps[_step_index(steps, COLD_CACHE_CHECK)]["run"]
    return subprocess.run(
        ["bash", "-c", script], cwd=workdir, capture_output=True, text=True, check=False
    )


def test_cold_cache_check_passes_with_only_the_placeholder(tmp_path):
    (tmp_path / "data/cache").mkdir(parents=True)
    (tmp_path / "data/cache/.gitkeep").write_text("")
    result = _run_cold_cache_check(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "leftover",
    [
        "districts__1=1__*_0123456789abcdef01234567.json",
        "roadways__CO = 1__*_0123456789abcdef01234567.json",
        "nested/anything.json",
    ],
)
def test_cold_cache_check_fails_on_any_cached_file(tmp_path, leftover):
    cache = tmp_path / "data/cache"
    cache.mkdir(parents=True)
    (cache / ".gitkeep").write_text("")
    (cache / leftover).parent.mkdir(parents=True, exist_ok=True)
    (cache / leftover).write_text("{}")
    result = _run_cold_cache_check(tmp_path)
    assert result.returncode == 1
    assert "::error::data/cache is not empty" in result.stdout
    # Fails visibly; never deletes the evidence.
    assert (cache / leftover).exists()


def test_cold_cache_check_fails_when_cache_dir_is_missing(tmp_path):
    result = _run_cold_cache_check(tmp_path)
    assert result.returncode == 1
    assert "::error::data/cache is missing" in result.stdout
