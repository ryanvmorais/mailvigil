"""
The vocabulary of refusals of ``fetch``: why a run could not finish.

A refusal is a typed exception carrying a machine-readable ``FetchReason``. The user-facing text is
built from the reason by the message catalog (English and Portuguese); the ``detail`` is a short
piece of what the library or the server said, cleaned and cut, for the person who has to fix the
cause (spec 009, RF-08). The module imports nothing that touches the network.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from mailvigil.text import clean_text

if TYPE_CHECKING:
    from mailvigil.fetch.model import FetchOutcome

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# The longest ``detail``: one line of a server's complaint is enough to act on, and a server can
# write as much as it likes.
DETAIL_LIMIT = 200

# ---------------------------------------------------------------------------
# Reasons
# ---------------------------------------------------------------------------


class FetchReason(StrEnum):
    """
    Why a fetch was refused.

    The values are the stable keys the catalog translates, so they never change once released.

    Attributes:
        HOST_UNREACHABLE (str): No DNS answer, connection refused or no route.
        TIMEOUT (str): A read or the connection passed the socket timeout.
        DEADLINE_EXCEEDED (str): The whole run passed its deadline.
        CERTIFICATE_INVALID (str): The server certificate failed verification; nothing was sent.
        TLS_FAILED (str): The handshake failed for another reason, such as an old TLS version.
        LOGIN_FAILED (str): The server said NO or BAD to the login.
        PASSWORD_UNUSABLE (str): The password is empty, non-ASCII or has a line break.
        PASSWORD_FILE (str): The password file is missing, unreadable or empty.
        FOLDER_NOT_FOUND (str): The server has no such folder.
        PROTOCOL_ERROR (str): An answer the bounds or the parsers refuse.
        TOO_MANY_MATCHES (str): The search answer passed the line limit.
        WRITE_FAILED (str): The disk refused a file (full, permission, interrupted).
    """

    HOST_UNREACHABLE = "host_unreachable"
    TIMEOUT = "timeout"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    CERTIFICATE_INVALID = "certificate_invalid"
    TLS_FAILED = "tls_failed"
    LOGIN_FAILED = "login_failed"
    PASSWORD_UNUSABLE = "password_unusable"
    PASSWORD_FILE = "password_file"
    FOLDER_NOT_FOUND = "folder_not_found"
    PROTOCOL_ERROR = "protocol_error"
    TOO_MANY_MATCHES = "too_many_matches"
    WRITE_FAILED = "write_failed"


# ---------------------------------------------------------------------------
# The refusal
# ---------------------------------------------------------------------------


class FetchRefused(Exception):
    """
    Raised when a fetch cannot finish.

    Attributes:
        reason (FetchReason): The machine-readable cause.
        detail (str): What the library or the server said, cleaned and at most ``DETAIL_LIMIT``
            characters. Empty when there is nothing safe to add (a refused login carries none).
        outcome (FetchOutcome | None): What the run had done before it stopped, so the command can
            say how many files are valid; ``None`` when it stopped before any work.
    """

    def __init__(
        self, reason: FetchReason, detail: str = "", outcome: FetchOutcome | None = None
    ) -> None:
        """
        Build a refusal.

        Args:
            reason (FetchReason): The machine-readable cause.
            detail (str, optional): Text from the library or the server; it is cleaned and cut
                here, so no caller can forget. Default: empty.
            outcome (FetchOutcome | None, optional): The work done before the refusal. Default:
                ``None``.
        """
        cleaned = clean_text(detail, DETAIL_LIMIT)
        super().__init__(reason, cleaned)
        self.reason = reason
        self.detail = cleaned
        self.outcome = outcome

    def __str__(self) -> str:
        """
        Describe the refusal for a log line.

        Returns:
            str: The reason value, followed by the detail when there is one.
        """
        return f"{self.reason.value}: {self.detail}" if self.detail else self.reason.value
