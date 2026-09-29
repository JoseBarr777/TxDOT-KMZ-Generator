"""Manifest-driven release packager for the staging workflow.

Answers: which generated files are allowed into the release staging
directory? THE release invariant: what ships to R2 is defined by
manifest.json, never by whatever happens to sit in data/output/. This
copies manifest.json plus exactly the paths manifest["artifacts"] declares
into a clean release-stage/ tree, and every later workflow step (upload and
verification) reads only from release-stage/. Anything undeclared -- the
checked-out data/output/.gitkeep that broke staging run #2, .DS_Store,
editor temp files, debug dumps, a future artifact type the manifest builder
does not yet advertise -- is structurally unable to reach R2, because it is
never copied here in the first place. This is an allowlist, not an exclude
list.

Extracted verbatim in behavior from the former inline heredoc in
.github/workflows/release-staging.yml ("Package release tree from
manifest"). Standard library only.

Exit status: 0 when the staged tree is exactly manifest.json + every
declared artifact, 1 otherwise. A malformed manifest (bad JSON, missing
keys) raises and exits 1 with a traceback, exactly as the inline version
did.

Usage:
    python3 scripts/release/package.py [--source-dir data/output] [--stage-dir release-stage]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

DEFAULT_SOURCE_DIR = "data/output"
DEFAULT_STAGE_DIR = "release-stage"
MANIFEST_NAME = "manifest.json"

# Cap on individually listed missing artifacts, so a wholesale failure does
# not bury the log.
MAX_MISSING_REPORTED = 10


def declared_path_failures(declared: list[str]) -> list[str]:
    """Reject a manifest that cannot describe a coherent release.

    Duplicates would silently collapse two artifacts into one staged file,
    and a non-relative/escaping path would write outside the staging tree.
    """
    failures = []
    seen = set()
    for rel in declared:
        if rel in seen:
            failures.append(f"manifest declares duplicate path: {rel}")
        seen.add(rel)
        if Path(rel).is_absolute() or ".." in Path(rel).parts:
            failures.append(f"manifest declares a non-relative or escaping path: {rel}")
    if MANIFEST_NAME in seen:
        failures.append(
            f"manifest declares {MANIFEST_NAME} as an artifact; it is staged separately"
        )
    return failures


def package(source_dir: Path, stage_dir: Path) -> int:
    """Stage manifest.json + manifest-declared artifacts; return an exit status."""
    manifest_src = source_dir / MANIFEST_NAME
    try:
        with manifest_src.open(encoding="utf-8") as fh:
            manifest = json.load(fh)
    except FileNotFoundError:
        print(f"::error::{manifest_src} not found -- nothing to package")
        return 1

    declared = [artifact["path"] for artifact in manifest["artifacts"]]

    # Validate before copying anything.
    failures = declared_path_failures(declared)
    if failures:
        for reason in failures:
            print(f"::error::Packaging failed: {reason}")
        return 1

    # A stale tree from an earlier attempt must never leak into this release.
    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    stage_dir.mkdir(parents=True)

    staged = 0
    missing = []
    for rel in declared:
        src = source_dir / rel
        if not src.is_file():
            missing.append(rel)
            continue
        dst = stage_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        staged += 1

    if missing:
        for rel in missing[:MAX_MISSING_REPORTED]:
            print(
                f"::error::Packaging failed: manifest-declared artifact missing from {source_dir}: {rel}"
            )
        if len(missing) > MAX_MISSING_REPORTED:
            print(
                "::error::Packaging failed: "
                f"...and {len(missing) - MAX_MISSING_REPORTED} more missing artifact(s)"
            )
        return 1

    shutil.copy2(manifest_src, stage_dir / MANIFEST_NAME)

    total_staged = sum(1 for p in stage_dir.rglob("*") if p.is_file())

    print("Release packaging summary")
    print(f"  manifest artifacts:  {len(declared)}")
    print(f"  staged artifacts:    {staged}")
    print(f"  total staged files:  {total_staged}")

    # Catches declared paths that are distinct strings but land on the same
    # staged file (e.g. "a/b.kmz" and "a/./b.kmz").
    if staged != len(declared) or total_staged != len(declared) + 1:
        print(
            "::error::Packaging failed: staged tree does not match the manifest contract "
            f"(expected {len(declared)} artifacts + {MANIFEST_NAME} = {len(declared) + 1} files)"
        )
        return 1

    print(
        f"Packaged {stage_dir}/: {MANIFEST_NAME} + {staged} manifest-declared artifact(s), nothing else."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source-dir", type=Path, default=Path(DEFAULT_SOURCE_DIR))
    parser.add_argument("--stage-dir", type=Path, default=Path(DEFAULT_STAGE_DIR))
    args = parser.parse_args(argv)
    return package(args.source_dir, args.stage_dir)


if __name__ == "__main__":
    sys.exit(main())
