"""
The one adapter to IMAP: ``imaplib`` and ``ssl`` are imported here and nowhere else in the product.

``ImapMailbox`` implements the five-method ``Mailbox`` protocol over a connection whose reads are
bounded (spec 009, ADR-1, ADR-3): a literal the server announces over the current limit is refused
before one byte of it is read, every read waits at most ``SOCKET_TIMEOUT`` or the time left to the
run, and a line over ``LINE_LIMIT`` ends the run. The TLS context is built here and always verifies
the certificate and the host name (ADR-2). The only commands the module can send are ``CAPABILITY``,
``LOGIN`` (or ``AUTHENTICATE PLAIN`` for a login outside ASCII, ADR-9), ``EXAMINE``,
``UID SEARCH``, ``UID FETCH`` and ``LOGOUT``, and the message is fetched with ``BODY.PEEK`` so it is
not marked read. Every failure of the library becomes a ``FetchRefused``, with the password
scrubbed out of whatever text it carries.
"""

from __future__ import annotations

import base64
import contextlib
import imaplib
import re
import ssl
from collections.abc import Callable, Iterator, Sequence
from datetime import date
from typing import Any

from mailvigil.fetch.errors import FetchReason, FetchRefused
from mailvigil.fetch.model import (
    LINE_LIMIT,
    LITERAL_OTHER,
    SIZE_BATCH,
    SOCKET_TIMEOUT,
    UID_MAX,
    SearchResult,
)

__all__ = [
    "ImapMailbox",
    "build_context",
    "connect",
    "encode_folder",
    "format_since",
    "parse_search",
    "parse_sizes",
    "parse_validity",
    "quote",
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# IMAP wants English month names whatever the locale, so the date is never built by ``strftime``.
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

# RFC 7489 asks a report sender to write ``Report Domain:`` in the subject; the maintainer's first
# real run checks that the providers do (spec 009, open question 3).
_SUBJECT = '"Report Domain:"'

# A literal is read in slices of this size, so the deadline is looked at between slices.
_CHUNK = 64 * 1024

# What ``LOGIN`` can carry: printable ASCII, no control character (ADR-5).
_CREDENTIAL = re.compile(r"[\x20-\x7e]+")

# What a credential may hold at all (ADR-9): any text but a control character of C0, DEL or C1.
# NUL is the separator of ``PLAIN`` and a line break has no business in a password.
_USABLE = re.compile(r"[^\x00-\x1f\x7f-\x9f]+")

# The capability that lets a credential outside ASCII be sent as UTF-8 (RFC 4616).
_PLAIN = "AUTH=PLAIN"

# UIDs, validity numbers and sizes have at most ten digits (``UID_MAX``); the cap on the length
# keeps a hostile ten-thousand-digit token away from ``int``.
_NUMBER = re.compile(rb"\d{1,10}")
_SIZE_LINE = re.compile(rb"\d{1,10} \((?:(?:UID|RFC822\.SIZE) \d{1,10} ?)+\)")
_UID_ATTRIBUTE = re.compile(rb"UID (\d{1,10})")
_SIZE_ATTRIBUTE = re.compile(rb"RFC822\.SIZE (\d{1,10})")

# What a refusal of the library may be; anything else is a bug and is left to crash.
_LIBRARY_ERRORS = (OSError, UnicodeError, imaplib.IMAP4.error, FetchRefused)

# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def quote(text: str) -> str:
    """
    Make an IMAP quoted string.

    Args:
        text (str): The text, printable ASCII; ``imaplib`` sends its arguments as they are.

    Returns:
        str: The text between double quotes, with ``\\`` and ``"`` escaped.
    """
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def encode_folder(name: str) -> str:
    """
    Encode a folder name as modified UTF-7 (RFC 3501, section 5.1.3).

    ``&`` becomes ``&-``; a run of characters outside printable ASCII becomes ``&``, the base64 of
    its UTF-16BE form without padding and with ``,`` for ``/``, then ``-``.

    Args:
        name (str): The folder name as the user typed it.

    Returns:
        str: The name in printable ASCII, ready to be quoted.

    Raises:
        FetchRefused: ``folder_not_found``, when the name has a control character (a line break
            would send a second command) or a lone surrogate that has no UTF-16 form.
    """
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in name):
        raise FetchRefused(FetchReason.FOLDER_NOT_FOUND)

    def run(match: re.Match[str]) -> str:
        text = match.group()
        if text == "&":
            return "&-"
        packed = base64.b64encode(text.encode("utf-16-be")).decode("ascii")
        return "&" + packed.rstrip("=").replace("/", ",") + "-"

    try:
        return re.sub(r"&|[^\x20-\x25\x27-\x7e]+", run, name)
    except UnicodeEncodeError:
        raise FetchRefused(FetchReason.FOLDER_NOT_FOUND) from None


def format_since(day: date) -> str:
    """
    Write a day the way ``SINCE`` wants it, whatever the locale.

    Args:
        day (date): The day.

    Returns:
        str: ``dd-Mon-yyyy`` with an English month name.
    """
    return f"{day.day:02d}-{_MONTHS[day.month - 1]}-{day.year:04d}"


def _uid_from(token: bytes) -> int | None:
    """
    Read a UID or a validity number.

    Args:
        token (bytes): One word of a server answer.

    Returns:
        int | None: The number, or ``None`` when it is not ASCII digits, has more than ten of them
            or is outside ``1..UID_MAX`` (zero, hex, a sign and a decimal point all fall here).
    """
    if _NUMBER.fullmatch(token) is None:
        return None
    value = int(token)
    return value if 1 <= value <= UID_MAX else None


def parse_search(data: Sequence[object] | None) -> SearchResult:
    """
    Read the answer of ``UID SEARCH``.

    Args:
        data (Sequence[object] | None): What ``imaplib`` returns: a list with the answer line, an
            empty line when nothing matched, or ``[None]`` or ``None`` when there was no line.

    Returns:
        SearchResult: The valid UIDs in ascending order, and the count of words that were not one.
    """
    words = b" ".join(item for item in data or () if isinstance(item, bytes)).split()
    valid: list[int] = []
    dropped = 0
    for word in words:
        uid = _uid_from(word)
        if uid is None:
            dropped += 1
        else:
            valid.append(uid)
    return SearchResult(tuple(sorted(valid)), dropped)


def parse_sizes(data: Sequence[object] | None, wanted: set[int]) -> dict[int, int]:
    """
    Read the answer of ``UID FETCH ... (RFC822.SIZE)``.

    The attributes of a line come in any order, as servers differ; a line that is not exactly a
    sequence number and those two attributes, or that lacks one of the two numbers, is ignored.

    Args:
        data (Sequence[object] | None): What ``imaplib`` returns: one line per message.
        wanted (set[int]): The UIDs that were asked about; an answer for another one is ignored.

    Returns:
        dict[int, int]: The announced size in bytes of each UID the server answered for.
    """
    sizes: dict[int, int] = {}
    for item in data or ():
        if not isinstance(item, bytes) or _SIZE_LINE.fullmatch(item) is None:
            continue
        uid_match = _UID_ATTRIBUTE.search(item)
        size_match = _SIZE_ATTRIBUTE.search(item)
        if uid_match is None or size_match is None:
            continue
        uid = _uid_from(uid_match.group(1))
        if uid in wanted:
            sizes[uid] = int(size_match.group(1))
    return sizes


def parse_validity(data: Sequence[object] | None) -> int:
    """
    Read the ``UIDVALIDITY`` the server sent when the folder was opened.

    Args:
        data (Sequence[object] | None): What ``imaplib`` returns for that response code.

    Returns:
        int: The validity number, in ``1..UID_MAX``.

    Raises:
        FetchRefused: ``protocol_error``, when there is none or it is not such a number.
    """
    token = data[-1] if data else None
    value = _uid_from(token) if isinstance(token, bytes) else None
    if value is None:
        raise FetchRefused(FetchReason.PROTOCOL_ERROR, "the server sent no valid UIDVALIDITY")
    return value


# ---------------------------------------------------------------------------
# Errors and secrets
# ---------------------------------------------------------------------------


class _LineTooLong(imaplib.IMAP4.abort):
    """
    A line passed ``LINE_LIMIT``: the server is not speaking IMAP, or has too much to say.

    ``imaplib`` wraps every ``abort`` of a command in a new one, so the type does not survive to
    the caller; the connection also sets ``overlong``, which does.
    """


def _is_plain_error(exc: BaseException) -> bool:
    """
    Tell a refusal the server gave from a connection that failed.

    Args:
        exc (BaseException): What the library raised.

    Returns:
        bool: True for ``IMAP4.error`` itself (a ``BAD`` answer), which leaves the connection
            usable; False for ``abort`` and everything else, which leave it in an unknown state.
    """
    return isinstance(exc, imaplib.IMAP4.error) and not isinstance(exc, imaplib.IMAP4.abort)


def _scrub(text: str, secret: str) -> str:
    """
    Take the password out of a text, in the forms a server or the library may echo it.

    Args:
        text (str): Text from the library or the server.
        secret (str): The password.

    Returns:
        str: The text with every occurrence replaced by ``***``.
    """
    escaped = secret.replace("\\", "\\\\")
    utf8 = secret.encode("utf-8", "replace")
    forms = (
        secret,
        escaped,
        escaped.replace('"', '\\"'),
        repr(secret)[1:-1],
        # A server that echoes the UTF-8 bytes is read as ASCII with a replacement per byte.
        utf8.decode("ascii", "replace"),
        base64.b64encode(utf8).decode("ascii"),
    )
    for form in forms:
        text = text.replace(form, "***")
    return text


def _is_usable(text: str) -> bool:
    """
    Tell whether a credential can be sent at all.

    Args:
        text (str): The user name or the password.

    Returns:
        bool: ``True`` when it is not empty, has no control character and encodes as UTF-8 (a lone
            surrogate, which a command line can carry, does not).
    """
    if _USABLE.fullmatch(text) is None:
        return False
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _server_text(data: Sequence[object] | None) -> str:
    """
    Join the text lines of a server answer.

    Args:
        data (Sequence[object] | None): What ``imaplib`` returns with an answer.

    Returns:
        str: The lines that are bytes, decoded as ASCII, joined by a space.
    """
    return " ".join(
        item.decode("ascii", "replace") for item in data or () if isinstance(item, bytes)
    )


def _refusal_for(
    exc: BaseException, secret: str, *, expired: bool, overlong: bool = False
) -> FetchRefused:
    """
    Turn what the library raised into the refusal the command reports.

    Args:
        exc (BaseException): One of ``_LIBRARY_ERRORS``.
        secret (str): The password, scrubbed out of the detail.
        expired (bool): Whether the run's deadline has passed, which makes a timeout the
            deadline's.
        overlong (bool, optional): Whether a line passed ``LINE_LIMIT`` during ``UID SEARCH``,
            which means too many matches. Default: ``False``.

    Returns:
        FetchRefused: The refusal; ``exc`` itself when it already is one.
    """
    if isinstance(exc, FetchRefused):
        return exc
    if isinstance(exc, ssl.SSLCertVerificationError):
        reason = FetchReason.CERTIFICATE_INVALID
    elif isinstance(exc, ssl.SSLError):
        reason = FetchReason.TLS_FAILED
    elif isinstance(exc, TimeoutError):
        reason = FetchReason.DEADLINE_EXCEEDED if expired else FetchReason.TIMEOUT
    elif isinstance(exc, (OSError, UnicodeError)):
        reason = FetchReason.HOST_UNREACHABLE
    elif overlong:
        reason = FetchReason.TOO_MANY_MATCHES
    else:
        reason = FetchReason.PROTOCOL_ERROR
    return FetchRefused(reason, _scrub(str(exc), secret))


# ---------------------------------------------------------------------------
# The bounded connection
# ---------------------------------------------------------------------------


class _Bounds(imaplib.IMAP4):
    """
    An ``IMAP4`` whose reads are bounded in size and in time (spec 009, ADR-3).

    It overrides ``read`` and ``readline``, which ``imaplib`` documents as replaceable, and goes on
    through the library's own reading, so it works on every version whose I/O sits behind those two
    methods. Combined with ``IMAP4_SSL`` it is the product's connection; the tests combine it with
    a plain ``IMAP4`` over a local socket pair.

    Attributes:
        clock (Callable[[], float]): Reads the time, in the unit of ``deadline``.
        deadline (float): The reading of ``clock`` past which nothing more is read.
        max_literal (int): The biggest literal a server may announce right now.
        overlong (bool): Whether a line passed ``LINE_LIMIT``; the caller reads it after a failure.
    """

    def __init__(
        self,
        host: str,
        port: int,
        *,
        clock: Callable[[], float],
        deadline: float,
        **options: Any,
    ) -> None:
        """
        Open the connection and read the greeting under the bounds.

        Args:
            host (str): The server.
            port (int): The port.
            clock (Callable[[], float]): Reads the time.
            deadline (float): The reading of ``clock`` past which nothing more is read.
            **options (Any): Passed to the library's constructor (``ssl_context``, ``timeout``).
        """
        # Set before the library connects: the greeting is already read through these bounds.
        self.clock = clock
        self.deadline = deadline
        self.max_literal = LITERAL_OTHER
        self.overlong = False
        super().__init__(host, port, **options)

    def _arm(self) -> None:
        """
        Allow the next read the time it may take: at most ``SOCKET_TIMEOUT``, at most what is left.

        Raises:
            FetchRefused: ``deadline_exceeded``, when no time is left.
        """
        left = self.deadline - self.clock()
        if left <= 0:
            raise FetchRefused(FetchReason.DEADLINE_EXCEEDED)
        self.sock.settimeout(min(SOCKET_TIMEOUT, left))

    def read(self, size: int) -> bytes:
        """
        Read a literal, refusing one the server announces over the limit.

        Args:
            size (int): The size the server announced.

        Returns:
            bytes: What arrived; shorter than ``size`` only when the connection ended.

        Raises:
            IMAP4.abort: Before reading anything, when ``size`` is over ``max_literal``.
            FetchRefused: ``deadline_exceeded``, between two slices.
        """
        if size > self.max_literal:
            raise self.abort(f"the server announced a literal of {size} bytes, over the limit")
        parts: list[bytes] = []
        remaining = size
        while remaining > 0:
            self._arm()
            want = min(remaining, _CHUNK)
            part = super().read(want)
            parts.append(part)
            remaining -= len(part)
            if len(part) < want:
                break
        return b"".join(parts)

    def readline(self) -> bytes:
        """
        Read a line of at most ``LINE_LIMIT`` bytes.

        Returns:
            bytes: The line, with its line break.

        Raises:
            _LineTooLong: When the line passes the limit.
            FetchRefused: ``deadline_exceeded``, when no time is left.
        """
        self._arm()
        try:
            line = super().readline()
        except imaplib.IMAP4.error:
            # The library raises its plain error only for a line over its own limit.
            self.overlong = True
            raise _LineTooLong(f"a line of more than {LINE_LIMIT} bytes") from None
        # Newer releases read in blocks and can stop at exactly the limit with no line break yet;
        # a line that long and still open is too long as well.
        if len(line) >= LINE_LIMIT and not line.endswith(b"\n"):
            self.overlong = True
            raise _LineTooLong(f"a line of more than {LINE_LIMIT} bytes")
        return line


class _BoundedSsl(_Bounds, imaplib.IMAP4_SSL):
    """The product's connection: implicit TLS with the context ``build_context`` makes."""


# ---------------------------------------------------------------------------
# The mailbox
# ---------------------------------------------------------------------------


class ImapMailbox:
    """
    A mailbox read over IMAP, read-only (the ``Mailbox`` protocol of ``model.py``).

    It sends ``EXAMINE``, ``UID SEARCH`` and ``UID FETCH`` and, on ``close``, ``LOGOUT``.
    """

    def __init__(
        self,
        connection: _Bounds,
        secret: str,
        clock: Callable[[], float],
        deadline: float,
    ) -> None:
        """
        Wrap a connection that is already logged in.

        Args:
            connection (_Bounds): The bounded connection.
            secret (str): The password, scrubbed out of every refusal text.
            clock (Callable[[], float]): Reads the time, in the unit of ``deadline``.
            deadline (float): The reading of ``clock`` that makes a timeout the deadline's.
        """
        self._connection = connection
        self._secret = secret
        self._clock = clock
        self._deadline = deadline
        # After an abort the stream is in an unknown state: a LOGOUT could not be understood.
        self._broken = False

    @contextlib.contextmanager
    def _guard(self, *, searching: bool = False) -> Iterator[None]:
        """
        Turn the library's failures inside the block into a ``FetchRefused``.

        Args:
            searching (bool, optional): Whether the block is the search. Default: ``False``.

        Yields:
            None: The block runs.

        Raises:
            FetchRefused: For any of ``_LIBRARY_ERRORS``.
        """
        try:
            yield
        except _LIBRARY_ERRORS as exc:
            if not _is_plain_error(exc):
                self._broken = True
            refusal = _refusal_for(
                exc,
                self._secret,
                expired=self._clock() >= self._deadline,
                overlong=searching and self._connection.overlong,
            )
            raise refusal from None

    def _refuse(self, reason: FetchReason, data: Sequence[object] | None) -> FetchRefused:
        """
        Build the refusal for an answer that was not ``OK``.

        Args:
            reason (FetchReason): The cause.
            data (Sequence[object] | None): The answer, whose text becomes the detail.

        Returns:
            FetchRefused: The refusal, with the password scrubbed out of the server's words.
        """
        return FetchRefused(reason, _scrub(_server_text(data), self._secret))

    def select(self, folder: str) -> int:
        """
        Open a folder read-only (``EXAMINE``).

        Args:
            folder (str): The folder name as the user typed it.

        Returns:
            int: The validity number of the folder, in ``1..UID_MAX``.

        Raises:
            FetchRefused: ``folder_not_found`` for a name with a control character or an answer of
                ``NO``; ``protocol_error`` for a validity number that is not one.
        """
        name = quote(encode_folder(folder))
        with self._guard():
            kind, data = self._connection.select(name, readonly=True)
            validity = self._connection.response("UIDVALIDITY")[1]
        if kind != "OK":
            raise self._refuse(FetchReason.FOLDER_NOT_FOUND, data)
        return parse_validity(validity)

    def search(self, since: date | None) -> SearchResult:
        """
        List the messages whose subject says they are DMARC reports (``UID SEARCH``).

        Args:
            since (date | None): Only messages received on or after this day; ``None`` for all.

        Returns:
            SearchResult: The valid UIDs, ascending, and the count of words that were not one.

        Raises:
            FetchRefused: ``too_many_matches`` when the answer line passes ``LINE_LIMIT``;
                ``protocol_error`` for an answer of ``NO``.
        """
        criteria = ["SINCE", format_since(since)] if since is not None else []
        with self._guard(searching=True):
            kind, data = self._connection.uid("SEARCH", *criteria, "SUBJECT", _SUBJECT)
        if kind != "OK":
            raise self._refuse(FetchReason.PROTOCOL_ERROR, data)
        return parse_search(data)

    def sizes(self, uids: Sequence[int]) -> dict[int, int]:
        """
        Ask the size the server announces for each message, in batches of ``SIZE_BATCH``.

        Args:
            uids (Sequence[int]): The messages to ask about, each in ``1..UID_MAX``.

        Returns:
            dict[int, int]: The announced size in bytes; a UID with no usable answer is missing.

        Raises:
            FetchRefused: ``protocol_error`` for an answer of ``NO``.
        """
        announced: dict[int, int] = {}
        for start in range(0, len(uids), SIZE_BATCH):
            batch = uids[start : start + SIZE_BATCH]
            with self._guard():
                kind, data = self._connection.uid(
                    "FETCH", ",".join(str(uid) for uid in batch), "(RFC822.SIZE)"
                )
            if kind != "OK":
                raise self._refuse(FetchReason.PROTOCOL_ERROR, data)
            announced.update(parse_sizes(data, set(batch)))
        return announced

    def message(self, uid: int, limit: int) -> bytes | None:
        """
        Download one message without marking it read (``BODY.PEEK``, ``limit + 1`` bytes at most).

        The extra byte lets the caller tell a message of exactly ``limit`` bytes from a longer one.

        Args:
            uid (int): The message, in ``1..UID_MAX``.
            limit (int): The cap in bytes.

        Returns:
            bytes | None: The raw message, at most ``limit + 1`` bytes; ``None`` when the server
                gives no body.

        Raises:
            FetchRefused: ``protocol_error`` when the server announces more than was asked.
        """
        self._connection.max_literal = limit + 1
        try:
            with self._guard():
                kind, data = self._connection.uid(
                    "FETCH", str(uid), f"(BODY.PEEK[]<0.{limit + 1}>)"
                )
        finally:
            self._connection.max_literal = LITERAL_OTHER
        first = data[0] if kind == "OK" and data else None
        if isinstance(first, tuple) and isinstance(first[1], bytes):
            return first[1]
        return None

    def close(self) -> None:
        """Say ``LOGOUT`` and drop the connection; a failure here is ignored."""
        if not self._broken:
            with contextlib.suppress(*_LIBRARY_ERRORS):
                self._connection.logout()
        _drop(self._connection)


# ---------------------------------------------------------------------------
# The connection
# ---------------------------------------------------------------------------


def _drop(connection: imaplib.IMAP4) -> None:
    """
    Close the socket of a connection, whatever its state.

    Args:
        connection (imaplib.IMAP4): The connection.
    """
    with contextlib.suppress(OSError):
        connection.shutdown()


def build_context() -> ssl.SSLContext:
    """
    Build the TLS context of every connection: verified certificate, verified host name, TLS 1.2+.

    ``imaplib`` would build an unverified one when given none (spec 009, ADR-2), so this is the
    only context the module ever uses.

    Returns:
        ssl.SSLContext: A context from ``ssl.create_default_context``.
    """
    context = ssl.create_default_context()
    # The default is already 1.2 on current releases; an older build or a loosened one is raised.
    context.minimum_version = max(context.minimum_version, ssl.TLSVersion.TLSv1_2)
    return context


def _sign_in(connection: imaplib.IMAP4, user: str, password: str) -> None:
    """
    Log in with ``LOGIN``, or with ``AUTHENTICATE PLAIN`` when a credential is outside ASCII.

    Args:
        connection (imaplib.IMAP4): The connection, past the greeting; the caller has verified TLS.
        user (str): The login, with no control character.
        password (str): The password, with no control character.

    Raises:
        FetchRefused: ``password_unusable`` when a credential is outside ASCII and the server does
            not advertise ``AUTH=PLAIN``, before anything secret is sent.
        imaplib.IMAP4.error: The server said ``NO`` or ``BAD``.
    """
    if _CREDENTIAL.fullmatch(user) and _CREDENTIAL.fullmatch(password):
        connection.login(quote(user), password)
        return
    # ``LOGIN`` has no encoding for these (RFC 3501); ``PLAIN`` is UTF-8 by definition (RFC 4616).
    if _PLAIN not in connection.capabilities:
        raise FetchRefused(FetchReason.PASSWORD_UNUSABLE)
    response = f"\0{user}\0{password}".encode()
    connection.authenticate("PLAIN", lambda _challenge: response)


def connect(
    host: str,
    port: int,
    user: str,
    password: str,
    clock: Callable[[], float],
    deadline: float,
) -> ImapMailbox:
    """
    Open a verified TLS connection to a server and log in.

    The password is sent only after the handshake, which is after the certificate was verified, so a
    server that fails verification has seen nothing.

    Args:
        host (str): The server.
        port (int): The port; it only changes where to connect, the connection is always TLS.
        user (str): The login, with no control character (the command checks it as a usage error).
        password (str): The password, with no control character; outside ASCII it needs a server
            that advertises ``AUTH=PLAIN`` (ADR-9).
        clock (Callable[[], float]): Reads the time, in the unit of ``deadline``.
        deadline (float): The reading of ``clock`` past which nothing more is read.

    Returns:
        ImapMailbox: The mailbox, logged in.

    Raises:
        ValueError: When ``user`` is empty or has a control character.
        FetchRefused: ``password_unusable`` before any connection is opened, or after the handshake
            when a credential is outside ASCII and the server has no ``AUTH=PLAIN``; otherwise the
            reason that matches what failed (certificate, TLS, host, timeout, login, protocol).
    """
    if not _is_usable(user):
        raise ValueError("the user name is empty or has a control character")
    if not _is_usable(password):
        raise FetchRefused(FetchReason.PASSWORD_UNUSABLE)
    try:
        connection = _BoundedSsl(
            host,
            port,
            clock=clock,
            deadline=deadline,
            ssl_context=build_context(),
            timeout=SOCKET_TIMEOUT,
        )
    except _LIBRARY_ERRORS as exc:
        raise _refusal_for(exc, password, expired=clock() >= deadline) from None
    try:
        _sign_in(connection, user, password)
    except _LIBRARY_ERRORS as exc:
        _drop(connection)
        # What the server says about a refused login is not shown: it may echo the credentials.
        if _is_plain_error(exc):
            raise FetchRefused(FetchReason.LOGIN_FAILED) from None
        raise _refusal_for(exc, password, expired=clock() >= deadline) from None
    return ImapMailbox(connection, password, clock, deadline)
