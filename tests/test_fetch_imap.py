"""
Tests of the IMAP adapter (spec 009, stage 4: RF-01 to RF-05, RF-10, RNF-01, RNF-02, ADR-2 to
ADR-5).

Isolation: nothing here reaches a network. The pure helpers take plain values; the connection is
tested with ``_BoundedSsl`` replaced by a recorder; the bounds and the commands on the wire run over
a ``socket.socketpair()`` joined to a scripted server in a thread (``imap_peer.py``). Hosts end in
``.invalid``, users and passwords are invented and the password is a canary that must appear in no
output (RNF-06, RNF-02).
"""

from __future__ import annotations

import base64
import imaplib
import locale
import re
import socket
import ssl
import threading
from collections.abc import Callable, Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from fetch_helpers import ManualClock
from imap_peer import (
    CANARY,
    Handler,
    PairedImap,
    ScriptedPeer,
    literal_fetch,
    ok,
    open_mailbox,
    refuse,
)
from mailvigil.fetch import imap
from mailvigil.fetch.errors import DETAIL_LIMIT, FetchReason, FetchRefused
from mailvigil.fetch.imap import (
    ImapMailbox,
    _Bounds,
    _LineTooLong,
    build_context,
    connect,
    encode_folder,
    format_since,
    parse_search,
    parse_sizes,
    parse_validity,
    quote,
)
from mailvigil.fetch.model import (
    LINE_LIMIT,
    LITERAL_OTHER,
    SIZE_BATCH,
    UID_MAX,
    SearchResult,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# A deadline far enough that no test reaches it by accident.
_FAR = 1_000_000.0


@pytest.fixture
def peers() -> Iterator[Callable[..., ScriptedPeer]]:
    """
    Hand out scripted servers and close every one at the end of the test.

    Yields:
        Callable[..., ScriptedPeer]: Builds a peer from a handler and an optional greeting.
    """
    made: list[ScriptedPeer] = []

    def make(handler: Handler | None = None, **options: Any) -> ScriptedPeer:
        peer = ScriptedPeer(handler, **options)
        made.append(peer)
        return peer

    yield make
    for peer in made:
        peer.close()


def _script(*rules: tuple[bytes, bytes | Callable[[bytes, ScriptedPeer], bytes | None]]) -> Handler:
    """
    Build a handler that answers by what the command line contains.

    Args:
        *rules (tuple): Pairs of a fragment of a command and its answer: untagged lines, which get
            the tagged ``OK`` after them, or a function of the tag and the peer returning the whole
            answer (``None`` for silence). The first fragment found wins; a command no rule matches
            gets a plain ``OK``.

    Returns:
        Handler: The handler.
    """

    def handler(tag: bytes, line: bytes, peer: ScriptedPeer) -> bytes | None:
        for needle, reply in rules:
            if needle in line:
                return reply(tag, peer) if callable(reply) else ok(tag, reply)
        return ok(tag)

    return handler


def _refused(call: Callable[[], object]) -> FetchRefused:
    """
    Run a call that must be refused.

    Args:
        call (Callable[[], object]): The call.

    Returns:
        FetchRefused: What it raised.
    """
    with pytest.raises(FetchRefused) as caught:
        call()
    return caught.value


def _all_words(peer: ScriptedPeer) -> bytes:
    """
    Join everything the client sent after the login.

    Args:
        peer (ScriptedPeer): The scripted server, already closed.

    Returns:
        bytes: Every command line after the ``LOGIN`` one.
    """
    lines = peer.commands()
    start = next(i for i, line in enumerate(lines) if line.startswith(b"LOGIN"))
    return b"\n".join(lines[start + 1 :])


# ---------------------------------------------------------------------------
# Folder names and quoting
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "encoded"),
    [
        ("INBOX", "INBOX"),
        ("Sent Items", "Sent Items"),
        ("Entwürfe", "Entw&APw-rfe"),  # the RFC's own example
        ("~peter/mail/台北/日本語", "~peter/mail/&U,BTFw-/&ZeVnLIqe-"),  # RFC 3501, 5.1.3
        ("A&B", "A&-B"),
        ("&", "&-"),
        ("ñáé", "&APEA4QDp-"),  # one run of three characters
        ("😀", "&2D3eAA-"),  # outside the BMP: a surrogate pair
        ("台北", "&U,BTFw-"),  # a "/" of the base64 becomes ","
        ("a é b é", "a &AOk- b &AOk-"),  # two runs
    ],
)
def test_encode_folder_is_modified_utf7(name: str, encoded: str) -> None:
    assert encode_folder(name) == encoded


@pytest.mark.parametrize("name", ["a\nb", "a\rb", "a\x00b", "a\tb", "\x7f", "caf\x1bé"])
def test_encode_folder_refuses_a_control_character(name: str) -> None:
    assert _refused(lambda: encode_folder(name)).reason is FetchReason.FOLDER_NOT_FOUND


def test_encode_folder_refuses_a_lone_surrogate() -> None:
    assert _refused(lambda: encode_folder("a\ud800b")).reason is FetchReason.FOLDER_NOT_FOUND


def test_quote_escapes_backslash_and_double_quote() -> None:
    assert quote('a"b\\c') == '"a\\"b\\\\c"'
    assert quote("plain") == '"plain"'


# ---------------------------------------------------------------------------
# The SINCE date
# ---------------------------------------------------------------------------


class _NoStrftime(date):
    """A date whose ``strftime`` fails, as a locale-dependent month name would."""

    def strftime(self, format: str) -> str:
        raise AssertionError("the SINCE date must not depend on the locale")


@pytest.mark.parametrize(
    ("day", "text"),
    [
        (date(2026, 10, 28), "28-Oct-2026"),
        (date(2026, 1, 5), "05-Jan-2026"),
        (date(2026, 12, 31), "31-Dec-2026"),
        (date(999, 3, 1), "01-Mar-0999"),
    ],
)
def test_format_since_is_dd_mon_yyyy_in_english(day: date, text: str) -> None:
    assert format_since(day) == text


def test_format_since_never_calls_strftime() -> None:
    assert format_since(_NoStrftime(2026, 2, 3)) == "03-Feb-2026"


def test_format_since_ignores_the_locale() -> None:
    old = locale.setlocale(locale.LC_TIME)
    for name in ("pt_BR.UTF-8", "pt_BR", "Portuguese_Brazil.1252", "de_DE.UTF-8"):
        try:
            locale.setlocale(locale.LC_TIME, name)
        except locale.Error:
            continue
        try:
            assert format_since(date(2026, 2, 3)) == "03-Feb-2026"
        finally:
            locale.setlocale(locale.LC_TIME, old)
        return
    pytest.skip("no non-English locale is installed")


# ---------------------------------------------------------------------------
# The parsers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "uids", "dropped"),
    [
        ([b"1 5 3"], (1, 3, 5), 0),
        ([b"4294967295"], (UID_MAX,), 0),
        ([b"7", b"2 9"], (2, 7, 9), 0),  # several lines are one answer
        ([b""], (), 0),
        ([None], (), 0),
        (None, (), 0),
        ([b"2 2"], (2, 2), 0),  # a repeated UID is kept; the loop counts it
        ([b"1 0 3"], (1, 3), 1),
        ([b"1 -4 3"], (1, 3), 1),
        ([b"1 +4 3"], (1, 3), 1),
        ([b"1 0x10 3"], (1, 3), 1),
        ([b"1 2.5 3"], (1, 3), 1),
        ([b"1 4294967296 3"], (1, 3), 1),  # one over UID_MAX
        ([b"1 " + b"9" * 10_000 + b" 3"], (1, 3), 1),  # int() must never see it
        ([b"1 \xd9\xa3 3"], (1, 3), 1),  # a non-ASCII digit
        ([b"abc 1"], (1,), 1),
        ([(b"1 {3}", b"2 3")], (), 0),  # a literal is not a SEARCH answer
    ],
)
def test_parse_search(data: Any, uids: tuple[int, ...], dropped: int) -> None:
    assert parse_search(data) == SearchResult(uids, dropped)


@pytest.mark.parametrize(
    ("data", "sizes"),
    [
        ([b"1 (UID 10 RFC822.SIZE 500)"], {10: 500}),
        ([b"1 (RFC822.SIZE 500 UID 10)"], {10: 500}),  # attributes in the other order
        ([b"1 (UID 10 RFC822.SIZE 500)", b"2 (UID 11 RFC822.SIZE 0)"], {10: 500, 11: 0}),
        ([b"1 (UID 10)"], {}),  # only one of the two numbers
        ([b"1 (RFC822.SIZE 500)"], {}),
        ([b"1 (UID 10 RFC822.SIZE 500 FLAGS (\\Seen))"], {}),  # not exactly those attributes
        ([b"garbage"], {}),
        ([b"1 (UID x RFC822.SIZE 500)"], {}),
        ([b"1 (UID 0 RFC822.SIZE 500)"], {}),  # zero is no UID
        ([b"1 (UID 99 RFC822.SIZE 500)"], {}),  # not asked about
        ([b"1 (UID 10 RFC822.SIZE " + b"9" * 10_000 + b")"], {}),
        ([None], {}),
        (None, {}),
        ([(b"1 (UID 10 RFC822.SIZE {2}", b"55")], {}),
    ],
)
def test_parse_sizes(data: Any, sizes: dict[int, int]) -> None:
    assert parse_sizes(data, {10, 11}) == sizes


@pytest.mark.parametrize(
    ("data", "validity"),
    [([b"3857529045"], 3857529045), ([b"1"], 1), ([b"4294967295"], UID_MAX), ([b"9", b"12"], 12)],
)
def test_parse_validity(data: Any, validity: int) -> None:
    assert parse_validity(data) == validity


@pytest.mark.parametrize(
    "data",
    [[None], None, [], [b"0"], [b"-3"], [b"4294967296"], [b"1" * 5000], [b"abc"], [(b"1", b"2")]],
)
def test_parse_validity_refuses_what_is_not_a_validity_number(data: Any) -> None:
    assert _refused(lambda: parse_validity(data)).reason is FetchReason.PROTOCOL_ERROR


# ---------------------------------------------------------------------------
# The connection: context, errors, login
# ---------------------------------------------------------------------------


class _Recorder:
    """What the replaced ``_BoundedSsl`` saw."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int, dict[str, Any]]] = []
        self.logins: list[tuple[str, str]] = []
        self.plain_responses: list[bytes] = []
        self.capabilities: tuple[str, ...] = ("IMAP4REV1", "AUTH=PLAIN")
        self.shutdowns = 0
        self.raises: BaseException | None = None
        self.login_raises: BaseException | None = None


@pytest.fixture
def fake_ssl(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    """
    Replace the TLS connection by one that records and opens nothing.

    Args:
        monkeypatch (pytest.MonkeyPatch): The fixture.

    Returns:
        _Recorder: What the fake saw; set ``raises`` or ``login_raises`` to script a failure.
    """
    recorder = _Recorder()

    class Fake:
        def __init__(self, host: str, port: int, **options: Any) -> None:
            recorder.calls.append((host, port, options))
            self.capabilities = recorder.capabilities
            if recorder.raises is not None:
                raise recorder.raises

        def login(self, user: str, password: str) -> None:
            recorder.logins.append((user, password))
            if recorder.login_raises is not None:
                raise recorder.login_raises

        def authenticate(self, mechanism: str, authobject: Callable[[bytes], bytes]) -> None:
            assert mechanism == "PLAIN"
            recorder.plain_responses.append(authobject(b""))
            if recorder.login_raises is not None:
                raise recorder.login_raises

        def shutdown(self) -> None:
            recorder.shutdowns += 1

    monkeypatch.setattr(imap, "_BoundedSsl", Fake)
    return recorder


def _connect(**override: Any) -> ImapMailbox:
    """
    Call ``connect`` with invented values.

    Args:
        **override (Any): Arguments to change.

    Returns:
        ImapMailbox: What ``connect`` returned.
    """
    arguments: dict[str, Any] = {
        "host": "mail.invalid",
        "port": 993,
        "user": "reader",
        "password": CANARY,
        "clock": ManualClock(),
        "deadline": _FAR,
    }
    arguments.update(override)
    return connect(**arguments)


def test_the_context_verifies_the_certificate_and_the_host_name() -> None:
    context = build_context()
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert context.minimum_version >= ssl.TLSVersion.TLSv1_2


def test_a_loosened_minimum_version_is_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    def loose() -> ssl.SSLContext:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = ssl.TLSVersion.MINIMUM_SUPPORTED
        return context

    monkeypatch.setattr(ssl, "create_default_context", loose)
    assert build_context().minimum_version == ssl.TLSVersion.TLSv1_2


def test_a_stricter_minimum_version_is_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    def strict() -> ssl.SSLContext:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        return context

    monkeypatch.setattr(ssl, "create_default_context", strict)
    assert build_context().minimum_version == ssl.TLSVersion.TLSv1_3


def test_the_context_that_reaches_the_connection_is_the_verified_one(fake_ssl: _Recorder) -> None:
    _connect()
    ((_, _, options),) = fake_ssl.calls
    context = options["ssl_context"]
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert context.minimum_version >= ssl.TLSVersion.TLSv1_2


def test_the_port_only_changes_where_to_connect(fake_ssl: _Recorder) -> None:
    _connect(port=143)
    _connect(port=10993)
    assert [(host, port) for host, port, _ in fake_ssl.calls] == [
        ("mail.invalid", 143),
        ("mail.invalid", 10993),
    ]
    first, second = (options for _, _, options in fake_ssl.calls)
    for options in (first, second):
        assert options["ssl_context"].verify_mode == ssl.CERT_REQUIRED
        assert options["timeout"] == imap.SOCKET_TIMEOUT


def test_no_path_builds_an_unverified_context() -> None:
    """The module's source names none of the ways to ask for an unverified context (ADR-2)."""
    source = Path(imap.__file__).read_text(encoding="utf-8")
    for forbidden in ("_create_unverified_context", "_create_stdlib_context", "CERT_NONE"):
        assert forbidden not in source
    assert not re.search(r"check_hostname\s*=\s*False", source)
    assert not re.search(r"ssl_context\s*=\s*None", source)


@pytest.mark.parametrize(
    ("raised", "reason"),
    [
        (
            ssl.SSLCertVerificationError(1, "certificate verify failed"),
            FetchReason.CERTIFICATE_INVALID,
        ),
        (ssl.SSLError(1, "handshake failure"), FetchReason.TLS_FAILED),
        (ssl.SSLEOFError(8, "EOF"), FetchReason.TLS_FAILED),
        (socket.gaierror(11001, "getaddrinfo failed"), FetchReason.HOST_UNREACHABLE),
        (ConnectionRefusedError(10061, "refused"), FetchReason.HOST_UNREACHABLE),
        (OSError(113, "no route to host"), FetchReason.HOST_UNREACHABLE),
        (UnicodeError("label empty or too long"), FetchReason.HOST_UNREACHABLE),
        (TimeoutError("timed out"), FetchReason.TIMEOUT),
        (imaplib.IMAP4.error("bad greeting"), FetchReason.PROTOCOL_ERROR),
        (imaplib.IMAP4.abort("socket error: EOF"), FetchReason.PROTOCOL_ERROR),
    ],
)
def test_connect_maps_what_the_library_raises(
    fake_ssl: _Recorder, raised: BaseException, reason: FetchReason
) -> None:
    fake_ssl.raises = raised
    assert _refused(_connect).reason is reason
    assert fake_ssl.logins == []  # a failed handshake or greeting has seen no credential


def test_a_refusal_the_connection_raises_passes_through(fake_ssl: _Recorder) -> None:
    fake_ssl.raises = FetchRefused(FetchReason.DEADLINE_EXCEEDED)
    assert _refused(_connect).reason is FetchReason.DEADLINE_EXCEEDED


def test_a_timeout_after_the_deadline_is_the_deadline(fake_ssl: _Recorder) -> None:
    fake_ssl.raises = TimeoutError("timed out")
    refused = _refused(lambda: _connect(clock=ManualClock(50.0), deadline=10.0))
    assert refused.reason is FetchReason.DEADLINE_EXCEEDED


def test_a_rejected_login_is_login_failed_with_no_detail(fake_ssl: _Recorder) -> None:
    fake_ssl.login_raises = imaplib.IMAP4.error(f"[AUTHENTICATIONFAILED] bad {CANARY}".encode())
    refused = _refused(_connect)
    assert refused.reason is FetchReason.LOGIN_FAILED
    assert refused.detail == ""
    assert fake_ssl.shutdowns == 1  # the socket is dropped


def test_a_connection_lost_during_the_login_is_not_a_rejected_login(fake_ssl: _Recorder) -> None:
    fake_ssl.login_raises = imaplib.IMAP4.abort(f"socket error: EOF {CANARY}")
    refused = _refused(_connect)
    assert refused.reason is FetchReason.PROTOCOL_ERROR
    assert CANARY not in refused.detail
    assert fake_ssl.shutdowns == 1


def test_a_timeout_during_the_login_is_a_timeout(fake_ssl: _Recorder) -> None:
    fake_ssl.login_raises = TimeoutError("timed out")
    assert _refused(_connect).reason is FetchReason.TIMEOUT


def test_the_user_is_quoted_in_the_login(fake_ssl: _Recorder) -> None:
    _connect(user='odd "name"')
    assert fake_ssl.logins == [('"odd \\"name\\""', CANARY)]


@pytest.mark.parametrize(
    "password",
    ["", "pass\nword", "pass\rword", "a\x00b", "pa\x7fss", "pa\x85ss", "a\udcffb"],
    ids=["empty", "lf", "cr", "nul", "del", "c1", "lone-surrogate"],
)
def test_an_unusable_password_is_refused_before_the_connection_opens(
    fake_ssl: _Recorder, password: str
) -> None:
    refused = _refused(lambda: _connect(password=password))
    assert refused.reason is FetchReason.PASSWORD_UNUSABLE
    assert fake_ssl.calls == []


@pytest.mark.parametrize("user", ["", "a\nb", "a\x00b", "a\udcffb"])
def test_an_unusable_user_is_a_programming_error(fake_ssl: _Recorder, user: str) -> None:
    with pytest.raises(ValueError, match="user name"):
        _connect(user=user)
    assert fake_ssl.calls == []


@pytest.mark.parametrize(
    ("user", "password", "expected"),
    [
        ("reader", "sénha", "\0reader\0sénha".encode()),
        ("usér", CANARY, f"\0usér\0{CANARY}".encode()),
        ("日本", "パス", "\0日本\0パス".encode()),
    ],
    ids=["password", "user", "both"],
)
def test_a_credential_outside_ascii_goes_by_plain_in_utf8(
    fake_ssl: _Recorder, user: str, password: str, expected: bytes
) -> None:
    _connect(user=user, password=password)
    assert fake_ssl.plain_responses == [expected]
    assert fake_ssl.logins == []  # LOGIN has no encoding for it


def test_an_ascii_credential_still_goes_by_login_whatever_the_server_offers(
    fake_ssl: _Recorder,
) -> None:
    _connect()
    assert fake_ssl.logins == [('"reader"', CANARY)]
    assert fake_ssl.plain_responses == []


def test_a_credential_outside_ascii_needs_plain_advertised(fake_ssl: _Recorder) -> None:
    fake_ssl.capabilities = ("IMAP4REV1", "LOGINDISABLED")
    refused = _refused(lambda: _connect(password="sénha"))
    assert refused.reason is FetchReason.PASSWORD_UNUSABLE
    assert fake_ssl.plain_responses == []  # the secret was never built, let alone sent
    assert fake_ssl.logins == []
    assert fake_ssl.shutdowns == 1


def test_a_rejected_plain_login_is_login_failed_with_no_detail(fake_ssl: _Recorder) -> None:
    fake_ssl.login_raises = imaplib.IMAP4.error(f"AUTHENTICATE failed: bad sénha {CANARY}".encode())
    refused = _refused(lambda: _connect(password="sénha"))
    assert refused.reason is FetchReason.LOGIN_FAILED
    assert refused.detail == ""
    assert fake_ssl.shutdowns == 1


def test_a_password_with_a_space_and_punctuation_is_usable(fake_ssl: _Recorder) -> None:
    _connect(password='pa ss"\\word~')
    assert fake_ssl.logins[0][1] == 'pa ss"\\word~'


# ---------------------------------------------------------------------------
# Secrets and hostile text
# ---------------------------------------------------------------------------


def test_the_password_is_scrubbed_from_every_form_the_library_may_echo() -> None:
    """The scrub also catches the password as ``imaplib`` quotes it and as ``repr`` writes it."""
    secret = 'pa"ss\\w'
    # As typed, as ``imaplib`` quotes it, and as ``repr`` writes it.
    forms = [secret, 'pa\\"ss\\\\w', 'pa"ss\\\\w']
    assert imap._scrub(" | ".join(forms), secret) == "*** | *** | ***"
    assert imap._scrub("nothing to hide", secret) == "nothing to hide"


def test_a_hostile_error_text_is_cleaned_and_cut(fake_ssl: _Recorder) -> None:
    fake_ssl.raises = OSError("\x1b[31m‮evil\u0007\r\n" + "x" * 500 + CANARY)
    refused = _refused(_connect)
    assert len(refused.detail) <= DETAIL_LIMIT
    assert not set(refused.detail) & {"\x1b", "‮", "\x07", "\r", "\n"}


def test_the_password_never_reaches_a_detail(fake_ssl: _Recorder) -> None:
    fake_ssl.raises = OSError(f"connection to {CANARY} failed")
    refused = _refused(_connect)
    assert CANARY not in refused.detail
    assert "***" in refused.detail
    assert CANARY not in str(refused)


# ---------------------------------------------------------------------------
# What goes on the wire
# ---------------------------------------------------------------------------

# The size answer for three messages; the second line puts the attributes in the other order, as
# some servers do.
_SIZES = (
    b"* 1 FETCH (UID 1 RFC822.SIZE 100)\r\n"
    b"* 2 FETCH (RFC822.SIZE 200 UID 2)\r\n"
    b"* 3 FETCH (UID 3 RFC822.SIZE 300)\r\n"
)


def _mailbox_server() -> Handler:
    """
    Build a server with a folder of three messages.

    Returns:
        Handler: Answers ``EXAMINE``, ``UID SEARCH`` and both forms of ``UID FETCH``.
    """
    return _script(
        (b"EXAMINE", b"* 3 EXISTS\r\n* OK [UIDVALIDITY 77] valid\r\n"),
        (b"UID SEARCH", b"* SEARCH 1 2 3\r\n"),
        (b"RFC822.SIZE", _SIZES),
        (b"BODY.PEEK", lambda tag, peer: ok(tag, literal_fetch(3, b"m" * 101))),
    )


def test_only_the_closed_set_of_commands_is_sent(peers: Callable[..., ScriptedPeer]) -> None:
    peer = peers(_mailbox_server())
    mailbox = open_mailbox(peer)

    assert mailbox.select("INBOX") == 77
    assert mailbox.search(None).uids == (1, 2, 3)
    assert mailbox.sizes([1, 2, 3]) == {1: 100, 2: 200, 3: 300}
    assert mailbox.message(3, 100) == b"m" * 101
    mailbox.close()
    peer.close()

    commands = peer.commands()
    names = set()
    for line in commands:
        words = line.decode().split(" ")
        names.add(" ".join(words[:2]) if words[0] == "UID" else words[0])
    assert names == {"CAPABILITY", "LOGIN", "EXAMINE", "UID SEARCH", "UID FETCH", "LOGOUT"}
    assert commands[-1].startswith(b"LOGOUT")
    assert not any(b"BODY[]" in line for line in commands)


def test_plain_sends_one_base64_response_with_the_utf8_credentials(
    peers: Callable[..., ScriptedPeer],
) -> None:
    """PLAIN is a continuation: the response is a line of its own, not a tagged command."""
    tags: list[bytes] = []

    def handler(tag: bytes, line: bytes, peer: ScriptedPeer) -> bytes | None:
        if line.endswith(b"AUTHENTICATE PLAIN"):
            tags.append(tag)
            return b"+ \r\n"
        return ok(tags[0])  # the next line is the response, not a command

    peer = peers(handler, capabilities=b"IMAP4rev1 AUTH=PLAIN")
    connection = PairedImap(peer.client, clock=ManualClock(), deadline=_FAR)
    imap._sign_in(connection, "usér", "sénha")
    peer.close()

    # Newer ``imaplib`` asks for ``CAPABILITY`` again after the login, so the response is not last.
    start = next(i for i, line in enumerate(peer.received) if line.endswith(b"AUTHENTICATE PLAIN"))
    assert base64.b64decode(peer.received[start + 1]) == "\0usér\0sénha".encode()
    assert not any(line.startswith(b"LOGIN") for line in peer.commands())


def test_the_password_is_scrubbed_in_the_forms_a_utf8_echo_takes() -> None:
    """A server may echo the password as typed, as its bytes read as ASCII, or in base64."""
    secret = "sénha"
    forms = [
        secret,
        secret.encode().decode("ascii", "replace"),  # the bytes of an echo, read as ASCII
        base64.b64encode(secret.encode()).decode(),
    ]
    for form in forms:
        assert imap._scrub(f"bad {form} here", secret) == "bad *** here"


def test_the_message_is_fetched_with_peek_and_the_cap_plus_one(
    peers: Callable[..., ScriptedPeer],
) -> None:
    peer = peers(_mailbox_server())
    mailbox = open_mailbox(peer)
    mailbox.select("INBOX")
    mailbox.message(3, 100)
    mailbox.close()
    peer.close()
    assert b"UID FETCH 3 (BODY.PEEK[]<0.101>)" in peer.commands()


def test_the_folder_arrives_quoted_and_encoded(peers: Callable[..., ScriptedPeer]) -> None:
    peer = peers(_mailbox_server())
    mailbox = open_mailbox(peer)
    mailbox.select('Entwürfe "x"')
    mailbox.close()
    peer.close()
    assert b'EXAMINE "Entw&APw-rfe \\"x\\""' in peer.commands()


def test_a_folder_with_a_line_break_sends_nothing(peers: Callable[..., ScriptedPeer]) -> None:
    peer = peers(_mailbox_server())
    mailbox = open_mailbox(peer)
    assert (
        _refused(lambda: mailbox.select("INBOX\r\nA1 DELETE x")).reason
        is FetchReason.FOLDER_NOT_FOUND
    )
    mailbox.close()
    peer.close()
    assert not any(line.startswith(b"EXAMINE") or b"DELETE" in line for line in peer.commands())


def test_a_no_on_examine_is_folder_not_found(peers: Callable[..., ScriptedPeer]) -> None:
    peer = peers(
        _script((b"EXAMINE", lambda tag, _: refuse(tag, b"[NONEXISTENT] Unknown Mailbox")))
    )
    mailbox = open_mailbox(peer)
    refused = _refused(lambda: mailbox.select("Nope"))
    assert refused.reason is FetchReason.FOLDER_NOT_FOUND
    assert "Unknown Mailbox" in refused.detail
    mailbox.close()


def test_a_bad_on_examine_is_a_protocol_error(peers: Callable[..., ScriptedPeer]) -> None:
    peer = peers(_script((b"EXAMINE", lambda tag, _: refuse(tag, b"syntax", b"BAD"))))
    mailbox = open_mailbox(peer)
    assert _refused(lambda: mailbox.select("INBOX")).reason is FetchReason.PROTOCOL_ERROR
    mailbox.close()


@pytest.mark.parametrize(
    "answer", [b"", b"* OK [UIDVALIDITY 0] zero\r\n", b"* OK [UIDVALIDITY x] x\r\n"]
)
def test_a_missing_or_invalid_validity_is_a_protocol_error(
    peers: Callable[..., ScriptedPeer], answer: bytes
) -> None:
    peer = peers(_script((b"EXAMINE", b"* 3 EXISTS\r\n" + answer)))
    mailbox = open_mailbox(peer)
    assert _refused(lambda: mailbox.select("INBOX")).reason is FetchReason.PROTOCOL_ERROR
    mailbox.close()


def test_the_search_carries_the_subject_with_and_without_since(
    peers: Callable[..., ScriptedPeer],
) -> None:
    peer = peers(_mailbox_server())
    mailbox = open_mailbox(peer)
    mailbox.select("INBOX")
    mailbox.search(None)
    mailbox.search(date(2026, 10, 5))
    mailbox.close()
    peer.close()
    searches = [line for line in peer.commands() if line.startswith(b"UID SEARCH")]
    assert searches == [
        b'UID SEARCH SUBJECT "Report Domain:"',
        b'UID SEARCH SINCE 05-Oct-2026 SUBJECT "Report Domain:"',
    ]


def test_an_empty_search_answer_is_no_message(peers: Callable[..., ScriptedPeer]) -> None:
    peer = peers(
        _script((b"EXAMINE", b"* OK [UIDVALIDITY 5] v\r\n"), (b"UID SEARCH", b"* SEARCH\r\n"))
    )
    mailbox = open_mailbox(peer)
    mailbox.select("INBOX")
    assert mailbox.search(None) == SearchResult((), 0)
    mailbox.close()


def test_sizes_are_asked_in_batches(peers: Callable[..., ScriptedPeer]) -> None:
    def answer(tag: bytes, line: bytes) -> bytes:
        asked = line.split(b" ")[3].split(b",")
        return ok(tag, b"".join(b"* 1 FETCH (UID %s RFC822.SIZE 9)\r\n" % uid for uid in asked))

    peer = peers(lambda tag, line, _: answer(tag, line) if b"RFC822.SIZE" in line else ok(tag))
    mailbox = open_mailbox(peer, selected=True)
    uids = list(range(1, 2 * SIZE_BATCH + 51))
    sizes = mailbox.sizes(uids)
    mailbox.close()
    peer.close()
    fetches = [line for line in peer.commands() if line.startswith(b"UID FETCH")]
    assert [len(line.split(b" ")[2].split(b",")) for line in fetches] == [
        SIZE_BATCH,
        SIZE_BATCH,
        50,
    ]
    assert sizes == dict.fromkeys(uids, 9)


def test_no_sizes_to_ask_sends_nothing(peers: Callable[..., ScriptedPeer]) -> None:
    peer = peers()
    mailbox = open_mailbox(peer)
    assert mailbox.sizes([]) == {}
    mailbox.close()
    peer.close()
    assert not any(line.startswith(b"UID") for line in peer.commands())


def test_a_no_on_a_command_is_a_protocol_error(peers: Callable[..., ScriptedPeer]) -> None:
    peer = peers(
        lambda tag, line, _: (
            refuse(tag, b"try later")
            if line.startswith(
                b"UID",
            )
            or b"UID" in line
            else ok(tag)
        )
    )
    mailbox = open_mailbox(peer, selected=True)
    for call in (lambda: mailbox.search(None), lambda: mailbox.sizes([1])):
        refused = _refused(call)
        assert refused.reason is FetchReason.PROTOCOL_ERROR
        assert "try later" in refused.detail
    mailbox.close()


def test_a_message_the_server_does_not_give_is_none(peers: Callable[..., ScriptedPeer]) -> None:
    refusal = _script((b"BODY.PEEK", lambda tag, _: refuse(tag, b"gone")))
    nothing = _script((b"BODY.PEEK", b""))
    for handler in (refusal, nothing):
        peer = peers(handler)
        mailbox = open_mailbox(peer, selected=True)
        assert mailbox.message(9, 100) is None
        mailbox.close()


def test_close_sends_logout_and_ignores_its_failure(peers: Callable[..., ScriptedPeer]) -> None:
    peer = peers()
    mailbox = open_mailbox(peer)
    peer.hang_up()  # the server leaves before the goodbye
    mailbox.close()  # must not raise
    mailbox.close()  # and again, on a connection that is already gone


def test_a_server_error_line_with_control_characters_comes_out_clean(
    peers: Callable[..., ScriptedPeer],
) -> None:
    hostile = b"\x01\x1b[31m" + b"A" * 600 + b"\x07"
    peer = peers(_script((b"UID SEARCH", lambda tag, _: refuse(tag, hostile))))
    mailbox = open_mailbox(peer)
    refused = _refused(lambda: mailbox.search(None))
    assert len(refused.detail) <= DETAIL_LIMIT
    assert not set(refused.detail) & {"\x01", "\x1b", "\x07"}
    mailbox.close()


def test_the_password_is_in_no_command_after_the_login_nor_in_any_detail(
    peers: Callable[..., ScriptedPeer],
) -> None:
    echo = f"your password {CANARY} is not good".encode()
    peer = peers(
        _script(
            (b'"Nope"', lambda tag, _: refuse(tag, echo)),
            (b"EXAMINE", b"* OK [UIDVALIDITY 5] valid\r\n"),
            (b"UID SEARCH", lambda tag, _: refuse(tag, echo, b"BAD")),
            (b"RFC822.SIZE", lambda tag, _: refuse(tag, echo)),
        )
    )
    mailbox = open_mailbox(peer)
    refusals = [_refused(lambda: mailbox.select("Nope"))]
    mailbox.select("INBOX")
    refusals += [_refused(lambda: mailbox.search(None)), _refused(lambda: mailbox.sizes([1]))]
    mailbox.close()
    peer.close()
    for refused in refusals:
        assert CANARY not in refused.detail
        assert CANARY not in str(refused)
        assert "***" in refused.detail
    assert CANARY.encode() not in _all_words(peer)
    assert any(CANARY.encode() in line for line in peer.commands())  # only the LOGIN line has it


# ---------------------------------------------------------------------------
# The bounds
# ---------------------------------------------------------------------------


def test_a_literal_over_the_limit_is_refused_before_any_of_it_is_read(
    peers: Callable[..., ScriptedPeer], monkeypatch: pytest.MonkeyPatch
) -> None:
    peer = peers()
    connection = PairedImap(peer.client, clock=ManualClock(), deadline=_FAR)

    def never(self: object, size: int) -> bytes:
        raise AssertionError("the library read a literal the bounds should have refused")

    monkeypatch.setattr(imaplib.IMAP4, "read", never)
    connection.max_literal = 10
    with pytest.raises(imaplib.IMAP4.abort, match="announced a literal of 11 bytes"):
        connection.read(11)


def test_a_literal_within_the_limit_is_read_whole(peers: Callable[..., ScriptedPeer]) -> None:
    peer = peers()
    connection = PairedImap(peer.client, clock=ManualClock(), deadline=_FAR)
    body = bytes(range(256)) * 600  # 153,600 bytes: three slices
    connection.max_literal = len(body)
    peer.send(body)
    assert connection.read(len(body)) == body


def test_a_literal_cut_short_by_the_server_returns_what_arrived(
    peers: Callable[..., ScriptedPeer],
) -> None:
    peer = peers()
    connection = PairedImap(peer.client, clock=ManualClock(), deadline=_FAR)
    connection.max_literal = 1000
    peer.send(b"abc")
    peer.hang_up()
    assert connection.read(1000) == b"abc"


def test_the_announced_literal_of_an_answer_is_refused_as_a_protocol_error(
    peers: Callable[..., ScriptedPeer],
) -> None:
    announce = b"* 1 FETCH (UID 3 BODY[]<0> {%d}\r\n" % (LITERAL_OTHER + 1)
    peer = peers(_script((b"RFC822.SIZE", lambda tag, p: p.send(announce) or None)))
    mailbox = open_mailbox(peer, selected=True)
    refused = _refused(lambda: mailbox.sizes([3]))
    assert refused.reason is FetchReason.PROTOCOL_ERROR
    mailbox.close()
    peer.close()
    assert not any(line.startswith(b"LOGOUT") for line in peer.commands())  # an abort ends it


def test_the_literal_limit_is_other_outside_message_and_cap_plus_one_inside(
    peers: Callable[..., ScriptedPeer],
) -> None:
    peer = peers(_script((b"BODY.PEEK", lambda tag, _: ok(tag, literal_fetch(3, b"m" * 102)))))
    mailbox = open_mailbox(peer, selected=True)
    connection = mailbox._connection
    assert connection.max_literal == LITERAL_OTHER

    seen: list[int] = []
    real = connection.uid

    def spy(command: str, *args: str) -> Any:
        seen.append(connection.max_literal)
        return real(command, *args)

    connection.uid = spy  # type: ignore[method-assign]  # a test spy on the instance
    # The cap is 100, so the literal may be 101 bytes; 102 is the server ignoring the partial fetch.
    assert _refused(lambda: mailbox.message(3, 100)).reason is FetchReason.PROTOCOL_ERROR
    assert seen == [101]
    assert connection.max_literal == LITERAL_OTHER  # restored on the way out, refusal or not


def test_a_literal_of_exactly_the_cap_plus_one_is_accepted(
    peers: Callable[..., ScriptedPeer],
) -> None:
    peer = peers(_script((b"BODY.PEEK", lambda tag, _: ok(tag, literal_fetch(3, b"m" * 101)))))
    mailbox = open_mailbox(peer, selected=True)
    assert mailbox.message(3, 100) == b"m" * 101
    assert mailbox._connection.max_literal == LITERAL_OTHER
    mailbox.close()


def test_a_silent_server_ends_in_timeout(
    peers: Callable[..., ScriptedPeer], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(imap, "SOCKET_TIMEOUT", 0.3)
    peer = peers(_script((b"UID SEARCH", lambda tag, _: None)))
    mailbox = open_mailbox(peer, selected=True)
    assert _refused(lambda: mailbox.search(None)).reason is FetchReason.TIMEOUT
    mailbox.close()


def test_a_literal_that_never_ends_ends_in_timeout(
    peers: Callable[..., ScriptedPeer], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(imap, "SOCKET_TIMEOUT", 0.3)
    start = b"* 1 FETCH (UID 3 BODY[]<0> {100}\r\n" + b"m" * 10
    peer = peers(_script((b"BODY.PEEK", lambda tag, p: p.send(start) or None)))
    mailbox = open_mailbox(peer, selected=True)
    assert _refused(lambda: mailbox.message(3, 100)).reason is FetchReason.TIMEOUT
    mailbox.close()


def test_an_endless_line_is_a_protocol_error(peers: Callable[..., ScriptedPeer]) -> None:
    peer = peers(_script((b"RFC822.SIZE", lambda tag, p: p.send(b"x" * (LINE_LIMIT + 50)) or None)))
    mailbox = open_mailbox(peer, selected=True)
    assert _refused(lambda: mailbox.sizes([1])).reason is FetchReason.PROTOCOL_ERROR
    mailbox.close()
    peer.close()
    assert not any(line.startswith(b"LOGOUT") for line in peer.commands())


def test_a_search_line_over_the_limit_is_too_many_matches(
    peers: Callable[..., ScriptedPeer],
) -> None:
    numbers = b" ".join(b"%d" % n for n in range(1_000_000, 1_150_000))
    assert len(numbers) > LINE_LIMIT
    peer = peers(
        _script((b"UID SEARCH", lambda tag, p: p.send(b"* SEARCH " + numbers + b"\r\n") or None))
    )
    mailbox = open_mailbox(peer, selected=True)
    assert _refused(lambda: mailbox.search(None)).reason is FetchReason.TOO_MANY_MATCHES
    mailbox.close()


def test_a_search_answer_just_under_the_limit_is_read(peers: Callable[..., ScriptedPeer]) -> None:
    numbers = b" ".join(b"%d" % n for n in range(1_000_000, 1_123_750))
    assert LINE_LIMIT - 20_000 < len(numbers) < LINE_LIMIT - 20
    peer = peers(_script((b"UID SEARCH", b"* SEARCH " + numbers + b"\r\n")))
    mailbox = open_mailbox(peer, selected=True)
    assert len(mailbox.search(None).uids) == 123_750
    mailbox.close()


def test_a_line_of_exactly_the_limit_with_no_line_break_is_too_long(
    peers: Callable[..., ScriptedPeer], monkeypatch: pytest.MonkeyPatch
) -> None:
    peer = peers()
    connection = PairedImap(peer.client, clock=ManualClock(), deadline=_FAR)
    monkeypatch.setattr(imaplib.IMAP4, "readline", lambda self: b"x" * LINE_LIMIT)
    with pytest.raises(_LineTooLong):
        connection.readline()


def test_a_line_of_exactly_the_limit_with_its_line_break_is_fine(
    peers: Callable[..., ScriptedPeer], monkeypatch: pytest.MonkeyPatch
) -> None:
    peer = peers()
    connection = PairedImap(peer.client, clock=ManualClock(), deadline=_FAR)
    line = b"x" * (LINE_LIMIT - 2) + b"\r\n"
    monkeypatch.setattr(imaplib.IMAP4, "readline", lambda self: line)
    assert connection.readline() == line


def test_a_clock_past_the_deadline_between_chunks_ends_the_transfer(
    peers: Callable[..., ScriptedPeer],
) -> None:
    """The server sends the literal in two parts and the time runs out between them."""
    late = threading.Event()

    def clock() -> float:
        return 100.0 if late.is_set() else 0.0

    def answer(tag: bytes, peer: ScriptedPeer) -> None:
        peer.send(b"* 1 FETCH (UID 3 BODY[]<0> {200000}\r\n" + b"m" * 70_000)
        late.set()  # the time runs out while the literal is still arriving
        peer.send(b"m" * 130_000 + b")\r\n" + ok(tag))

    peer = peers(_script((b"BODY.PEEK", lambda tag, p: answer(tag, p))))
    mailbox = open_mailbox(peer, selected=True, clock=clock, deadline=50.0)
    assert _refused(lambda: mailbox.message(3, 300_000)).reason is FetchReason.DEADLINE_EXCEEDED
    mailbox.close()
    peer.close()
    assert not any(line.startswith(b"LOGOUT") for line in peer.commands())


def test_a_command_after_the_deadline_reads_nothing(peers: Callable[..., ScriptedPeer]) -> None:
    clock = ManualClock()
    peer = peers()
    mailbox = open_mailbox(peer, selected=True, clock=clock, deadline=10.0)
    clock.now = 11.0
    assert _refused(lambda: mailbox.search(None)).reason is FetchReason.DEADLINE_EXCEEDED
    mailbox.close()


def test_the_socket_timeout_is_the_time_left_when_that_is_less(
    peers: Callable[..., ScriptedPeer],
) -> None:
    clock = ManualClock()
    peer = peers()
    connection = PairedImap(peer.client, clock=clock, deadline=100.0)
    clock.now = 98.0
    connection._arm()
    assert connection.sock.gettimeout() == pytest.approx(2.0)
    clock.now = 0.0
    connection._arm()
    assert connection.sock.gettimeout() == imap.SOCKET_TIMEOUT


def test_the_bounds_are_a_mixin_over_the_library_connection() -> None:
    assert issubclass(imap._BoundedSsl, _Bounds)
    assert issubclass(imap._BoundedSsl, imaplib.IMAP4_SSL)
