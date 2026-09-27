"""Deterministic ZIP archive writing, shared by every ZIP-producing artifact in
this project -- KMZ files today (`export/kmz_writer.py`), District/Statewide
offline packages later.

A thin wrapper around the standard library's `zipfile` module, not a custom
archive format. The only thing this module adds is the fixed set of choices
that make repeated builds of the same logical content produce byte-identical
archives:

- every entry gets the same fixed timestamp (`ZIP_EPOCH`), never the current
  time or a source file's mtime
- entries are always written in a stable order (sorted by arcname), never in
  whatever order the caller happened to iterate them
- compression method and each entry's `external_attr` are the caller's
  explicit choice, never a platform- or library-specific default
"""

from __future__ import annotations

import zipfile
from collections.abc import Iterable
from pathlib import Path

# Earliest timestamp the zip format can represent. Stamping every entry with
# it makes an archive's bytes depend only on its contents, never on when it
# was built.
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)


def write_deterministic_zip(
    entries: Iterable[tuple[str, bytes, int]],
    output_path: Path,
    *,
    compress_type: int,
) -> Path:
    """Write `entries` to `output_path` as a deterministic zip archive.

    Each entry is `(arcname, data, external_attr)`. Entries are sorted by
    arcname before writing, so the caller's iteration order never affects
    the output bytes, and every entry gets the same fixed `ZIP_EPOCH`
    timestamp so build time never does either.

    `compress_type` is the caller's choice, not a default this module
    imposes: KMZ output re-compresses its (small, text) KML payload with
    `zipfile.ZIP_DEFLATED`; a future offline package wrapping already-
    deflated KMZ files as opaque members would use `zipfile.ZIP_STORED`
    instead, to avoid a second compression pass for negligible size benefit
    and to avoid depending on a particular zlib build producing identical
    DEFLATE output across platforms.

    Does not create `output_path`'s parent directory -- callers that need
    that (see `export/kmz_writer.py`'s `save_kml`/`save_kmz`) already do it
    themselves before writing.
    """
    with zipfile.ZipFile(output_path, "w", compress_type) as target:
        for arcname, data, external_attr in sorted(entries, key=lambda entry: entry[0]):
            info = zipfile.ZipInfo(arcname, date_time=ZIP_EPOCH)
            info.compress_type = compress_type
            info.external_attr = external_attr
            target.writestr(info, data)
    return output_path
