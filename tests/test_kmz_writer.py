"""Locks down `export/kmz_writer.py`'s KMZ determinism contract, and proves the
Step 4 extraction of `export/zip_utils.py` did not change its output.

Fixed, hand-built zip bytes are used for the normalization tests rather than
simplekml-generated ones: simplekml assigns each KML element a globally
auto-incrementing `id` attribute that is not reset per `Kml()` instance, so
building two separate `Kml()` objects with identical logical content within
one process does not reliably produce identical XML bytes -- an upstream
simplekml property, not something `_normalize_kmz` controls or can fix.
Where this file does exercise simplekml (`save_kmz`), it saves the *same*
already-built `Kml` object twice rather than rebuilding a second one, which
sidesteps that global counter entirely and is also how the object is
actually used in production (`build_county_detail_kml` builds one `Kml` per
county and saves it exactly once).
"""

from __future__ import annotations

import hashlib
import zipfile

import simplekml

from txdot_overlay.export.kmz_writer import _normalize_kmz, save_kmz
from txdot_overlay.export.zip_utils import ZIP_EPOCH


def _write_raw_zip(path, entries, *, date_time):
    """Build a zip exactly like the one simplekml.Kml.savekmz() would hand to
    _normalize_kmz *before* normalization: unsorted, non-epoch timestamp,
    simplekml's own fixed 0o600 file mode.
    """
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries:
            info = zipfile.ZipInfo(name, date_time=date_time)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            zf.writestr(info, data)


def _reference_old_normalize_kmz(path):
    """Verbatim copy of _normalize_kmz's pre-Step-4 implementation (the
    version committed before export/zip_utils.py existed), kept here only to
    prove the refactor is byte-for-byte equivalent. Not a second production
    implementation to maintain going forward.
    """
    _ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)
    with zipfile.ZipFile(path) as source:
        entries = [
            (info, source.read(info.filename))
            for info in sorted(source.infolist(), key=lambda i: i.filename)
        ]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as target:
        for info, data in entries:
            normalized = zipfile.ZipInfo(info.filename, date_time=_ZIP_EPOCH)
            normalized.compress_type = zipfile.ZIP_DEFLATED
            normalized.external_attr = info.external_attr
            target.writestr(normalized, data)


def test_normalize_kmz_matches_the_pre_refactor_reference_implementation(tmp_path):
    entries = [
        ("doc.kml", b"<kml>fixed content</kml>"),
        ("images/icon.png", b"\x89PNG-fake-bytes"),
    ]
    old_path = tmp_path / "old.kmz"
    new_path = tmp_path / "new.kmz"
    _write_raw_zip(old_path, entries, date_time=(2024, 6, 15, 12, 30, 0))
    _write_raw_zip(new_path, entries, date_time=(2024, 6, 15, 12, 30, 0))

    _reference_old_normalize_kmz(old_path)
    _normalize_kmz(new_path)

    assert old_path.read_bytes() == new_path.read_bytes()
    assert (
        hashlib.sha256(old_path.read_bytes()).hexdigest()
        == hashlib.sha256(new_path.read_bytes()).hexdigest()
    )


def test_normalize_kmz_stamps_the_fixed_epoch_and_sorts_entries(tmp_path):
    path = tmp_path / "unsorted.kmz"
    # Deliberately unsorted and stamped with a non-epoch, "current-looking" time.
    _write_raw_zip(
        path,
        [("z_entry.kml", b"z"), ("a_entry.kml", b"a")],
        date_time=(2026, 9, 26, 21, 0, 0),
    )

    _normalize_kmz(path)

    with zipfile.ZipFile(path) as zf:
        infos = zf.infolist()
        assert [info.filename for info in infos] == ["a_entry.kml", "z_entry.kml"]
        assert all(info.date_time == ZIP_EPOCH for info in infos)
        assert all(info.compress_type == zipfile.ZIP_DEFLATED for info in infos)


def test_normalize_kmz_preserves_external_attr_from_source(tmp_path):
    path = tmp_path / "attrs.kmz"
    _write_raw_zip(path, [("doc.kml", b"<kml/>")], date_time=(2024, 1, 1, 0, 0, 0))

    _normalize_kmz(path)

    with zipfile.ZipFile(path) as zf:
        info = zf.getinfo("doc.kml")
        assert info.external_attr == 0o600 << 16


def test_save_kmz_is_byte_identical_across_repeated_saves_of_the_same_kml(tmp_path):
    """Same already-built Kml object, saved twice -- see module docstring for
    why this (not rebuilding a second Kml()) is the valid way to check
    save_kmz's own determinism.
    """
    kml = simplekml.Kml()
    kml.newpoint(name="marker", coords=[(-96.0, 32.0)])

    path1 = save_kmz(kml, tmp_path / "one.kmz")
    path2 = save_kmz(kml, tmp_path / "two.kmz")

    assert path1.read_bytes() == path2.read_bytes()


def test_save_kmz_produces_a_valid_kmz_with_normalized_metadata(tmp_path):
    kml = simplekml.Kml()
    kml.newpoint(name="marker", coords=[(-96.0, 32.0)])

    path = save_kmz(kml, tmp_path / "county.kmz")

    with zipfile.ZipFile(path) as zf:
        assert zf.testzip() is None
        kml_members = [n for n in zf.namelist() if n.lower().endswith(".kml")]
        assert kml_members
        for info in zf.infolist():
            assert info.date_time == ZIP_EPOCH
            assert info.compress_type == zipfile.ZIP_DEFLATED
