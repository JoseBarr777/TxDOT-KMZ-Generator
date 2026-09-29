"""Behavior of scripts/release/verify.py, post-upload staged-release verification.

R2 is replaced by an in-memory fake that answers the three aws CLI calls the
verifier makes (list-objects-v2, s3 cp, head-object). No network.
"""

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from release import verify

BUCKET = "test-bucket"
RELEASE_ID = "2026-09-28T1200Z-abc1234"
PREFIX = f"releases/{RELEASE_ID}/"

CONTENT_TYPES = {
    ".kml": "application/vnd.google-earth.kml+xml",
    ".kmz": "application/vnd.google-earth.kmz",
    ".json": "application/json",
    ".zip": "application/zip",
}


class FakeR2:
    """Stand-in for `aws ... --endpoint-url <r2>`; objects keyed by full S3 key."""

    def __init__(self, objects=None, truncated=False):
        self.objects = dict(objects or {})  # key -> (bytes, content_type)
        self.truncated = truncated
        self.calls = []

    @classmethod
    def mirror(cls, stage_dir):
        """A bucket holding exactly what the upload step would have put there."""
        objects = {}
        for p in stage_dir.rglob("*"):
            if p.is_file():
                rel = p.relative_to(stage_dir).as_posix()
                objects[PREFIX + rel] = (p.read_bytes(), CONTENT_TYPES.get(p.suffix))
        return cls(objects)

    def __call__(self, args):
        self.calls.append(args)
        if args[:2] == ["s3api", "list-objects-v2"]:
            prefix = args[args.index("--prefix") + 1]
            contents = [
                {"Key": k, "Size": len(body)}
                for k, (body, _) in sorted(self.objects.items())
                if k.startswith(prefix)
            ]
            listing = {"IsTruncated": self.truncated}
            if contents:
                listing["Contents"] = contents
            return json.dumps(listing)
        if args[:2] == ["s3", "cp"]:
            key = args[2].removeprefix(f"s3://{BUCKET}/")
            if key not in self.objects:
                raise subprocess.CalledProcessError(1, ["aws", *args])
            Path(args[3]).write_bytes(self.objects[key][0])
            return ""
        if args[:2] == ["s3api", "head-object"]:
            key = args[args.index("--key") + 1]
            if key not in self.objects:
                raise subprocess.CalledProcessError(254, ["aws", *args])
            body, content_type = self.objects[key]
            head = {"ContentLength": len(body)}
            if content_type is not None:
                head["ContentType"] = content_type
            return json.dumps(head)
        raise AssertionError(f"unexpected aws call: {args}")


def _artifact(stage, rel, type_, body):
    path = stage / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return {
        "type": type_,
        "path": rel,
        "size_bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }


@pytest.fixture
def stage(tmp_path):
    """A synthetic release-stage/ tree as package.py would produce it."""
    stage = tmp_path / "release-stage"
    stage.mkdir()
    artifacts = [
        _artifact(stage, "master.kml", "master_kml", b"<kml>master</kml>"),
        _artifact(stage, "districts/tyler.kml", "district_kml", b"<kml>tyler</kml>"),
        _artifact(stage, "counties/anderson.kmz", "county_kmz", b"PK-anderson"),
        _artifact(stage, "counties/smith.kmz", "county_kmz", b"PK-smith-longer"),
    ]
    (stage / "manifest.json").write_text(json.dumps({"artifacts": artifacts}), encoding="utf-8")
    return stage


def _verify(stage, r2):
    return verify.verify(stage, BUCKET, RELEASE_ID, r2)


def _errors(out):
    return [line for line in out.splitlines() if line.startswith("::error::")]


def test_faithful_upload_passes(stage, capsys):
    r2 = FakeR2.mirror(stage)
    assert _verify(stage, r2) == 0
    out = capsys.readouterr().out
    assert _errors(out) == []
    assert f"  prefix:              {PREFIX}" in out
    assert "  local file count:    5" in out
    assert "  manifest artifacts:  4" in out
    assert "  remote object count: 5" in out
    assert "  size mismatches:     0" in out
    assert "  hash check manifest.json: OK" in out
    assert "  hash check master.kml: OK" in out
    # The representative county is the first county_kmz in manifest order.
    assert "  hash check counties/anderson.kmz: OK" in out
    assert "counties/smith.kmz" not in out
    assert "Verification passed: staged release is complete and consistent." in out


def test_only_the_expected_prefix_is_read(stage):
    r2 = FakeR2.mirror(stage)
    _verify(stage, r2)
    listing = r2.calls[0]
    assert listing == [
        "s3api",
        "list-objects-v2",
        "--bucket",
        BUCKET,
        "--prefix",
        PREFIX,
        "--output",
        "json",
    ]
    assert [c[2] for c in r2.calls if c[:2] == ["s3", "cp"]] == [
        f"s3://{BUCKET}/{PREFIX}manifest.json",
        f"s3://{BUCKET}/{PREFIX}master.kml",
        f"s3://{BUCKET}/{PREFIX}counties/anderson.kmz",
    ]


def test_extra_remote_object_fails_count_checks(stage, capsys):
    r2 = FakeR2.mirror(stage)
    r2.objects[PREFIX + ".gitkeep"] = (b"", None)
    assert _verify(stage, r2) == 1
    errors = _errors(capsys.readouterr().out)
    assert "::error::Verification failed: remote object count 6 != local file count 5" in errors
    assert (
        "::error::Verification failed: remote object count 6 != expected 5 "
        "(manifest artifacts + manifest.json)"
    ) in errors


def test_objects_outside_the_prefix_are_ignored(stage, capsys):
    r2 = FakeR2.mirror(stage)
    r2.objects["current.json"] = (b"{}", "application/json")
    r2.objects["releases/other-release/master.kml"] = (b"x", None)
    assert _verify(stage, r2) == 0


def test_missing_artifact_fails(stage, capsys):
    r2 = FakeR2.mirror(stage)
    del r2.objects[PREFIX + "districts/tyler.kml"]
    assert _verify(stage, r2) == 1
    errors = _errors(capsys.readouterr().out)
    assert (
        "::error::Verification failed: districts/tyler.kml: missing from remote listing" in errors
    )


def test_missing_remote_manifest_is_reported_before_download_fails(stage, capsys):
    r2 = FakeR2.mirror(stage)
    del r2.objects[PREFIX + "manifest.json"]
    # The listing checks run and print first; the manifest re-download
    # then fails the aws call itself, which aborts with a traceback.
    with pytest.raises(subprocess.CalledProcessError):
        _verify(stage, r2)
    assert "  size mismatches:     1" in capsys.readouterr().out


def test_size_mismatch_fails(stage, capsys):
    r2 = FakeR2.mirror(stage)
    r2.objects[PREFIX + "counties/smith.kmz"] = (b"short", CONTENT_TYPES[".kmz"])
    assert _verify(stage, r2) == 1
    errors = _errors(capsys.readouterr().out)
    assert (
        "::error::Verification failed: counties/smith.kmz: remote size 5 != manifest size 15"
        in (errors)
    )


def test_size_mismatch_report_is_capped_at_ten(tmp_path, capsys):
    stage = tmp_path / "release-stage"
    stage.mkdir()
    artifacts = [
        _artifact(stage, "master.kml", "master_kml", b"<kml/>"),
        _artifact(stage, "counties/c00.kmz", "county_kmz", b"PK"),
    ]
    artifacts += [
        {"type": "county_kmz", "path": f"counties/x{i:02d}.kmz", "size_bytes": 1, "sha256": ""}
        for i in range(12)
    ]
    (stage / "manifest.json").write_text(json.dumps({"artifacts": artifacts}), encoding="utf-8")
    assert _verify(stage, FakeR2.mirror(stage)) == 1
    out = capsys.readouterr().out
    assert "  size mismatches:     12" in out
    assert out.count("missing from remote listing") == 10
    assert "::error::Verification failed: ...and 2 more size mismatches" in out


def test_hash_mismatch_fails(stage, capsys):
    r2 = FakeR2.mirror(stage)
    # Same size, different bytes: passes the size check, fails the hash.
    r2.objects[PREFIX + "master.kml"] = (b"<kml>MASTER</kml>", CONTENT_TYPES[".kml"])
    assert _verify(stage, r2) == 1
    out = capsys.readouterr().out
    assert "  size mismatches:     0" in out
    assert "  hash check master.kml: MISMATCH" in out
    assert any("master.kml: sha256 mismatch" in e for e in _errors(out))


def test_wrong_content_type_fails(stage, capsys):
    r2 = FakeR2.mirror(stage)
    body, _ = r2.objects[PREFIX + "counties/anderson.kmz"]
    r2.objects[PREFIX + "counties/anderson.kmz"] = (body, "application/octet-stream")
    assert _verify(stage, r2) == 1
    errors = _errors(capsys.readouterr().out)
    assert (
        "::error::Verification failed: counties/anderson.kmz: content-type "
        "'application/octet-stream' != expected 'application/vnd.google-earth.kmz'"
    ) in errors


def test_content_type_checks_do_not_cover_zips(stage, capsys):
    # Step 10 is extraction only: ZIP content-type is Step 12's concern.
    body = b"PK-zip"
    _artifact(stage, "offline/statewide.zip", "statewide_zip", body)
    manifest = json.loads((stage / "manifest.json").read_text(encoding="utf-8"))
    manifest["artifacts"].append(
        {
            "type": "statewide_zip",
            "path": "offline/statewide.zip",
            "size_bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
        }
    )
    (stage / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    r2 = FakeR2.mirror(stage)
    r2.objects[PREFIX + "offline/statewide.zip"] = (body, "binary/octet-stream")
    assert _verify(stage, r2) == 0


def test_truncated_listing_aborts(stage, capsys):
    r2 = FakeR2.mirror(stage)
    r2.truncated = True
    assert _verify(stage, r2) == 1
    out = capsys.readouterr().out
    assert _errors(out) == [
        "::error::Object listing was truncated (>1000 objects); this check does not paginate"
    ]
    assert "remote object count" not in out
    assert len(r2.calls) == 1


def test_manifest_without_county_kmz_aborts_before_downloads(tmp_path, capsys):
    stage = tmp_path / "release-stage"
    stage.mkdir()
    artifacts = [_artifact(stage, "master.kml", "master_kml", b"<kml/>")]
    (stage / "manifest.json").write_text(json.dumps({"artifacts": artifacts}), encoding="utf-8")
    r2 = FakeR2.mirror(stage)
    assert _verify(stage, r2) == 1
    assert _errors(capsys.readouterr().out) == [
        "::error::No county_kmz artifacts found in manifest"
    ]
    assert len(r2.calls) == 1  # only the listing


def test_empty_remote_prefix_fails(stage, capsys):
    r2 = FakeR2()
    # Nothing uploaded: counts and sizes fail, then the manifest download
    # errors out of the aws call.
    with pytest.raises(subprocess.CalledProcessError):
        _verify(stage, r2)
    out = capsys.readouterr().out
    assert "  remote object count: 0" in out
    assert "  size mismatches:     5" in out


def test_main_builds_aws_calls_against_the_endpoint(stage, monkeypatch):
    seen = []

    def fake_run(cmd, **kwargs):
        seen.append(cmd)
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(verify.subprocess, "run", fake_run)
    with pytest.raises(subprocess.CalledProcessError):
        verify.main(
            [
                "--bucket",
                BUCKET,
                "--release-id",
                RELEASE_ID,
                "--endpoint-url",
                "https://acct.r2.cloudflarestorage.com",
                "--stage-dir",
                str(stage),
            ]
        )
    assert seen[0][0] == "aws"
    assert seen[0][-2:] == ["--endpoint-url", "https://acct.r2.cloudflarestorage.com"]
