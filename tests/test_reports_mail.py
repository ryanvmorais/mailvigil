"""
Tests of the mail message reader (RF-01 to RF-05, RF-09): ``read_message``, ``read_message_file``
and ``iter_mailbox`` (spec 007, stage 2).

Isolation: every message is built in the test, with ``email.message.EmailMessage`` or as raw bytes,
and every mailbox is bytes joined with separator lines; files live under ``tmp_path``. Domains and
addresses are invented (``example.com``, ``.invalid``). Nothing touches the network, an environment
variable or a path outside ``tmp_path``. The hostile cases are the attack itself (a parts bomb, a
message of millions of blank lines, a mailbox with no separators), so a failure there means a
defense is gone; each one expects ``ReportRefused`` and asserts ``.reason``. Limits that are large
on purpose are lowered with ``monkeypatch`` where the case is about the rule, not about the number.
"""

from __future__ import annotations

import base64
import io
import tracemalloc
from collections.abc import Iterator
from email.message import EmailMessage
from email.parser import BytesFeedParser
from pathlib import Path

import pytest

from mailvigil.reports import mail
from mailvigil.reports.errors import Reason, ReportRefused
from mailvigil.reports.mail import (
    MAX_DEPTH,
    MAX_LINES,
    MAX_MESSAGE_BYTES,
    MAX_PARTS,
    Attachment,
    iter_mailbox,
    read_message,
    read_message_file,
)
from mailvigil.reports.reader import read_xml_bytes

# Bytes that are not text, so a base64 round trip that mangled them would show.
_BINARY = bytes(range(256)) * 3
_XML = b"<feedback><a>x</a></feedback>"

# One zip attachment as a hand-written MIME part: the leaf the nesting and bomb cases wrap.
_ZIP_PART = (
    b"Content-Type: application/zip\n"
    b'Content-Disposition: attachment; filename="report.zip"\n'
    b"Content-Transfer-Encoding: base64\n\n"
    b"UEsFBg==\n"
)

# A text part with nothing in it: the cheapest way to add one to the part count.
_EMPTY_PART = b"Content-Type: text/plain\n\nx\n"

# A character that reverses the text after it on a terminal; built with ``chr`` so it stays visible.
_BIDI_OVERRIDE = chr(0x202E)

# The first line of a message inside a mailbox, in the shape Thunderbird writes.
_FROM = b"From - Tue Oct 28 10:00:00 2025\n"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mail(*attachments: tuple[bytes, str, str, str | None]) -> bytes:
    """
    Build a message with a text body and attachments, as a mail client would.

    Args:
        *attachments (tuple[bytes, str, str, str | None]): ``(data, maintype, subtype, filename)``
            for each attachment; a ``filename`` of ``None`` leaves the attachment unnamed.

    Returns:
        bytes: The message as written to an ``.eml``.
    """
    message = EmailMessage()
    message["From"] = "dmarc@reports.example.invalid"
    message["To"] = "postmaster@example.com"
    message["Subject"] = "Report domain: example.com"
    message.set_content("This is an aggregate report.")
    for data, maintype, subtype, filename in attachments:
        message.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
    return message.as_bytes()


def _raw(content_type: str, body: bytes) -> bytes:
    """
    Build a message by hand, headers and body, with no library deciding the structure.

    Args:
        content_type (str): The ``Content-Type`` header value of the message.
        body (bytes): What follows the blank line after the headers.

    Returns:
        bytes: The message.
    """
    head = (
        f"From: dmarc@reports.example.invalid\nMIME-Version: 1.0\nContent-Type: {content_type}\n\n"
    )
    return head.encode("ascii") + body


def _multipart(parts: list[bytes], boundary: str = "BND") -> bytes:
    """
    Wrap parts in a ``multipart/mixed`` message.

    Args:
        parts (list[bytes]): Each part: its headers, a blank line and its body.
        boundary (str, optional): The boundary string. Default: ``BND``.

    Returns:
        bytes: The message.
    """
    body = b"".join(f"--{boundary}\n".encode() + part + b"\n" for part in parts)
    return _raw(f"multipart/mixed; boundary={boundary}", body + f"--{boundary}--\n".encode())


def _nested(levels: int) -> bytes:
    """
    Build a message whose one zip leaf sits ``levels`` multiparts deep.

    Args:
        levels (int): How many multiparts wrap the leaf; the leaf is at depth ``levels``.

    Returns:
        bytes: The message.
    """
    inner = _ZIP_PART
    for level in range(levels):
        boundary = f"b{level}"
        inner = (
            f"Content-Type: multipart/mixed; boundary={boundary}\n\n--{boundary}\n".encode()
            + inner
            + f"\n--{boundary}--\n".encode()
        )
    return b"From: dmarc@reports.example.invalid\nMIME-Version: 1.0\n" + inner


def _refusal(raw: bytes) -> Reason:
    """
    Read a message that must be refused.

    Args:
        raw (bytes): The message.

    Returns:
        Reason: Why ``read_message`` refused it.
    """
    with pytest.raises(ReportRefused) as caught:
        read_message(raw)
    return caught.value.reason


def _fed(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """
    Record every chunk the feed parser is given, so a test can say "never parsed" without a clock.

    Args:
        monkeypatch (pytest.MonkeyPatch): The fixture that undoes the patch.

    Returns:
        list[int]: The size of each chunk fed; empty while the parser is untouched.
    """
    sizes: list[int] = []
    original = BytesFeedParser.feed

    def spy(self: BytesFeedParser, data: bytes) -> None:
        sizes.append(len(data))
        original(self, data)

    monkeypatch.setattr(BytesFeedParser, "feed", spy)
    return sizes


def _mailbox(*messages: bytes, separator: bytes = _FROM) -> bytes:
    """
    Join messages into a mailbox, each after a separator line and followed by a blank line.

    Args:
        *messages (bytes): The messages.
        separator (bytes, optional): The line that starts each one. Default: Thunderbird's.

    Returns:
        bytes: The mailbox.
    """
    return b"".join(separator + message + b"\n" for message in messages)


def _split(data: bytes) -> list[tuple[int, bytes | ReportRefused]]:
    """
    Split a mailbox held in memory.

    Args:
        data (bytes): The mailbox.

    Returns:
        list[tuple[int, bytes | ReportRefused]]: What ``iter_mailbox`` yields, in order.
    """
    return list(iter_mailbox(io.BytesIO(data)))


def _reasons(items: list[tuple[int, bytes | ReportRefused]]) -> list[Reason | None]:
    """
    Summarize a split: the reason of each refused message and ``None`` for each one read.

    Args:
        items (list[tuple[int, bytes | ReportRefused]]): The output of ``_split``.

    Returns:
        list[Reason | None]: One entry per message, in order.
    """
    return [item.reason if isinstance(item, ReportRefused) else None for _, item in items]


# ---------------------------------------------------------------------------
# read_message: which attachments are candidates (RF-01, RF-03, RF-04)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("filename", "maintype", "subtype", "kind"),
    [
        ("report.zip", "application", "zip", "zip"),
        ("report.xml.gz", "application", "gzip", "gz"),
        ("report.xml", "application", "xml", "xml"),
    ],
)
def test_each_form_of_report_is_one_attachment(
    filename: str, maintype: str, subtype: str, kind: str
) -> None:
    """A zip, a gzip and an xml each give one attachment with the bytes that were put in."""
    found = read_message(_mail((_BINARY, maintype, subtype, filename)))
    # ``kind`` arrives from the parametrization as a plain ``str``; the model wants the Literal.
    expected = Attachment(name=filename, kind=kind, data=_BINARY)  # type: ignore[arg-type]
    assert found == (expected,)


def test_suffix_is_matched_without_regard_to_case() -> None:
    """``REPORT.ZIP`` is read like ``report.zip``."""
    found = read_message(_mail((_BINARY, "application", "octet-stream", "REPORT.ZIP")))
    assert [(a.name, a.kind) for a in found] == [("REPORT.ZIP", "zip")]


def test_extended_parameter_name_is_decoded_before_the_suffix() -> None:
    """RFC 2231: ``filename*=utf-8''...`` is decoded to the real name."""
    found = read_message(_mail((_BINARY, "application", "octet-stream", "relatório.zip")))
    assert [(a.name, a.kind) for a in found] == [("relatório.zip", "zip")]


def test_encoded_word_name_is_decoded_before_the_suffix() -> None:
    """RFC 2047: ``=?utf-8?b?...?=`` is decoded to the real name."""
    word = base64.b64encode("relatório.zip".encode()).decode()
    part = (
        b"Content-Type: application/octet-stream\n"
        + f'Content-Disposition: attachment; filename="=?utf-8?b?{word}?="\n'.encode()
        + b"Content-Transfer-Encoding: base64\n\nUEsFBg==\n"
    )
    found = read_message(_multipart([part]))
    assert [(a.name, a.kind) for a in found] == [("relatório.zip", "zip")]


@pytest.mark.parametrize(
    ("maintype", "subtype", "kind"),
    [
        ("application", "zip", "zip"),
        ("application", "x-zip-compressed", "zip"),
        ("application", "gzip", "gz"),
        ("application", "x-gzip", "gz"),
        ("text", "xml", "xml"),
        ("application", "xml", "xml"),
    ],
)
def test_unnamed_attachment_takes_its_kind_from_the_content_type(
    maintype: str, subtype: str, kind: str
) -> None:
    """With no name, each of the six report content types gives its kind (ADR-9)."""
    found = read_message(_mail((_XML, maintype, subtype, None)))
    assert [(a.name, a.kind, a.data) for a in found] == [("", kind, _XML)]


def test_unknown_suffix_with_a_known_content_type_is_a_candidate() -> None:
    """A name that says nothing falls back to the content type."""
    found = read_message(_mail((_BINARY, "application", "zip", "report.bin")))
    assert [(a.name, a.kind) for a in found] == [("report.bin", "zip")]


def test_name_decides_over_the_content_type() -> None:
    """``.gz`` with ``application/octet-stream``, the usual case, is a gzip."""
    found = read_message(_mail((_BINARY, "application", "octet-stream", "report.xml.gz")))
    assert [a.kind for a in found] == ["gz"]


def test_nothing_else_is_a_candidate() -> None:
    """A text body, an image, a calendar and an unnamed binary give nothing, and no error."""
    raw = _mail(
        (b"\x89PNG", "image", "png", "logo.png"),
        (b"BEGIN:VCALENDAR", "text", "calendar", "invite.ics"),
        (b"\x00\x01", "application", "octet-stream", None),
    )
    assert read_message(raw) == ()


def test_plain_text_message_gives_nothing() -> None:
    """A message with no attachment gives an empty tuple, not a refusal."""
    assert read_message(b"Subject: hello\n\nJust text.\n") == ()


def test_inline_xml_body_is_not_an_attachment() -> None:
    """XML in the body of the message is never read (Non-goals): only attachments count."""
    raw = _raw("text/xml", b"<feedback/>\n")
    assert read_message(raw) == ()


def test_two_candidates_come_in_message_order() -> None:
    """Every candidate is returned, in the order they appear."""
    raw = _mail(
        (b"first", "application", "zip", "a.zip"),
        (b"second", "application", "gzip", "b.xml.gz"),
    )
    assert [a.name for a in read_message(raw)] == ["a.zip", "b.xml.gz"]


def test_forwarded_message_is_not_entered() -> None:
    """A ``message/rfc822`` attachment is skipped; the outer message's own attachment is read."""
    inner = EmailMessage()
    inner["Subject"] = "forwarded"
    inner.set_content("body")
    inner.add_attachment(b"inner", maintype="application", subtype="zip", filename="inner.zip")
    outer = EmailMessage()
    outer["Subject"] = "fwd"
    outer.set_content("see attached")
    outer.add_attachment(b"outer", maintype="application", subtype="zip", filename="outer.zip")
    outer.add_attachment(inner)
    assert [a.name for a in read_message(outer.as_bytes())] == ["outer.zip"]


def test_signed_wrapper_is_read_normally() -> None:
    """``multipart/signed`` is a wrapper: the report inside is read, the signature is not."""
    content = _multipart([_EMPTY_PART, _ZIP_PART], boundary="M")
    inner = content.split(b"\n\n", 1)[1]
    body = (
        b"--S\nContent-Type: multipart/mixed; boundary=M\n\n"
        + inner
        + b"\n--S\nContent-Type: application/pgp-signature; name=signature.asc\n\n"
        + b"-----BEGIN PGP SIGNATURE-----\n--S--\n"
    )
    raw = _raw('multipart/signed; protocol="application/pgp-signature"; boundary=S', body)
    assert [a.name for a in read_message(raw)] == ["report.zip"]


def test_base64_and_quoted_printable_are_undone() -> None:
    """The transfer encoding is removed whatever it is; the bytes are the document."""
    message = EmailMessage()
    message.set_content("body")
    xml = "<a>café</a>"
    message.add_attachment(xml, subtype="xml", filename="q.xml", cte="quoted-printable")
    message.add_attachment(_BINARY, maintype="application", subtype="zip", filename="b.zip")
    found = read_message(message.as_bytes())
    # ``EmailMessage`` ends a text part with a line break, so the decoded text has one too.
    assert [(a.name, a.data) for a in found] == [
        ("q.xml", xml.encode() + b"\n"),
        ("b.zip", _BINARY),
    ]


def test_crlf_line_endings_are_read() -> None:
    """A message written with CRLF, as it travels, reads the same."""
    raw = _mail((_BINARY, "application", "zip", "report.zip")).replace(b"\n", b"\r\n")
    assert [a.data for a in read_message(raw)] == [_BINARY]


# ---------------------------------------------------------------------------
# read_message: hostile input (RF-04, RF-05, RF-09)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("unit", [b"\n", b"X-Filler: yes\n"], ids=["blank lines", "headers"])
def test_too_many_lines_is_refused_before_any_parsing(
    unit: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    """More than ``MAX_LINES`` lines is refused and the parser is never fed."""
    sizes = _fed(monkeypatch)
    assert _refusal(unit * (MAX_LINES + 1)) is Reason.MESSAGE_TOO_COMPLEX
    assert sizes == []


def test_carriage_return_only_lines_are_counted_too() -> None:
    """Old Mac line endings do not hide a flood of lines."""
    assert _refusal(b"\r" * (MAX_LINES + 1)) is Reason.MESSAGE_TOO_COMPLEX


def test_exactly_the_line_limit_is_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The limit is "more than": a message of ``MAX_LINES`` lines goes to the parser."""
    sizes = _fed(monkeypatch)
    assert read_message(b"\n" * MAX_LINES) == ()
    assert sizes


def test_message_over_the_byte_limit_is_refused_before_parsing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``read_message`` also checks the size, for a caller that holds raw bytes (spec 009)."""
    sizes = _fed(monkeypatch)
    monkeypatch.setattr(mail, "MAX_MESSAGE_BYTES", 100)
    assert _refusal(b"x" * 101) is Reason.MESSAGE_TOO_LARGE
    assert sizes == []


def test_parts_bomb_is_refused() -> None:
    """More than ``MAX_PARTS`` parts is refused; ``MAX_PARTS`` including the message is not."""
    assert read_message(_multipart([_EMPTY_PART] * (MAX_PARTS - 1))) == ()
    assert _refusal(_multipart([_EMPTY_PART] * MAX_PARTS)) is Reason.MESSAGE_TOO_COMPLEX
    assert _refusal(_multipart([_EMPTY_PART] * (MAX_PARTS + 1))) is Reason.MESSAGE_TOO_COMPLEX


def test_parts_bomb_stops_the_parser_early(monkeypatch: pytest.MonkeyPatch) -> None:
    """The count is made while parsing: 20,000 parts are refused after the 51st, in one chunk."""
    created: list[int] = []
    original = mail._PartCounter.__call__

    def counted(self: mail._PartCounter, policy: object) -> EmailMessage:
        created.append(1)
        return original(self, policy)  # type: ignore[arg-type]  # the fake takes ``object``

    monkeypatch.setattr(mail._PartCounter, "__call__", counted)
    assert _refusal(_multipart([_EMPTY_PART] * 20000)) is Reason.MESSAGE_TOO_COMPLEX
    assert len(created) == MAX_PARTS + 1


def test_nesting_past_the_depth_limit_is_refused() -> None:
    """A leaf at depth ``MAX_DEPTH`` is read; one level deeper is refused."""
    assert [a.name for a in read_message(_nested(MAX_DEPTH))] == ["report.zip"]
    assert _refusal(_nested(MAX_DEPTH + 1)) is Reason.MESSAGE_TOO_COMPLEX


def test_nesting_of_two_thousand_levels_is_refused_not_a_crash() -> None:
    """Deep nesting is a refusal with a reason, never a ``RecursionError``."""
    assert _refusal(_nested(2000)) is Reason.MESSAGE_TOO_COMPLEX


def test_parser_failure_is_a_malformed_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """Whatever the ``email`` package raises of its own is ``malformed_message``."""

    def broken(self: mail._PartCounter, policy: object) -> EmailMessage:
        raise ValueError("boom")

    monkeypatch.setattr(mail._PartCounter, "__call__", broken)
    assert _refusal(_mail((_BINARY, "application", "zip", "r.zip"))) is Reason.MALFORMED_MESSAGE


def test_truncated_base64_reaches_the_reader_which_refuses_it() -> None:
    """The ``email`` package is lenient; the damaged archive is refused where archives are."""
    encoded = base64.b64encode(_BINARY).decode()[:-7]
    part = (
        b"Content-Type: application/zip\nContent-Disposition: attachment; filename=r.zip\n"
        b"Content-Transfer-Encoding: base64\n\n" + encoded.encode() + b"\n"
    )
    (attachment,) = read_message(_multipart([part]))
    with pytest.raises(ReportRefused) as caught:
        read_xml_bytes(attachment.data, attachment.kind)
    assert caught.value.reason is Reason.NOT_AN_ARCHIVE


def test_unknown_transfer_encoding_reaches_the_reader_which_refuses_it() -> None:
    """An encoding nobody knows leaves the text as it is, and the reader refuses it."""
    part = (
        b"Content-Type: application/zip\nContent-Disposition: attachment; filename=r.zip\n"
        b"Content-Transfer-Encoding: x-unheard-of\n\nnot a zip at all\n"
    )
    (attachment,) = read_message(_multipart([part]))
    with pytest.raises(ReportRefused) as caught:
        read_xml_bytes(attachment.data, attachment.kind)
    assert caught.value.reason is Reason.NOT_AN_ARCHIVE


def test_name_is_cleaned_and_cut() -> None:
    """Control characters and a bidirectional override are dropped; at most 255 characters stay."""
    raw = _mail((_BINARY, "application", "zip", "re\x07port" + _BIDI_OVERRIDE + "gnp.zip"))
    (attachment,) = read_message(raw)
    assert attachment.name == "reportgnp.zip"
    long = _mail((_BINARY, "application", "octet-stream", "a" * 400 + ".zip"))
    (attachment,) = read_message(long)
    assert attachment.name == "a" * 255
    assert attachment.kind == "zip"


# ---------------------------------------------------------------------------
# read_message_file (RF-05)
# ---------------------------------------------------------------------------


def test_message_file_is_read_as_bytes(tmp_path: Path) -> None:
    """An ``.eml`` gives its bytes."""
    path = tmp_path / "report.eml"
    path.write_bytes(_mail((_BINARY, "application", "zip", "r.zip")))
    assert read_message_file(path) == path.read_bytes()


def test_file_of_exactly_the_limit_is_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The limit is "over": a file of exactly ``MAX_MESSAGE_BYTES`` passes."""
    monkeypatch.setattr(mail, "MAX_MESSAGE_BYTES", 100)
    path = tmp_path / "exact.eml"
    path.write_bytes(b"x" * 100)
    assert read_message_file(path) == b"x" * 100


def test_file_over_the_limit_is_refused_before_it_is_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The size comes from ``stat``; the file is not opened."""
    monkeypatch.setattr(mail, "MAX_MESSAGE_BYTES", 100)
    path = tmp_path / "big.eml"
    path.write_bytes(b"x" * 101)
    opened: list[Path] = []
    original = Path.open

    def spy(self: Path, *args: object, **kwargs: object) -> object:
        opened.append(self)
        return original(self, *args, **kwargs)  # type: ignore[call-overload]  # args typed ``object``

    monkeypatch.setattr(Path, "open", spy)
    with pytest.raises(ReportRefused) as caught:
        read_message_file(path)
    assert caught.value.reason is Reason.MESSAGE_TOO_LARGE
    assert opened == []


def test_file_that_grows_after_the_stat_is_still_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file that lied to ``stat`` is caught by the bounded read."""
    monkeypatch.setattr(mail, "MAX_MESSAGE_BYTES", 100)
    path = tmp_path / "grows.eml"
    path.write_bytes(b"x" * 101)

    class _Small:
        """A stat result that claims a small file."""

        st_mode = path.stat().st_mode
        st_size = 10

    monkeypatch.setattr(Path, "stat", lambda self, **_: _Small())
    with pytest.raises(ReportRefused) as caught:
        read_message_file(path)
    assert caught.value.reason is Reason.MESSAGE_TOO_LARGE


def test_directory_and_missing_file_are_unreadable(tmp_path: Path) -> None:
    """Neither a directory nor a file that is not there is read."""
    for path in (tmp_path, tmp_path / "missing.eml"):
        with pytest.raises(ReportRefused) as caught:
            read_message_file(path)
        assert caught.value.reason is Reason.UNREADABLE


# ---------------------------------------------------------------------------
# iter_mailbox (RF-02, RF-05)
# ---------------------------------------------------------------------------


def test_messages_come_in_order_with_numbers_from_one() -> None:
    """Each message is yielded without its separator, numbered from 1."""
    data = _mailbox(b"Subject: one\n\nfirst\n", b"Subject: two\n\nsecond\n", b"Subject: 3\n\nx\n")
    assert _split(data) == [
        (1, b"Subject: one\n\nfirst\n\n"),
        (2, b"Subject: two\n\nsecond\n\n"),
        (3, b"Subject: 3\n\nx\n\n"),
    ]


def test_text_before_the_first_separator_is_dropped() -> None:
    """A preamble is not a message when real messages follow."""
    assert _split(b"some preamble\n" + _mailbox(b"Subject: one\n\nx\n")) == [
        (1, b"Subject: one\n\nx\n\n")
    ]


@pytest.mark.parametrize(
    "separator",
    [
        b"From - Tue Oct 28 10:00:00 2025\n",
        b"From dmarc@reports.example.invalid Tue Oct 28 10:00:00 2025\n",
        b"From 17890@xxx Tue Oct 28 10:00:00 +0000 2025\n",
        b"From - Tue Oct  8 10:00:00 2025\r\n",
    ],
    ids=["thunderbird", "with sender", "with zone", "crlf and padded day"],
)
def test_the_usual_separator_shapes_split(separator: bytes) -> None:
    """The shapes mail clients write all start a message."""
    data = _mailbox(b"Subject: one\n\nx\n", b"Subject: two\n\ny\n", separator=separator)
    assert [number for number, _ in _split(data)] == [1, 2]


def test_from_inside_a_body_does_not_split() -> None:
    """``From me to you`` is text, not a separator."""
    message = b"Subject: one\n\nFrom me to you\nFrom: not a separator either\nbye\n"
    assert _split(_mailbox(message)) == [(1, message + b"\n")]


def test_line_longer_than_the_read_size_does_not_split() -> None:
    """A long line is read in pieces; a piece that starts with ``From `` is not a line start."""
    long_line = b"y" * mail._LINE_READ + _FROM.rstrip(b"\n") + b" tail\n"
    message = b"Subject: one\n\n" + long_line
    assert _split(_mailbox(message)) == [(1, message + b"\n")]


def test_oversized_message_among_good_ones_costs_one_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The big one is yielded as a refusal and the next is still read."""
    monkeypatch.setattr(mail, "MAX_MESSAGE_BYTES", 200)
    big = b"Subject: big\n\n" + b"x" * 80 + b"\n" + b"y" * 80 + b"\n" + b"z" * 80 + b"\n"
    items = _split(_mailbox(b"Subject: a\n\nx\n", big, b"Subject: c\n\nx\n"))
    assert _reasons(items) == [None, Reason.MESSAGE_TOO_LARGE, None]
    assert [number for number, _ in items] == [1, 2, 3]


def test_mailbox_with_no_separator_is_one_refused_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An export whose lines are not recognized is refused, and memory stays near the limit."""
    limit = 1024 * 1024
    monkeypatch.setattr(mail, "MAX_MESSAGE_BYTES", limit)
    stream = io.BytesIO((b"x" * 70 + b"\n") * (10 * limit // 71))
    tracemalloc.start()
    try:
        items = list(iter_mailbox(stream))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert _reasons(items) == [Reason.MESSAGE_TOO_LARGE]
    assert peak < 3 * limit


def test_small_file_with_no_separator_is_one_message() -> None:
    """A single message saved with the ``.mbox`` suffix is still read."""
    message = b"Subject: one\n\nx\n"
    assert _split(message) == [(1, message)]


def test_empty_stream_yields_nothing() -> None:
    """No bytes, no messages."""
    assert _split(b"") == []


def test_crlf_mailbox_is_split() -> None:
    """A mailbox written with CRLF splits like one written with LF."""
    data = _mailbox(
        b"Subject: a\r\n\r\nx\r\n", b"Subject: b\r\n\r\ny\r\n", separator=_FROM[:-1] + b"\r\n"
    )
    assert [number for number, _ in _split(data)] == [1, 2]


def test_mailbox_messages_are_read_by_read_message() -> None:
    """The two halves fit: what the splitter yields is what the reader takes."""
    report = _mail((_BINARY, "application", "zip", "report.zip"))
    items = _split(_mailbox(b"Subject: hi\n\nnothing\n", report))
    found: list[tuple[int, tuple[Attachment, ...]]] = []
    for number, item in items:
        assert isinstance(item, bytes)
        found.append((number, read_message(item)))
    assert [(number, [a.name for a in atts]) for number, atts in found] == [
        (1, []),
        (2, ["report.zip"]),
    ]


def test_iter_mailbox_is_lazy() -> None:
    """The first message is yielded before the rest of the stream is read."""
    stream = io.BytesIO(_mailbox(b"Subject: a\n\nx\n", b"Subject: b\n\ny\n"))
    iterator: Iterator[tuple[int, bytes | ReportRefused]] = iter_mailbox(stream)
    next(iterator)
    assert stream.tell() < len(stream.getvalue())


def test_limits_are_the_closed_values() -> None:
    """Changing a limit is a spec decision (design table), so the values are pinned."""
    assert (MAX_MESSAGE_BYTES, MAX_LINES, MAX_PARTS, MAX_DEPTH) == (
        8 * 1024 * 1024,
        150_000,
        50,
        10,
    )
