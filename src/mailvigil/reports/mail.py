"""
Reading mail messages: the report attachments inside an ``.eml``, and the messages inside an
``.mbox``, as bytes the reader of ``reader.py`` can open.

A message is a container the sender controls, so it is hostile input twice over: parts inside parts,
and a parser that spends time and memory per line. Every bound is checked before or while the
``email`` package works, never after (ADR-1, ADR-2 of 007): the size of the message, its number of
lines, its number of parts and its depth. This module returns attachments as bytes; it never touches
the XML or the report, and it never opens a message attached to a message (ADR-4).
"""

from __future__ import annotations

import email.errors
import re
import stat
from collections.abc import Iterator
from dataclasses import dataclass
from email.header import Header, decode_header, make_header
from email.message import Message
from email.parser import BytesFeedParser
from email.policy import Compat32, Policy
from pathlib import Path
from typing import BinaryIO, cast

from mailvigil.reports.errors import Reason, ReportRefused
from mailvigil.reports.reader import KIND_BY_SUFFIX, Kind
from mailvigil.text import MAX_TEXT, clean_text

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# The five bounds on a message. Changing one is a decision for a spec, not a silent edit (007).
# 8 MiB: the 5 MiB attachment cap, plus a third for base64, plus headers and a body.
MAX_MESSAGE_BYTES = 8 * 1024 * 1024
# An 8 MiB message of base64 has about 110,000 lines; more is not a mail.
MAX_LINES = 150_000
# Every part counts, the message itself included. A report mail has 2 or 3; a newsletter, 20.
MAX_PARTS = 50
# Mixed, related, alternative and a signature wrapper make 4. The message itself is depth 0.
MAX_DEPTH = 10
# One header, folded lines joined, in characters. A report's ``Content-Type`` or
# ``Content-Disposition`` is under 200; a line may hold 998 (RFC 5322), and a long name split by
# RFC 2231 takes a few lines. The length is checked before any header is read.
MAX_HEADER_CHARS = 4 * 1024

# How much of the message the parser is given at a time, so a refusal in the middle stops the work.
_FEED_SIZE = 64 * 1024

# ``readline(size)`` reads at most ``size`` bytes, so a line of any length costs a bounded read.
_LINE_READ = 64 * 1024 + 1

# The separator line of an mbox: ``From <sender> <weekday> <month> <day> <time> [zone] <year>``.
# Thunderbird writes ``From - Tue Oct 28 10:00:00 2025``; Apple Mail and Gmail Takeout a sender and
# sometimes a ``+0000`` zone. Matching the whole shape is what keeps ``From me to you`` in a body
# from splitting a message (ADR-3).
_FROM_LINE = re.compile(
    rb"From \S+ (?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) "
    rb"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) [ 0-3]\d "
    rb"\d{2}:\d{2}:\d{2}(?: [+-]\d{4})? \d{4}\s*"
)

# The content types providers use for a report, for the attachment whose name says nothing (ADR-9).
_KIND_BY_TYPE: dict[str, Kind] = {
    "application/zip": "zip",
    "application/x-zip-compressed": "zip",
    "application/gzip": "gz",
    "application/x-gzip": "gz",
    "text/xml": "xml",
    "application/xml": "xml",
}

# What the ``email`` package raises of its own on a message it cannot make sense of. A refusal of
# ours (``ReportRefused``) is not in the list, so it passes through. ``RecursionError`` was the
# structured header parser, which descends once per nested comment or group; it stays as defense in
# depth. ``LookupError`` is also the charset of an RFC 2047 name that Python does not know.
_MESSAGE_ERRORS = (
    email.errors.MessageError,
    ValueError,
    LookupError,
    UnicodeError,
    RecursionError,
)

# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Attachment:
    """
    A part of a message that may be a report.

    Attributes:
        name (str): The file name, decoded and cleaned, at most ``MAX_TEXT`` characters; empty when
            the part has none.
        kind (Kind): How the attachment is stored, from the suffix of the name or else from the
            content type.
        data (bytes): The content with the transfer encoding already undone.
    """

    name: str
    kind: Kind
    data: bytes


# ---------------------------------------------------------------------------
# One message
# ---------------------------------------------------------------------------


class _PartCounter:
    """
    A message factory that refuses the message once it has created too many parts.

    The ``email`` parser builds one object per part as it reads, and calls the factory of its policy
    each time. Counting there is the one hook the standard library offers that runs *during*
    parsing, so a message of a million empty parts is refused after the 51st (ADR-1).
    """

    def __init__(self) -> None:
        """Start a count at zero."""
        self._count = 0

    def __call__(self, policy: Policy[Message[str, str]]) -> Message[str, str]:
        """
        Create the next part.

        Args:
            policy (Policy[Message[str, str]]): The policy of the parser, handed to the part.

        Returns:
            Message[str, str]: An empty part.

        Raises:
            ReportRefused: ``MESSAGE_TOO_COMPLEX`` when this part is past ``MAX_PARTS``.
        """
        self._count += 1
        if self._count > MAX_PARTS:
            raise ReportRefused(Reason.MESSAGE_TOO_COMPLEX, f"more than {MAX_PARTS} parts")
        return Message(policy=policy)


class _BoundedHeaders(Compat32):
    """
    The ``compat32`` policy, refusing a header too long before it is read.

    ``email`` keeps a header as raw text and hands it out each time it is read, through
    ``header_fetch_parse``, during parsing (the content type of every part) as well as after. That
    is the one place every read goes through, so the check cannot be skipped.

    ``compat32`` rather than the default policy: the default one parses a header into a structured
    object on every read, in time that grows much faster than the header (a 4 KiB value took up to a
    tenth of a second, read again about nine times per part), so a message under every cap could
    take tens of seconds. ``compat32`` reads the parameters this module needs (``boundary``,
    ``filename``) in time that grows with the header, and gives the name of an attachment undecoded,
    which ``_filename`` decodes.
    """

    # The stubs give ``Compat32`` the ``str | Header`` it really returns and its base ``Policy`` a
    # plain ``str``, so the override is the stubs' own mismatch.
    def header_fetch_parse(self, name: str, value: str) -> str | Header:  # type: ignore[override]
        """
        Hand out a header the way ``compat32`` does, after checking its length.

        Args:
            name (str): The header name.
            value (str): The raw value, folded lines joined.

        Returns:
            str | Header: What ``compat32`` returns: the value, or a ``Header`` for one holding
                bytes that are not ASCII.

        Raises:
            ReportRefused: ``MESSAGE_TOO_COMPLEX`` for a value over ``MAX_HEADER_CHARS``.
        """
        if len(value) > MAX_HEADER_CHARS:
            raise ReportRefused(
                Reason.MESSAGE_TOO_COMPLEX, f"a header over {MAX_HEADER_CHARS} characters"
            )
        return super().header_fetch_parse(name, value)


def _parse(raw: bytes) -> Message[str, str]:
    """
    Parse a message in chunks, with the part count and the header length in force.

    Args:
        raw (bytes): The message.

    Returns:
        Message[str, str]: The root of the tree.

    Raises:
        ReportRefused: ``MESSAGE_TOO_COMPLEX`` past ``MAX_PARTS`` or ``MAX_HEADER_CHARS``.
    """
    parser: BytesFeedParser[Message[str, str]] = BytesFeedParser(
        policy=_BoundedHeaders(message_factory=_PartCounter())
    )
    for start in range(0, len(raw), _FEED_SIZE):
        parser.feed(raw[start : start + _FEED_SIZE])
    return parser.close()


def _kind_of(name: str, content_type: str) -> Kind | None:
    """
    Decide how an attachment is stored: the suffix of its name first, its content type second.

    Args:
        name (str): The cleaned name, whole (not cut), possibly empty.
        content_type (str): The lower-case ``type/subtype`` of the part.

    Returns:
        Kind | None: The kind, or ``None`` when the part is not a report candidate.
    """
    lowered = name.lower()
    for suffix, kind in KIND_BY_SUFFIX.items():
        if lowered.endswith(suffix):
            return kind
    return _KIND_BY_TYPE.get(content_type)


def _filename(part: Message[str, str]) -> str | None:
    """
    Read the file name of a part, decoded from RFC 2231 and from RFC 2047.

    ``compat32`` undoes RFC 2231 (``filename*=utf-8''...``) but hands an RFC 2047 name
    (``=?utf-8?b?...?=``) as written, which some senders use for an attachment; without this the
    name would end in ``?=`` and the attachment would be ignored.

    Args:
        part (Message[str, str]): A part that holds no other parts.

    Returns:
        str | None: The name, or ``None`` when the part has none. A name that does not decode (a
            charset Python does not know, a damaged word) is returned as written: the content type
            still decides whether the part is a report, and one odd name does not cost the message.
    """
    name = part.get_filename()
    if name is None or "=?" not in name:
        return name
    try:
        return str(make_header(decode_header(name)))
    except (email.errors.HeaderParseError, LookupError, UnicodeError):
        return name


def _candidate(part: Message[str, str]) -> Attachment | None:
    """
    Turn one leaf into an attachment, when it is a report candidate.

    Args:
        part (Message[str, str]): A part that holds no other parts.

    Returns:
        Attachment | None: The attachment, or ``None`` for the body, an image, a signature…
    """
    filename = _filename(part)
    if filename is None and part.get_content_disposition() != "attachment":
        return None
    # The suffix is read from the whole cleaned name: cutting first would drop the ``.zip`` of a
    # long name and the part would be wrongly ignored.
    whole = clean_text(filename or "", len(filename or ""))
    kind = _kind_of(whole, part.get_content_type())
    if kind is None:
        return None
    # A leaf decoded always gives bytes; ``None`` is only for a part that holds other parts.
    data = cast(bytes, part.get_payload(decode=True))
    return Attachment(name=whole[:MAX_TEXT], kind=kind, data=data)


def read_message(raw: bytes) -> tuple[Attachment, ...]:
    """
    Take the report candidates out of one message.

    Args:
        raw (bytes): The message as stored, headers and body.

    Returns:
        tuple[Attachment, ...]: The candidates, in the order they appear; empty when the message
            holds none.

    Raises:
        ReportRefused: ``MESSAGE_TOO_LARGE`` over ``MAX_MESSAGE_BYTES``, ``MESSAGE_TOO_COMPLEX``
            over ``MAX_LINES``, ``MAX_PARTS``, ``MAX_DEPTH`` or ``MAX_HEADER_CHARS``, and
            ``MALFORMED_MESSAGE`` when the ``email`` package fails in a way those do not name.
    """
    if len(raw) > MAX_MESSAGE_BYTES:
        raise ReportRefused(Reason.MESSAGE_TOO_LARGE, f"{len(raw)} bytes")
    # The parser costs time per line, and a byte cap does not see that (ADR-2). Counting is done by
    # the interpreter in C; the larger of the two counts covers a file with old ``\r`` line ends.
    if max(raw.count(b"\n"), raw.count(b"\r")) > MAX_LINES:
        raise ReportRefused(Reason.MESSAGE_TOO_COMPLEX, f"more than {MAX_LINES} lines")

    found: list[Attachment] = []
    try:
        # A stack, not ``walk()``: it must not enter an attached message and it must know the depth
        # (ADR-4). Children go in reversed so they come out in message order.
        stack: list[tuple[Message[str, str], int]] = [(_parse(raw), 0)]
        while stack:
            part, depth = stack.pop()
            if depth > MAX_DEPTH:
                raise ReportRefused(Reason.MESSAGE_TOO_COMPLEX, f"deeper than {MAX_DEPTH} levels")
            if part.get_content_maintype() == "message":
                continue
            if part.is_multipart():
                # ``is_multipart()`` is true only when the payload is a list of parts.
                children = cast("list[Message[str, str]]", part.get_payload())
                stack.extend((child, depth + 1) for child in reversed(children))
                continue
            attachment = _candidate(part)
            if attachment is not None:
                found.append(attachment)
    except _MESSAGE_ERRORS as error:
        raise ReportRefused(Reason.MALFORMED_MESSAGE, type(error).__name__) from None
    return tuple(found)


def read_message_file(path: Path) -> bytes:
    """
    Read an ``.eml`` from disk, refusing it by size before it is opened.

    Args:
        path (Path): The file.

    Returns:
        bytes: The message, at most ``MAX_MESSAGE_BYTES`` long.

    Raises:
        ReportRefused: ``UNREADABLE`` for a file that is missing, not a regular file or not
            permitted, and ``MESSAGE_TOO_LARGE`` over the limit.
    """
    try:
        info = path.stat()
        if not stat.S_ISREG(info.st_mode):
            raise ReportRefused(Reason.UNREADABLE, "not a regular file")
        if info.st_size > MAX_MESSAGE_BYTES:
            raise ReportRefused(Reason.MESSAGE_TOO_LARGE, f"{info.st_size} bytes on disk")
        with path.open("rb") as stream:
            # One byte more than allowed: a file can grow between the ``stat`` and the read.
            data = stream.read(MAX_MESSAGE_BYTES + 1)
    except OSError as error:
        raise ReportRefused(Reason.UNREADABLE, type(error).__name__) from None
    if len(data) > MAX_MESSAGE_BYTES:
        raise ReportRefused(Reason.MESSAGE_TOO_LARGE, "grew while being read")
    return data


# ---------------------------------------------------------------------------
# A mailbox
# ---------------------------------------------------------------------------


def iter_mailbox(stream: BinaryIO) -> Iterator[tuple[int, bytes | ReportRefused]]:
    """
    Split an mbox into its messages, one at a time.

    The stream is read line by line with a bounded read, and only the message in progress is kept,
    so a multi-gigabyte export never sits in memory. A message that grows past
    ``MAX_MESSAGE_BYTES`` stops being stored but is read to its end, and comes out as a refusal.
    Text before the first separator is dropped, unless the file has no separator at all: then the
    whole file is one message, which is how a lone message saved as ``.mbox`` is read and how a
    mailbox in a shape this splitter does not know is refused (RF-05).

    Args:
        stream (BinaryIO): The open mailbox.

    Yields:
        tuple[int, bytes | ReportRefused]: The number of the message, counting from 1, and its
            bytes (without the separator line) or ``MESSAGE_TOO_LARGE``.
    """
    number = 0
    started = False
    buffer = bytearray()
    overflowed = False
    # A read can stop in the middle of a line; the rest of that line is not a line start.
    at_line_start = True

    while line := stream.readline(_LINE_READ):
        if at_line_start and _FROM_LINE.fullmatch(line):
            if started:
                yield number, _finish(buffer, overflowed)
            started = True
            number += 1
            buffer.clear()
            overflowed = False
        elif not overflowed:
            if len(buffer) + len(line) > MAX_MESSAGE_BYTES:
                buffer.clear()
                overflowed = True
            else:
                buffer += line
        at_line_start = line.endswith(b"\n")

    if started:
        yield number, _finish(buffer, overflowed)
    elif buffer or overflowed:
        yield 1, _finish(buffer, overflowed)


def _finish(buffer: bytearray, overflowed: bool) -> bytes | ReportRefused:
    """
    Close the message in progress.

    Args:
        buffer (bytearray): What was stored of it.
        overflowed (bool): Whether it went past ``MAX_MESSAGE_BYTES`` and was not stored.

    Returns:
        bytes | ReportRefused: The message, or the refusal for one that was too large.
    """
    if overflowed:
        return ReportRefused(Reason.MESSAGE_TOO_LARGE, f"more than {MAX_MESSAGE_BYTES} bytes")
    return bytes(buffer)
