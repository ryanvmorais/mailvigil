"""
Reading one attachment: from a ``.xml``, ``.gz`` or ``.zip`` file, or from the same bytes taken
out of a mail message, to the bytes of its XML.

A report arrives from outside, so the file is hostile input: a few KB of zip or gzip can inflate to
gigabytes. The one size defense on the decompressed side counts the bytes actually produced and
stops at ``MAX_BYTES``; it never consults a size an archive declares, because a header can lie
(ADR-2). Nothing is extracted to disk and the name of a zip member is never used as a path.
"""

from __future__ import annotations

import gzip
import io
import stat
import zipfile
import zlib
from pathlib import Path
from typing import BinaryIO, Literal, Protocol

from mailvigil.reports.errors import Reason, ReportRefused

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# The cap on a document, on disk and once decompressed: 5 MiB, in bytes. A busy domain's report is
# far smaller; the source script never hit it. Raising it is a decision for a spec, not a silent
# edit.
MAX_BYTES = 5 * 1024 * 1024

# Only the three forms a provider sends a report in, so a mail attachment of any other kind is
# never opened as an archive.
type Kind = Literal["xml", "gz", "zip"]

# The suffix of each form; any other suffix is refused before the file opens.
KIND_BY_SUFFIX: dict[str, Kind] = {".xml": "xml", ".gz": "gz", ".zip": "zip"}

# What the standard library raises for an archive it cannot read. ``BadGzipFile`` is an ``OSError``,
# so this tuple must be caught before ``OSError``. ``NotImplementedError`` is a compression method
# it lacks and ``RuntimeError`` is an encrypted member. ``ValueError`` is what ``zipfile`` raises
# for a damaged archive read from memory, where a file would give ``BadZipFile``.
_ARCHIVE_ERRORS = (
    zipfile.BadZipFile,
    gzip.BadGzipFile,
    zlib.error,
    EOFError,
    NotImplementedError,
    RuntimeError,
    ValueError,
)

# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


class _Readable(Protocol):
    """What ``_read_capped`` needs of a stream: a bounded ``read``."""

    def read(self, size: int, /) -> bytes:
        """
        Read up to ``size`` bytes.

        Args:
            size (int): The most bytes to return.

        Returns:
            bytes: Up to ``size`` bytes; empty at the end of the stream.
        """


def _read_capped(stream: _Readable) -> bytes:
    """
    Read a whole stream, refusing it as soon as it holds more than ``MAX_BYTES``.

    Args:
        stream (_Readable): A gzip stream, a zip member or a file.

    Returns:
        bytes: The content, at most ``MAX_BYTES`` long.

    Raises:
        ReportRefused: ``DECOMPRESSED_TOO_LARGE`` when the stream has more than ``MAX_BYTES``. At
            most ``MAX_BYTES + 1`` bytes are ever held.
    """
    chunks: list[bytes] = []
    total = 0
    # A raw stream may return less than asked without having ended, so one ``read`` is not enough:
    # stopping at the first short read would hand back a truncated document as if it were whole.
    while total <= MAX_BYTES:
        chunk = stream.read(MAX_BYTES + 1 - total)
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    if total > MAX_BYTES:
        raise ReportRefused(Reason.DECOMPRESSED_TOO_LARGE, f"more than {MAX_BYTES} bytes")
    return b"".join(chunks)


def _read_zip(source: Path | BinaryIO) -> bytes:
    """
    Read the one ``.xml`` member of a zip, in memory.

    Args:
        source (Path | BinaryIO): The zip file, or its bytes in a stream.

    Returns:
        bytes: The content of the member.

    Raises:
        ReportRefused: ``NO_XML_MEMBER`` or ``MULTIPLE_XML_MEMBERS`` when the zip does not hold
            exactly one ``.xml`` file, and ``DECOMPRESSED_TOO_LARGE`` for a member over the cap.
    """
    with zipfile.ZipFile(source) as archive:
        members = [
            member
            for member in archive.infolist()
            if not member.is_dir() and member.filename.lower().endswith(".xml")
        ]
        if not members:
            raise ReportRefused(Reason.NO_XML_MEMBER, "the zip holds no .xml file")
        if len(members) > 1:
            raise ReportRefused(Reason.MULTIPLE_XML_MEMBERS, f"the zip holds {len(members)} files")
        with archive.open(members[0]) as stream:
            return _read_capped(stream)


def _read_kind(kind: Kind, source: Path | BinaryIO) -> bytes:
    """
    Read the XML out of an attachment of a known form, whether it is on disk or in memory.

    Args:
        kind (Kind): How the attachment is stored.
        source (Path | BinaryIO): The file, or its bytes in a stream.

    Returns:
        bytes: The document, at most ``MAX_BYTES`` long.

    Raises:
        ReportRefused: ``NOT_AN_ARCHIVE`` for a corrupt or unsupported zip or gzip,
            ``DECOMPRESSED_TOO_LARGE`` over the cap, and ``NO_XML_MEMBER`` or
            ``MULTIPLE_XML_MEMBERS`` for a zip without exactly one ``.xml``.
        OSError: When a file on disk cannot be read; the caller names the reason.
    """
    try:
        if kind == "zip":
            return _read_zip(source)
        if kind == "gz":
            with gzip.open(source, "rb") as gz_stream:
                return _read_capped(gz_stream)
        if isinstance(source, Path):
            with source.open("rb") as stream:
                return _read_capped(stream)
        return _read_capped(source)
    except _ARCHIVE_ERRORS as error:
        raise ReportRefused(Reason.NOT_AN_ARCHIVE, type(error).__name__) from None


def read_xml_bytes(data: bytes, kind: Kind) -> bytes:
    """
    Read the XML document of an attachment that is already in memory.

    This is what a mail message gives: the same three forms as a file, with no file name to trust.
    The same cap applies, to the size as it arrived and to the bytes actually produced.

    Args:
        data (bytes): The attachment as stored.
        kind (Kind): How it is stored.

    Returns:
        bytes: The document, at most ``MAX_BYTES`` long.

    Raises:
        ReportRefused: ``FILE_TOO_LARGE`` when ``data`` is over the cap before anything is opened,
            then the same refusals as ``read_xml`` for the content.
    """
    if len(data) > MAX_BYTES:
        raise ReportRefused(Reason.FILE_TOO_LARGE, f"{len(data)} bytes")
    return _read_kind(kind, io.BytesIO(data))


def read_xml(path: Path) -> bytes:
    """
    Read the XML document of one attachment.

    Args:
        path (Path): A ``.xml``, ``.gz`` or ``.zip`` file; the suffix is matched without regard to
            case.

    Returns:
        bytes: The document as stored, at most ``MAX_BYTES`` long.

    Raises:
        ReportRefused: ``UNSUPPORTED_EXTENSION`` for another suffix (checked before the file is
            touched), ``UNREADABLE`` for a file that is missing, not a regular file or not
            permitted, ``FILE_TOO_LARGE`` or ``DECOMPRESSED_TOO_LARGE`` over the cap,
            ``NOT_AN_ARCHIVE`` for a corrupt or unsupported zip or gzip, and ``NO_XML_MEMBER`` or
            ``MULTIPLE_XML_MEMBERS`` for a zip without exactly one ``.xml``.
    """
    suffix = path.suffix.lower()
    kind = KIND_BY_SUFFIX.get(suffix)
    if kind is None:
        raise ReportRefused(Reason.UNSUPPORTED_EXTENSION, f"suffix {suffix or '(none)'}")

    try:
        info = path.stat()
        if not stat.S_ISREG(info.st_mode):
            raise ReportRefused(Reason.UNREADABLE, "not a regular file")
        if info.st_size > MAX_BYTES:
            raise ReportRefused(Reason.FILE_TOO_LARGE, f"{info.st_size} bytes on disk")
        return _read_kind(kind, path)
    except OSError as error:
        raise ReportRefused(Reason.UNREADABLE, type(error).__name__) from None
