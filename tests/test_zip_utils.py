"""Locks down the deterministic-archive contract in `export/zip_utils.py`.

Entries are deliberately plain hardcoded bytes here, never simplekml-derived
content -- simplekml assigns each KML element a globally auto-incrementing
`id` attribute that is not reset per `Kml()` instance (see
`test_kmz_writer.py` for where that matters), so building "the same logical
KML" twice within one process does not reliably produce identical XML bytes.
That is an upstream simplekml property this module has no visibility into
and cannot be responsible for; testing this layer's own contract (ordering,
timestamps, compression, attrs) needs inputs with no hidden global state.
"""

from __future__ import annotations

import hashlib
import zipfile

import pytest

from txdot_overlay.export.zip_utils import ZIP_EPOCH, write_deterministic_zip


def _read_back(path):
    with zipfile.ZipFile(path) as zf:
        return {info.filename: (info, zf.read(info.filename)) for info in zf.infolist()}


def test_entries_are_written_in_sorted_arcname_order(tmp_path):
    # Deliberately out of arcname order.
    entries = [
        ("b.txt", b"second", 0),
        ("a.txt", b"first", 0),
        ("c.txt", b"third", 0),
    ]

    out = write_deterministic_zip(entries, tmp_path / "out.zip", compress_type=zipfile.ZIP_STORED)

    with zipfile.ZipFile(out) as zf:
        assert zf.namelist() == ["a.txt", "b.txt", "c.txt"]


def test_output_is_independent_of_caller_iteration_order(tmp_path):
    entries_forward = [("a.txt", b"first", 0), ("b.txt", b"second", 0)]
    entries_reversed = list(reversed(entries_forward))

    out1 = write_deterministic_zip(
        entries_forward, tmp_path / "forward.zip", compress_type=zipfile.ZIP_STORED
    )
    out2 = write_deterministic_zip(
        entries_reversed, tmp_path / "reversed.zip", compress_type=zipfile.ZIP_STORED
    )

    assert out1.read_bytes() == out2.read_bytes()


def test_rebuilding_the_same_entries_is_byte_for_byte_deterministic(tmp_path):
    entries = [("doc.kml", b"<kml>fixed content</kml>", 0o600 << 16)]

    out1 = write_deterministic_zip(
        entries, tmp_path / "one.zip", compress_type=zipfile.ZIP_DEFLATED
    )
    out2 = write_deterministic_zip(
        entries, tmp_path / "two.zip", compress_type=zipfile.ZIP_DEFLATED
    )

    assert out1.read_bytes() == out2.read_bytes()
    assert (
        hashlib.sha256(out1.read_bytes()).hexdigest()
        == hashlib.sha256(out2.read_bytes()).hexdigest()
    )


def test_every_entry_gets_the_fixed_epoch_timestamp(tmp_path):
    entries = [("a.txt", b"first", 0), ("b.txt", b"second", 0)]

    out = write_deterministic_zip(entries, tmp_path / "out.zip", compress_type=zipfile.ZIP_STORED)

    with zipfile.ZipFile(out) as zf:
        for info in zf.infolist():
            assert info.date_time == ZIP_EPOCH


def test_data_and_external_attr_are_preserved_per_entry(tmp_path):
    entries = [
        ("a.txt", b"alpha-bytes", 0o644 << 16),
        ("b.txt", b"beta-bytes", 0o600 << 16),
    ]

    out = write_deterministic_zip(entries, tmp_path / "out.zip", compress_type=zipfile.ZIP_STORED)
    by_name = _read_back(out)

    info_a, data_a = by_name["a.txt"]
    info_b, data_b = by_name["b.txt"]
    assert data_a == b"alpha-bytes"
    assert info_a.external_attr == 0o644 << 16
    assert data_b == b"beta-bytes"
    assert info_b.external_attr == 0o600 << 16


@pytest.mark.parametrize(
    "compress_type", [zipfile.ZIP_DEFLATED, zipfile.ZIP_STORED], ids=["deflated", "stored"]
)
def test_caller_chosen_compression_is_honored(tmp_path, compress_type):
    entries = [("data.txt", b"x" * 10_000, 0)]

    out = write_deterministic_zip(entries, tmp_path / "out.zip", compress_type=compress_type)

    with zipfile.ZipFile(out) as zf:
        info = zf.getinfo("data.txt")
        assert info.compress_type == compress_type


def test_stored_is_larger_than_deflated_for_compressible_data(tmp_path):
    """Not testing zlib itself -- just that the two compression choices this
    project actually uses (KMZ -> ZIP_DEFLATED, future offline packages ->
    ZIP_STORED) produce genuinely different archives, proving `compress_type`
    is real, not a no-op parameter.
    """
    entries = [("data.txt", b"x" * 10_000, 0)]

    deflated = write_deterministic_zip(
        entries, tmp_path / "deflated.zip", compress_type=zipfile.ZIP_DEFLATED
    )
    stored = write_deterministic_zip(
        entries, tmp_path / "stored.zip", compress_type=zipfile.ZIP_STORED
    )

    assert deflated.stat().st_size < stored.stat().st_size
