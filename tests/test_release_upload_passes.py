"""The staging workflow's R2 upload passes partition release-stage/ by extension.

Reads the `aws s3 sync` commands straight out of release-staging.yml and
applies the aws CLI's --exclude/--include semantics (every file starts
included; filters are applied in order and the last matching one wins;
patterns are matched against the path relative to the source directory,
where `*` also matches `/`). Nothing is uploaded.
"""

import shlex
from fnmatch import fnmatchcase
from pathlib import Path

import pytest
import yaml

from release import verify

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/release-staging.yml"
IMMUTABLE = "public, max-age=31536000, immutable"

# One of each kind of file package.py stages, using real Manifest 2.1 path shapes.
STAGED_FILES = {
    "master.kml": verify.KML_CONTENT_TYPE,
    "districts/tyler.kml": verify.KML_CONTENT_TYPE,
    "counties/anderson.kmz": verify.KMZ_CONTENT_TYPE,
    "boundaries/county_boundaries.kmz": verify.KMZ_CONTENT_TYPE,
    "offline/tyler.zip": verify.ZIP_CONTENT_TYPE,
    "offline/texas_statewide.zip": verify.ZIP_CONTENT_TYPE,
    # Catch-all: no explicit --content-type; the aws CLI infers it.
    "manifest.json": None,
    "some-future-artifact.txt": None,
}


def _sync_commands():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["release"]["steps"]
    (upload,) = [s for s in steps if s["name"] == "Upload release to R2 (staging)"]
    script = upload["run"].replace("\\\n", " ")
    commands = []
    for line in script.splitlines():
        tokens = shlex.split(line, comments=True)
        if tokens[:3] == ["aws", "s3", "sync"]:
            commands.append(tokens)
    return commands


def _option(tokens, name):
    return tokens[tokens.index(name) + 1] if name in tokens else None


def _selects(tokens, rel):
    included = True
    for flag, pattern in zip(tokens, tokens[1:]):
        if flag in ("--exclude", "--include") and fnmatchcase(rel, pattern):
            included = flag == "--include"
    return included


def test_four_passes_all_from_release_stage_with_immutable_cache_control():
    commands = _sync_commands()
    assert len(commands) == 4
    for tokens in commands:
        assert tokens[3:5] == ["release-stage/", "${dest}"]
        assert _option(tokens, "--cache-control") == IMMUTABLE


@pytest.mark.parametrize(("rel", "expected_content_type"), STAGED_FILES.items())
def test_each_staged_file_is_uploaded_by_exactly_one_pass(rel, expected_content_type):
    passes = [tokens for tokens in _sync_commands() if _selects(tokens, rel)]
    assert len(passes) == 1, f"{rel} selected by {len(passes)} passes"
    # The explicit type set on upload is the one verify.py expects remotely.
    assert _option(passes[0], "--content-type") == expected_content_type
