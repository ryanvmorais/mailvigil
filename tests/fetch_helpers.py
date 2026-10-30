"""
Helpers shared by the tests of ``fetch``: a scripted mailbox, a clock moved by hand and a message.

``FakeMailbox`` stands in for the one adapter that speaks IMAP, so the loop of ``fetch`` runs with
no socket (spec 009, ADR-1). Nothing here is a real message, host or address (RNF-06).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from email.message import EmailMessage

from mailvigil.fetch.errors import FetchRefused
from mailvigil.fetch.model import SearchResult

# ---------------------------------------------------------------------------
# The clock
# ---------------------------------------------------------------------------


class ManualClock:
    """
    A clock that only moves when a test says so.

    Attributes:
        now (float): The current reading, in seconds.
    """

    def __init__(self, now: float = 0.0) -> None:
        """
        Build a clock.

        Args:
            now (float, optional): The first reading. Default: ``0.0``.
        """
        self.now = now

    def __call__(self) -> float:
        """
        Read the clock.

        Returns:
            float: The current reading.
        """
        return self.now

    def advance(self, seconds: float) -> None:
        """
        Move the clock forward.

        Args:
            seconds (float): How far to move it.
        """
        self.now += seconds


# ---------------------------------------------------------------------------
# The mailbox
# ---------------------------------------------------------------------------


@dataclass
class FakeMailbox:
    """
    A mailbox scripted from a dict of bodies, recording every call it gets.

    Attributes:
        bodies (dict[int, bytes | None]): What ``message`` returns for each UID; ``None`` is a
            server that gives no body. The keys are the UIDs the search lists.
        announced (dict[int, int]): Sizes ``sizes`` announces instead of ``len(body)``, so a
            message can be announced small and arrive large.
        unsized (set[int]): UIDs ``sizes`` does not answer for.
        validity (int): What ``select`` returns.
        dropped (int): The tokens the search says it could not use.
        listed (list[int] | None): The UIDs the search returns instead of the keys of ``bodies``,
            in the order given (to script duplicates and a wrong order).
        failures (dict[str, FetchRefused]): The refusal each method raises, by method name.
        message_failures (dict[int, FetchRefused]): The refusal ``message`` raises for a UID.
        on_message (Callable[[int], None] | None): Called with the UID at the start of ``message``,
            for a test to move the clock.
        calls (list[tuple[object, ...]]): Every call, as the method name and its arguments.
        closed (int): How many times ``close`` was called.
    """

    bodies: dict[int, bytes | None] = field(default_factory=dict)
    announced: dict[int, int] = field(default_factory=dict)
    unsized: set[int] = field(default_factory=set)
    validity: int = 1
    dropped: int = 0
    listed: list[int] | None = None
    failures: dict[str, FetchRefused] = field(default_factory=dict)
    message_failures: dict[int, FetchRefused] = field(default_factory=dict)
    on_message: Callable[[int], None] | None = None
    calls: list[tuple[object, ...]] = field(default_factory=list)
    closed: int = 0

    def _maybe_fail(self, method: str) -> None:
        """
        Raise the refusal scripted for a method, if any.

        Args:
            method (str): The method name.

        Raises:
            FetchRefused: The one in ``failures`` for that method.
        """
        if method in self.failures:
            raise self.failures[method]

    def select(self, folder: str) -> int:
        """
        Open a folder.

        Args:
            folder (str): The folder name.

        Returns:
            int: The scripted validity number.
        """
        self.calls.append(("select", folder))
        self._maybe_fail("select")
        return self.validity

    def search(self, since: date | None) -> SearchResult:
        """
        List the messages.

        Args:
            since (date | None): The lower bound, recorded and otherwise ignored.

        Returns:
            SearchResult: The scripted UIDs, ascending unless ``listed`` says otherwise.
        """
        self.calls.append(("search", since))
        self._maybe_fail("search")
        uids = self.listed if self.listed is not None else sorted(self.bodies)
        return SearchResult(tuple(uids), self.dropped)

    def sizes(self, uids: Sequence[int]) -> dict[int, int]:
        """
        Announce the size of each message.

        Args:
            uids (Sequence[int]): The messages to ask about.

        Returns:
            dict[int, int]: ``announced`` or the length of the body, without the ``unsized`` ones.
        """
        self.calls.append(("sizes", tuple(uids)))
        self._maybe_fail("sizes")
        answer: dict[int, int] = {}
        for uid in uids:
            if uid in self.unsized:
                continue
            body = self.bodies.get(uid)
            answer[uid] = self.announced.get(uid, len(body) if body is not None else 0)
        return answer

    def message(self, uid: int, limit: int) -> bytes | None:
        """
        Download one message, cut at ``limit + 1`` bytes as the protocol promises.

        Args:
            uid (int): The message.
            limit (int): The cap in bytes.

        Returns:
            bytes | None: The scripted body, or ``None`` when it has none.

        Raises:
            FetchRefused: The one scripted for that UID.
        """
        self.calls.append(("message", uid, limit))
        if self.on_message is not None:
            self.on_message(uid)
        if uid in self.message_failures:
            raise self.message_failures[uid]
        self._maybe_fail("message")
        body = self.bodies.get(uid)
        return None if body is None else body[: limit + 1]

    def close(self) -> None:
        """Count the goodbye."""
        self.calls.append(("close",))
        self.closed += 1

    def called(self, method: str) -> list[tuple[object, ...]]:
        """
        Pick the calls of one method.

        Args:
            method (str): The method name.

        Returns:
            list[tuple[object, ...]]: The recorded calls of that method, in order.
        """
        return [call for call in self.calls if call[0] == method]


# ---------------------------------------------------------------------------
# The certificate authority
# ---------------------------------------------------------------------------

# The subject of ``TEST_CA_PEM``, as ``SSLContext.get_ca_certs`` reports it.
TEST_CA_SUBJECT = ((("commonName", "MailVigil test CA (synthetic)"),),)

# A self-signed authority made for these tests alone, valid for a hundred years. Its private key was
# thrown away when it was made, so it can sign nothing and nobody can pose as a server with it.
TEST_CA_PEM = """-----BEGIN CERTIFICATE-----
MIIBtzCCAV2gAwIBAgIUTe+8YiNzm1FHH7yrGU8FY4orZ6UwCgYIKoZIzj0EAwIw
KDEmMCQGA1UEAwwdTWFpbFZpZ2lsIHRlc3QgQ0EgKHN5bnRoZXRpYykwIBcNMjYx
MDMwMTg0MzQzWhgPMjEyNjEwMDYxODQzNDNaMCgxJjAkBgNVBAMMHU1haWxWaWdp
bCB0ZXN0IENBIChzeW50aGV0aWMpMFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE
IMHZQPavayTvrcHXR3jSHtjUpxplUtSYkF4r5G+1Y8wlS0oHlIkL4hp0/D1P3PCf
XhB2uhbm1rVvwioUyqSq+aNjMGEwHwYDVR0jBBgwFoAUKBXSi3RdZTWxTi7vXpNq
NGTPAeswDwYDVR0TAQH/BAUwAwEB/zAOBgNVHQ8BAf8EBAMCAQYwHQYDVR0OBBYE
FCgV0ot0XWU1sU4u716TajRkzwHrMAoGCCqGSM49BAMCA0gAMEUCIQCcXVIwven/
pY05a3yF6V5psrSzTfK36GixJRaOOz96jQIgcBZ6eSqrBgbkQGlI+P9JPX5ub7N0
gewgVhWCZoaO7sE=
-----END CERTIFICATE-----
"""

# ---------------------------------------------------------------------------
# The message
# ---------------------------------------------------------------------------


def build_message(label: str = "a", *, padding: int = 0) -> bytes:
    """
    Build a small synthetic report message.

    Args:
        label (str, optional): Text in the body, so two messages differ. Default: ``"a"``.
        padding (int, optional): Extra bytes of body, to reach a size. Default: ``0``.

    Returns:
        bytes: The message as stored in an ``.eml``.
    """
    message = EmailMessage()
    message["From"] = "noreply@example.org"
    message["To"] = "dmarc@example.com"
    message["Subject"] = "Report Domain: example.com"
    message.set_content(f"{label}\n" + "x" * padding)
    return message.as_bytes()
