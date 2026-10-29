"""
Tests of the attachment reader (RF-01, RF-02, RF-10): ``read_xml`` and its size cap, and
``read_xml_bytes``, the same reading over bytes already in memory (spec 007).

Isolation: every attachment is built in memory by the ``conftest.py`` factories and written under
``tmp_path``; nothing touches the network, an environment variable or a path outside it. The
oversized and corrupt files are the attack itself (zip bombs, lying headers), so a failure here
means a defense is gone. Each one expects ``ReportRefused`` and asserts ``.reason``.
"""

from __future__ import annotations

import io
import struct
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

from mailvigil.reports.errors import Reason, ReportRefused
from mailvigil.reports.reader import MAX_BYTES, Kind, _read_capped, read_xml, read_xml_bytes

type _MakeZip = Callable[[Mapping[str, bytes]], bytes]
type _MakeGzip = Callable[[bytes], bytes]

_XML = b"<feedback><a>x</a></feedback>"

# Signature of a zip central directory entry, and where its fields start (APPNOTE 4.3.12).
_CENTRAL_SIGNATURE = b"PK\x01\x02"
_FLAGS_OFFSET = 8
_METHOD_OFFSET = 10
_SIZE_OFFSET = 24

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write(directory: Path, name: str, content: bytes) -> Path:
    """
    Write an attachment under the test directory.

    Args:
        directory (Path): Where to write, normally ``tmp_path``.
        name (str): The file name, which decides how the reader treats it.
        content (bytes): The file content.

    Returns:
        Path: The file written.
    """
    path = directory / name
    path.write_bytes(content)
    return path


def _patch_central_entry(archive: bytes, offset: int, fmt: str, value: int) -> bytes:
    """
    Overwrite one field of the central directory entry of a one-member zip.

    The central directory is what ``zipfile`` trusts when it opens a member, so this is how a
    header is made to lie. The local header, whose name is all ``zipfile`` checks, is left alone.

    Args:
        archive (bytes): A zip with exactly one member.
        offset (int): Where the field starts, counted from the entry signature.
        fmt (str): The ``struct`` format of the field, little endian.
        value (int): The new value.

    Returns:
        bytes: The zip with the field replaced.
    """
    start = archive.rindex(_CENTRAL_SIGNATURE) + offset
    patched = struct.pack(fmt, value)
    return archive[:start] + patched + archive[start + len(patched) :]


# ---------------------------------------------------------------------------
# Round trips (RF-01)
# ---------------------------------------------------------------------------


def test_xml_file_is_read_as_is(tmp_path: Path) -> None:
    """A plain ``.xml`` is returned byte for byte."""
    assert read_xml(_write(tmp_path, "report.xml", _XML)) == _XML


def test_gzip_file_is_decompressed(tmp_path: Path, make_gzip: _MakeGzip) -> None:
    """A ``.gz`` gives the document it wraps."""
    assert read_xml(_write(tmp_path, "report.xml.gz", make_gzip(_XML))) == _XML


def test_zip_file_gives_its_xml_member(tmp_path: Path, make_zip: _MakeZip) -> None:
    """A ``.zip`` with one ``.xml`` member gives that member."""
    assert read_xml(_write(tmp_path, "report.zip", make_zip({"report.xml": _XML}))) == _XML


@pytest.mark.parametrize("name", ["REPORT.XML", "Report.Xml.GZ", "report.ZIP"])
def test_suffix_is_matched_without_regard_to_case(
    tmp_path: Path, make_gzip: _MakeGzip, make_zip: _MakeZip, name: str
) -> None:
    """Providers and operating systems upper-case suffixes; the reader still accepts them."""
    content = {
        "xml": _XML,
        "gz": make_gzip(_XML),
        "zip": make_zip({"report.xml": _XML}),
    }[name.rsplit(".", 1)[1].lower()]

    assert read_xml(_write(tmp_path, name, content)) == _XML


def test_zip_member_suffix_is_matched_without_regard_to_case(
    tmp_path: Path, make_zip: _MakeZip
) -> None:
    """A member called ``REPORT.XML`` is the report."""
    assert read_xml(_write(tmp_path, "r.zip", make_zip({"REPORT.XML": _XML}))) == _XML


def test_zip_ignores_directories_and_members_that_are_not_xml(
    tmp_path: Path, make_zip: _MakeZip
) -> None:
    """Only ``.xml`` files count as the report; a folder entry or a note beside it does not."""
    archive = make_zip({"reports/": b"", "reports/report.xml": _XML, "README.txt": b"hello"})

    assert read_xml(_write(tmp_path, "r.zip", archive)) == _XML


def test_zip_member_name_is_never_used_as_a_path(tmp_path: Path, make_zip: _MakeZip) -> None:
    """A member named ``../../escape.xml`` is read in memory; nothing is extracted anywhere."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    archive = _write(inbox, "r.zip", make_zip({"../../escape.xml": _XML}))

    assert read_xml(archive) == _XML
    assert not (tmp_path / "escape.xml").exists()
    assert sorted(path.name for path in tmp_path.rglob("*")) == ["inbox", "r.zip"]


# ---------------------------------------------------------------------------
# Files that are refused before their content matters (RF-01)
# ---------------------------------------------------------------------------


def test_unknown_suffix_is_refused_without_opening_the_file(tmp_path: Path) -> None:
    """The suffix is checked first: a ``.txt`` that does not exist is not ``UNREADABLE``."""
    with pytest.raises(ReportRefused) as caught:
        read_xml(tmp_path / "missing.txt")

    assert caught.value.reason is Reason.UNSUPPORTED_EXTENSION


def test_missing_file_is_unreadable(tmp_path: Path) -> None:
    """A path that does not exist is ``UNREADABLE``."""
    with pytest.raises(ReportRefused) as caught:
        read_xml(tmp_path / "missing.xml")

    assert caught.value.reason is Reason.UNREADABLE


def test_directory_is_unreadable(tmp_path: Path) -> None:
    """A directory whose name looks like a report is not a regular file."""
    folder = tmp_path / "folder.xml"
    folder.mkdir()

    with pytest.raises(ReportRefused) as caught:
        read_xml(folder)

    assert caught.value.reason is Reason.UNREADABLE


def test_zip_without_an_xml_member_is_refused(tmp_path: Path, make_zip: _MakeZip) -> None:
    """A zip with no ``.xml`` has nothing to read."""
    archive = _write(tmp_path, "r.zip", make_zip({"notes.txt": b"hello", "folder/": b""}))

    with pytest.raises(ReportRefused) as caught:
        read_xml(archive)

    assert caught.value.reason is Reason.NO_XML_MEMBER


def test_zip_with_two_xml_members_is_refused(tmp_path: Path, make_zip: _MakeZip) -> None:
    """Which of two documents is the report is not guessed (ADR-7)."""
    archive = _write(tmp_path, "r.zip", make_zip({"a.xml": _XML, "b.xml": _XML}))

    with pytest.raises(ReportRefused) as caught:
        read_xml(archive)

    assert caught.value.reason is Reason.MULTIPLE_XML_MEMBERS


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("r.zip", b"this is not a zip"),
        ("r.zip", b""),
        ("r.gz", b"this is not gzip"),
        ("r.gz", b"\x1f\x8b\x08\x00garbage that is not a deflate stream"),
    ],
    ids=["zip-text", "zip-empty", "gzip-text", "gzip-bad-stream"],
)
def test_corrupt_archive_is_refused(tmp_path: Path, name: str, content: bytes) -> None:
    """A file that is not the archive its suffix claims is ``NOT_AN_ARCHIVE``."""
    with pytest.raises(ReportRefused) as caught:
        read_xml(_write(tmp_path, name, content))

    assert caught.value.reason is Reason.NOT_AN_ARCHIVE


def test_truncated_gzip_is_refused(tmp_path: Path, make_gzip: _MakeGzip) -> None:
    """A gzip cut short ends before its trailer: ``EOFError`` in the standard library."""
    truncated = make_gzip(_XML * 100)[:-12]

    with pytest.raises(ReportRefused) as caught:
        read_xml(_write(tmp_path, "r.gz", truncated))

    assert caught.value.reason is Reason.NOT_AN_ARCHIVE


def test_encrypted_zip_member_is_refused(tmp_path: Path, make_zip: _MakeZip) -> None:
    """An encrypted member needs a password the reader does not have (``RuntimeError``)."""
    archive = _patch_central_entry(make_zip({"r.xml": _XML}), _FLAGS_OFFSET, "<H", 0x1)

    with pytest.raises(ReportRefused) as caught:
        read_xml(_write(tmp_path, "r.zip", archive))

    assert caught.value.reason is Reason.NOT_AN_ARCHIVE


def test_unsupported_zip_compression_is_refused(tmp_path: Path, make_zip: _MakeZip) -> None:
    """A compression method the standard library lacks is ``NotImplementedError`` inside."""
    archive = _patch_central_entry(make_zip({"r.xml": _XML}), _METHOD_OFFSET, "<H", 99)

    with pytest.raises(ReportRefused) as caught:
        read_xml(_write(tmp_path, "r.zip", archive))

    assert caught.value.reason is Reason.NOT_AN_ARCHIVE


# ---------------------------------------------------------------------------
# Size (RF-02, RF-10)
# ---------------------------------------------------------------------------


def test_file_over_the_cap_on_disk_is_refused_before_it_is_read(tmp_path: Path) -> None:
    """The size on disk is checked with ``stat``; a plain ``.xml`` over the cap never opens."""
    with pytest.raises(ReportRefused) as caught:
        read_xml(_write(tmp_path, "big.xml", b"\0" * (MAX_BYTES + 1)))

    assert caught.value.reason is Reason.FILE_TOO_LARGE


def test_gzip_bomb_is_refused(tmp_path: Path, make_gzip: _MakeGzip) -> None:
    """A few KB on disk that inflate past the cap are refused on the bytes actually produced."""
    bomb = _write(tmp_path, "bomb.gz", make_gzip(b"\0" * (MAX_BYTES + 1)))
    assert bomb.stat().st_size < MAX_BYTES // 100

    with pytest.raises(ReportRefused) as caught:
        read_xml(bomb)

    assert caught.value.reason is Reason.DECOMPRESSED_TOO_LARGE


def test_zip_bomb_is_refused(tmp_path: Path, make_zip: _MakeZip) -> None:
    """The same for a zip member."""
    bomb = _write(tmp_path, "bomb.zip", make_zip({"bomb.xml": b"\0" * (MAX_BYTES + 1)}))
    assert bomb.stat().st_size < MAX_BYTES // 100

    with pytest.raises(ReportRefused) as caught:
        read_xml(bomb)

    assert caught.value.reason is Reason.DECOMPRESSED_TOO_LARGE


def test_zip_header_declaring_a_smaller_size_is_refused(tmp_path: Path, make_zip: _MakeZip) -> None:
    """A header that understates the size makes ``zipfile`` stop early and fail the CRC check."""
    archive = _patch_central_entry(make_zip({"r.xml": _XML * 100}), _SIZE_OFFSET, "<I", 10)

    with pytest.raises(ReportRefused) as caught:
        read_xml(_write(tmp_path, "r.zip", archive))

    assert caught.value.reason is Reason.NOT_AN_ARCHIVE


def test_zip_bomb_is_refused_whatever_its_header_declares(
    tmp_path: Path, make_zip: _MakeZip
) -> None:
    """The cap rests on the bytes produced: a header declaring a tiny size does not slip a bomb in.

    ``zipfile`` honors the declared size, so the lie ends in a CRC failure rather than in an
    oversized read; either way the bomb is refused and nothing past the cap is returned.
    """
    archive = _patch_central_entry(
        make_zip({"bomb.xml": b"\0" * (MAX_BYTES + 1)}), _SIZE_OFFSET, "<I", 10
    )

    with pytest.raises(ReportRefused) as caught:
        read_xml(_write(tmp_path, "bomb.zip", archive))

    assert caught.value.reason in {Reason.DECOMPRESSED_TOO_LARGE, Reason.NOT_AN_ARCHIVE}


def test_read_capped_refuses_a_stream_over_the_cap() -> None:
    """The cap is a count of bytes read; a plain stream has no header to consult."""
    with pytest.raises(ReportRefused) as caught:
        _read_capped(io.BytesIO(b"\0" * (MAX_BYTES + 1)))

    assert caught.value.reason is Reason.DECOMPRESSED_TOO_LARGE


class _EndlessStream:
    """
    A stream that never ends, to prove the cap bounds what is read.

    Attributes:
        served (int): How many bytes have been handed out so far.
    """

    def __init__(self) -> None:
        """Start with nothing served."""
        self.served = 0

    def read(self, size: int, /) -> bytes:
        """
        Hand out zeros, refusing an unbounded read.

        Args:
            size (int): How many bytes the caller asks for.

        Returns:
            bytes: ``size`` zeros.
        """
        assert size >= 0, "an unbounded read would never come back from an endless stream"
        self.served += size
        return b"\0" * size


def test_read_capped_stops_reading_at_the_cap() -> None:
    """On an endless stream the reader holds at most ``MAX_BYTES + 1`` bytes, then refuses."""
    stream = _EndlessStream()

    with pytest.raises(ReportRefused) as caught:
        _read_capped(stream)

    assert caught.value.reason is Reason.DECOMPRESSED_TOO_LARGE
    assert stream.served == MAX_BYTES + 1


class _ShortReadStream:
    """
    A stream that returns less than asked, as a raw stream is allowed to.

    Attributes:
        content (memoryview): The whole stream.
        position (int): How many bytes have been handed out.
    """

    def __init__(self, content: bytes) -> None:
        """
        Hold the content to hand out.

        Args:
            content (bytes): The whole stream.
        """
        # A view and a position: slicing the bytes again on every read copies the rest each time.
        self.content = memoryview(content)
        self.position = 0

    def read(self, size: int, /) -> bytes:
        """
        Hand out at most 1,000 bytes, whatever was asked.

        Args:
            size (int): How many bytes the caller asks for.

        Returns:
            bytes: Up to ``min(size, 1000)`` bytes; empty at the end.
        """
        end = self.position + min(size, 1000)
        chunk = bytes(self.content[self.position : end])
        self.position = end
        return chunk


def test_read_capped_keeps_reading_after_a_short_read() -> None:
    """A short read is not the end: the content comes back whole, not cut at the first chunk."""
    content = b"x" * 5000

    assert _read_capped(_ShortReadStream(content)) == content


def test_read_capped_refuses_over_the_cap_after_short_reads() -> None:
    """Short reads cannot be used to slip past the cap."""
    with pytest.raises(ReportRefused) as caught:
        _read_capped(_ShortReadStream(b"\0" * (MAX_BYTES + 1)))

    assert caught.value.reason is Reason.DECOMPRESSED_TOO_LARGE


def test_content_of_exactly_the_cap_is_accepted(tmp_path: Path, make_gzip: _MakeGzip) -> None:
    """The cap is inclusive: ``MAX_BYTES`` is fine, one more is not."""
    content = b" " * MAX_BYTES

    assert read_xml(_write(tmp_path, "exact.xml", content)) == content
    assert read_xml(_write(tmp_path, "exact.xml.gz", make_gzip(content))) == content


def test_refusal_detail_does_not_echo_the_content(tmp_path: Path, make_gzip: _MakeGzip) -> None:
    """The detail says what happened, never what the file held."""
    with pytest.raises(ReportRefused) as caught:
        read_xml(_write(tmp_path, "r.gz", make_gzip(b"secret-token " * (MAX_BYTES // 10))))

    assert "secret-token" not in caught.value.detail


# ---------------------------------------------------------------------------
# Bytes in memory (RF-04 of spec 007)
# ---------------------------------------------------------------------------


def _stored(kind: Kind, content: bytes, make_gzip: _MakeGzip, make_zip: _MakeZip) -> bytes:
    """
    Wrap a document the way an attachment of that kind stores it.

    Args:
        kind (Kind): ``xml``, ``gz`` or ``zip``.
        content (bytes): The document.
        make_gzip (_MakeGzip): The ``conftest.py`` gzip factory.
        make_zip (_MakeZip): The ``conftest.py`` zip factory.

    Returns:
        bytes: The attachment as it would arrive.
    """
    if kind == "gz":
        return make_gzip(content)
    if kind == "zip":
        return make_zip({"report.xml": content})
    return content


@pytest.mark.parametrize("kind", ["xml", "gz", "zip"])
def test_bytes_give_the_same_document_as_the_file(
    tmp_path: Path, make_gzip: _MakeGzip, make_zip: _MakeZip, kind: Kind
) -> None:
    """A message attachment and a loose file of the same content read the same."""
    data = _stored(kind, _XML, make_gzip, make_zip)

    assert read_xml_bytes(data, kind) == _XML
    assert read_xml_bytes(data, kind) == read_xml(_write(tmp_path, f"report.{kind}", data))


@pytest.mark.parametrize("kind", ["xml", "gz", "zip"])
def test_bytes_over_the_cap_are_refused_before_an_archive_is_opened(kind: Kind) -> None:
    """The size of what arrived is checked first, as ``stat`` is for a file on disk."""
    with pytest.raises(ReportRefused) as caught:
        read_xml_bytes(b"\0" * (MAX_BYTES + 1), kind)

    assert caught.value.reason is Reason.FILE_TOO_LARGE


def test_a_gzip_bomb_in_memory_is_refused(make_gzip: _MakeGzip) -> None:
    """A few KB that inflate past the cap are refused on the bytes produced."""
    bomb = make_gzip(b"\0" * (MAX_BYTES + 1))
    assert len(bomb) < MAX_BYTES // 100

    with pytest.raises(ReportRefused) as caught:
        read_xml_bytes(bomb, "gz")

    assert caught.value.reason is Reason.DECOMPRESSED_TOO_LARGE


def test_a_zip_bomb_in_memory_is_refused_whatever_its_header_declares(make_zip: _MakeZip) -> None:
    """The cap rests on the bytes produced, so a header that lies cannot slip a bomb in."""
    plain = make_zip({"bomb.xml": b"\0" * (MAX_BYTES + 1)})
    lying = _patch_central_entry(plain, _SIZE_OFFSET, "<I", 10)

    for archive in (plain, lying):
        with pytest.raises(ReportRefused) as caught:
            read_xml_bytes(archive, "zip")

        assert caught.value.reason in {Reason.DECOMPRESSED_TOO_LARGE, Reason.NOT_AN_ARCHIVE}
    with pytest.raises(ReportRefused) as exact:
        read_xml_bytes(plain, "zip")
    assert exact.value.reason is Reason.DECOMPRESSED_TOO_LARGE


@pytest.mark.parametrize(
    ("kind", "data"),
    [
        ("zip", b"this is not a zip"),
        ("zip", b""),
        ("gz", b"this is not gzip"),
        ("gz", b"\x1f\x8b\x08\0garbage that is not a deflate stream"),
    ],
    ids=["zip-text", "zip-empty", "gzip-text", "gzip-bad-stream"],
)
def test_corrupt_archive_bytes_are_refused(kind: Kind, data: bytes) -> None:
    """Bytes that are not the archive their kind claims are ``NOT_AN_ARCHIVE``."""
    with pytest.raises(ReportRefused) as caught:
        read_xml_bytes(data, kind)

    assert caught.value.reason is Reason.NOT_AN_ARCHIVE


def test_a_truncated_gzip_in_memory_is_refused(make_gzip: _MakeGzip) -> None:
    """A gzip cut short ends before its trailer."""
    with pytest.raises(ReportRefused) as caught:
        read_xml_bytes(make_gzip(_XML * 100)[:-12], "gz")

    assert caught.value.reason is Reason.NOT_AN_ARCHIVE


def test_zip_bytes_without_or_with_several_xml_members_are_refused(make_zip: _MakeZip) -> None:
    """The same two refusals a loose zip gets, with the same reasons."""
    with pytest.raises(ReportRefused) as none:
        read_xml_bytes(make_zip({"notes.txt": b"hello"}), "zip")
    with pytest.raises(ReportRefused) as two:
        read_xml_bytes(make_zip({"a.xml": _XML, "b.xml": _XML}), "zip")

    assert none.value.reason is Reason.NO_XML_MEMBER
    assert two.value.reason is Reason.MULTIPLE_XML_MEMBERS


def test_reading_bytes_writes_nothing_to_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_zip: _MakeZip
) -> None:
    """A member named ``../escape.xml`` is read in memory and never extracted (RNF-02)."""
    monkeypatch.chdir(tmp_path)

    assert read_xml_bytes(make_zip({"../escape.xml": _XML}), "zip") == _XML
    assert list(tmp_path.rglob("*")) == []
