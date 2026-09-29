"""Behavior of scripts/release/package.py, the manifest-driven release allowlist."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from release import package

REPO_ROOT = Path(__file__).resolve().parents[1]


def _source(tmp_path, artifacts, files):
    """Build a synthetic data/output/: manifest.json + the given files."""
    source = tmp_path / "output"
    source.mkdir()
    (source / "manifest.json").write_text(
        json.dumps({"artifacts": [{"path": p} for p in artifacts]}), encoding="utf-8"
    )
    for rel, content in files.items():
        path = source / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return source


def _tree(root):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


def _run(source, stage):
    return package.main(["--source-dir", str(source), "--stage-dir", str(stage)])


def test_only_manifest_and_declared_artifacts_are_staged(tmp_path, capsys):
    source = _source(
        tmp_path,
        ["expected-artifact.kmz", "districts/tyler.kml"],
        {
            "expected-artifact.kmz": b"kmz",
            "districts/tyler.kml": b"kml",
            "unrelated-file.txt": b"junk",
            ".gitkeep": b"",
            ".DS_Store": b"x",
            "districts/debug.json": b"{}",
        },
    )
    stage = tmp_path / "stage"
    assert _run(source, stage) == 0

    assert _tree(stage) == ["districts/tyler.kml", "expected-artifact.kmz", "manifest.json"]
    assert (stage / "expected-artifact.kmz").read_bytes() == b"kmz"
    assert (stage / "manifest.json").read_bytes() == (source / "manifest.json").read_bytes()

    out = capsys.readouterr().out
    assert "  manifest artifacts:  2" in out
    assert "  staged artifacts:    2" in out
    assert "  total staged files:  3" in out
    assert (
        f"Packaged {stage}/: manifest.json + 2 manifest-declared artifact(s), nothing else." in out
    )


def test_stale_stage_tree_is_replaced(tmp_path):
    source = _source(tmp_path, ["a.kmz"], {"a.kmz": b"a"})
    stage = tmp_path / "stage"
    (stage / "old").mkdir(parents=True)
    (stage / "old" / "leftover.kmz").write_bytes(b"stale")

    assert _run(source, stage) == 0
    assert _tree(stage) == ["a.kmz", "manifest.json"]


def test_missing_manifest_fails(tmp_path, capsys):
    source = tmp_path / "output"
    source.mkdir()
    stage = tmp_path / "stage"
    assert _run(source, stage) == 1
    assert f"::error::{source / 'manifest.json'} not found -- nothing to package" in (
        capsys.readouterr().out
    )
    assert not stage.exists()


@pytest.mark.parametrize(
    ("declared", "reason"),
    [
        (["a.kmz", "a.kmz"], "manifest declares duplicate path: a.kmz"),
        (["/etc/passwd"], "manifest declares a non-relative or escaping path: /etc/passwd"),
        (["../escape.kmz"], "manifest declares a non-relative or escaping path: ../escape.kmz"),
        (["x/../../y.kmz"], "manifest declares a non-relative or escaping path: x/../../y.kmz"),
        (
            ["manifest.json"],
            "manifest declares manifest.json as an artifact; it is staged separately",
        ),
    ],
)
def test_incoherent_manifest_rejected_before_touching_stage(tmp_path, capsys, declared, reason):
    source = _source(tmp_path, declared, {"a.kmz": b"a"})
    stage = tmp_path / "stage"
    stage.mkdir()
    (stage / "previous.kmz").write_bytes(b"prev")

    assert _run(source, stage) == 1
    assert f"::error::Packaging failed: {reason}" in capsys.readouterr().out
    # Validation happens before the stage dir is wiped or written.
    assert _tree(stage) == ["previous.kmz"]


def test_missing_declared_artifact_fails_without_staging_manifest(tmp_path, capsys):
    source = _source(tmp_path, ["a.kmz", "gone.kmz"], {"a.kmz": b"a"})
    stage = tmp_path / "stage"
    assert _run(source, stage) == 1
    out = capsys.readouterr().out
    assert (
        f"::error::Packaging failed: manifest-declared artifact missing from {source}: gone.kmz"
        in out
    )
    assert "manifest.json" not in _tree(stage)


def test_missing_artifact_report_is_capped_at_ten(tmp_path, capsys):
    declared = [f"c{i:02d}.kmz" for i in range(13)]
    source = _source(tmp_path, declared, {})
    assert _run(source, tmp_path / "stage") == 1
    out = capsys.readouterr().out
    assert out.count("manifest-declared artifact missing from") == 10
    assert "::error::Packaging failed: ...and 3 more missing artifact(s)" in out


def test_distinct_paths_resolving_to_one_file_fail_contract_check(tmp_path, capsys):
    # "a/b.kmz" and "a/./b.kmz" are distinct strings (not duplicates) but
    # stage to the same file, so the staged tree comes up one short.
    source = _source(tmp_path, ["a/b.kmz", "a/./b.kmz"], {"a/b.kmz": b"b"})
    assert _run(source, tmp_path / "stage") == 1
    out = capsys.readouterr().out
    assert "  total staged files:  2" in out
    assert (
        "::error::Packaging failed: staged tree does not match the manifest contract "
        "(expected 2 artifacts + manifest.json = 3 files)"
    ) in out


def test_runs_as_standalone_script(tmp_path):
    source = _source(tmp_path, ["a.kmz"], {"a.kmz": b"a", "unrelated-file.txt": b"x"})
    stage = tmp_path / "stage"
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts/release/package.py"),
            "--source-dir",
            str(source),
            "--stage-dir",
            str(stage),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout
    assert _tree(stage) == ["a.kmz", "manifest.json"]
