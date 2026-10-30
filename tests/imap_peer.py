"""
A scripted IMAP server on the far end of a local socket pair, for the tests of ``fetch/imap.py``.

Nothing here opens a network connection: ``socket.socketpair()`` joins the connection under test to
a thread that reads command lines and answers from a handler (spec 009, ADR-1, RNF-06). The thread
answers ``CAPABILITY`` and ``LOGOUT`` itself; every other command goes to the handler, which may
answer, stay silent or write raw bytes through the peer. Hosts, users and passwords are invented.
"""

from __future__ import annotations

import contextlib
import select
import socket
import threading
from collections.abc import Callable, Iterator
from typing import Any

from mailvigil.fetch.imap import ImapMailbox, _Bounds, quote

# A handler gets the tag, the whole command line without its line break, and the peer.
Handler = Callable[[bytes, bytes, "ScriptedPeer"], bytes | None]

# How long the server thread waits for a command before it looks at the stop signal.
_POLL = 0.02

# A password no output may ever contain: the tests search every refusal and command for it (RNF-02).
CANARY = "canary-pw-7Q!"

# ---------------------------------------------------------------------------
# Answers
# ---------------------------------------------------------------------------


def ok(tag: bytes, untagged: bytes = b"") -> bytes:
    """
    Build a completed answer.

    Args:
        tag (bytes): The tag of the command.
        untagged (bytes, optional): Untagged lines to send first, each ending in a line break.
            Default: none.

    Returns:
        bytes: The untagged lines, then ``<tag> OK done``.
    """
    return untagged + tag + b" OK done\r\n"


def refuse(tag: bytes, text: bytes, kind: bytes = b"NO") -> bytes:
    """
    Build a refusal.

    Args:
        tag (bytes): The tag of the command.
        text (bytes): What the server says.
        kind (bytes, optional): ``NO`` or ``BAD``. Default: ``NO``.

    Returns:
        bytes: The tagged refusal.
    """
    return tag + b" " + kind + b" " + text + b"\r\n"


def literal_fetch(uid: int, body: bytes) -> bytes:
    """
    Build the untagged line of a fetched message, its literal and the closing parenthesis.

    Args:
        uid (int): The UID.
        body (bytes): The message.

    Returns:
        bytes: What ``BODY.PEEK[]`` is answered with, before the tagged line.
    """
    return b"* 1 FETCH (UID %d BODY[]<0> {%d}\r\n" % (uid, len(body)) + body + b")\r\n"


# ---------------------------------------------------------------------------
# The peer
# ---------------------------------------------------------------------------


class ScriptedPeer:
    """
    The server end of a socket pair, answering commands from a handler in a thread.

    Attributes:
        client (socket.socket): The end the connection under test uses.
        received (list[bytes]): Every command line the client sent, without its line break.
    """

    def __init__(
        self,
        handler: Handler | None = None,
        greeting: bytes = b"* OK ready\r\n",
        capabilities: bytes = b"IMAP4rev1",
    ) -> None:
        """
        Start the server thread.

        Args:
            handler (Handler | None, optional): Answers every command but ``CAPABILITY`` and
                ``LOGOUT``; ``None`` answers ``OK`` to all. Default: ``None``.
            greeting (bytes, optional): What the server says first. Default: ``* OK ready``.
            capabilities (bytes, optional): What ``CAPABILITY`` lists. Default: ``IMAP4rev1``.
        """
        self.client, self._server = socket.socketpair()
        self.received: list[bytes] = []
        self._handler = handler
        self._greeting = greeting
        self._capabilities = capabilities
        self._stopping = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def send(self, data: bytes) -> None:
        """
        Write raw bytes to the client.

        Args:
            data (bytes): What to write.
        """
        self._server.sendall(data)

    def _lines(self) -> Iterator[bytes]:
        """
        Read command lines from the client until it leaves or the peer is told to stop.

        Yields:
            bytes: Each line, with its line break.
        """
        pending = b""
        while not self._stopping.is_set():
            line, found, rest = pending.partition(b"\n")
            if found:
                pending = rest
                yield line + found
                continue
            # A short wait instead of a blocking read: ``shutdown`` from another thread does not
            # wake a blocked ``recv`` on every system, and the join would run to its limit.
            if not select.select([self._server], [], [], _POLL)[0]:
                continue
            data = self._server.recv(65536)
            if not data:
                return
            pending += data

    def _serve(self) -> None:
        """Read command lines and answer them until the client leaves."""
        # The client may close first, or the test may close us: both end the loop.
        with contextlib.suppress(OSError, ValueError):
            self.send(self._greeting)
            for line in self._lines():
                text = line.rstrip(b"\r\n")
                self.received.append(text)
                tag, _, rest = text.partition(b" ")
                verb = rest.split(b" ")[0].upper()
                if verb == b"CAPABILITY":
                    self.send(ok(tag, b"* CAPABILITY " + self._capabilities + b"\r\n"))
                elif verb == b"LOGOUT":
                    self.send(ok(tag, b"* BYE bye\r\n"))
                    return
                else:
                    reply = ok(tag) if self._handler is None else self._handler(tag, text, self)
                    if reply is not None:
                        self.send(reply)

    def hang_up(self) -> None:
        """Cut the server end, as a server that drops the connection does, and wait for it."""
        self._stopping.set()
        with contextlib.suppress(OSError):
            self._server.shutdown(socket.SHUT_RDWR)
        self._thread.join(timeout=5)

    def close(self) -> None:
        """Close both ends and wait for the thread."""
        self.hang_up()
        for end in (self.client, self._server):
            with contextlib.suppress(OSError):
                end.close()

    def commands(self) -> list[bytes]:
        """
        List the commands the client sent, without their tags.

        Returns:
            list[bytes]: Each command line after its tag, in order.
        """
        return [line.partition(b" ")[2] for line in list(self.received)]


# ---------------------------------------------------------------------------
# The connection
# ---------------------------------------------------------------------------


class PairedImap(_Bounds):
    """The bounded connection over a plain ``IMAP4``, using the socket the test hands it."""

    def __init__(self, paired: socket.socket, **options: Any) -> None:
        """
        Connect to the peer and read its greeting.

        Args:
            paired (socket.socket): The client end of the socket pair.
            **options (Any): ``clock`` and ``deadline``.
        """
        self._paired = paired
        super().__init__("peer.invalid", 0, **options)

    def _create_socket(self, timeout: float | None) -> socket.socket:
        """
        Hand the library the socket of the pair instead of opening one.

        Args:
            timeout (float | None): Ignored; the bounds set the timeout before each read.

        Returns:
            socket.socket: The client end of the pair.
        """
        return self._paired


def open_mailbox(
    peer: ScriptedPeer,
    *,
    clock: Callable[[], float] = lambda: 0.0,
    deadline: float = 1_000_000.0,
    secret: str = CANARY,
    login: bool = True,
    selected: bool = False,
) -> ImapMailbox:
    """
    Wrap a connection to the peer in the mailbox under test, logged in.

    Args:
        peer (ScriptedPeer): The scripted server.
        clock (Callable[[], float], optional): The clock. Default: always zero.
        deadline (float, optional): The deadline, in the unit of ``clock``. Default: far away.
        secret (str, optional): The password to log in with and to scrub. Default: ``CANARY``.
        login (bool, optional): Whether to send the ``LOGIN``. Default: ``True``.
        selected (bool, optional): Whether to open ``INBOX`` on the connection, which the library
            requires before a search or a fetch; the mailbox's own ``select`` is not used, so a
            test that does not want an ``EXAMINE`` in the record can still reach them.
            Default: ``False``.

    Returns:
        ImapMailbox: The mailbox.
    """
    connection = PairedImap(peer.client, clock=clock, deadline=deadline)
    if login:
        connection.login(quote("reader"), secret)
    if selected:
        connection.select(quote("INBOX"), readonly=True)
    return ImapMailbox(connection, secret, clock, deadline)
