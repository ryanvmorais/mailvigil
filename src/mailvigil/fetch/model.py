"""
The shapes ``fetch`` passes around: the outcome of a run, the constants, the ``Mailbox`` protocol.

``Mailbox`` is the seam of the package: ``run.py`` drives anything with these five methods, and
``imap.py`` is the one adapter that speaks IMAP, so the loop is tested with a fake and no socket
(spec 009, ADR-1). Changing a constant is a spec decision. The module imports no network code.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from mailvigil.reports.mail import MAX_MESSAGE_BYTES

__all__ = [
    "DEADLINE_SECONDS",
    "DEFAULT_LIMIT",
    "LINE_LIMIT",
    "LITERAL_OTHER",
    "MAX_LIMIT",
    "MAX_MESSAGE_BYTES",
    "SIZE_BATCH",
    "SOCKET_TIMEOUT",
    "UID_MAX",
    "FetchOutcome",
    "Mailbox",
    "SearchResult",
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# One silent read ends the run; a slow link still moves 8 MiB in chunks, each one under the limit.
SOCKET_TIMEOUT = 30

# 500 messages of a few hundred KB fit on any usable link in this time; more is a stuck run.
DEADLINE_SECONDS = 1800

# The newest 500 messages decide a verdict; 10,000 is a bounded disk.
DEFAULT_LIMIT = 500
MAX_LIMIT = 10_000

# UIDs per size query: one short command line per batch, and 500 messages cost 5 queries.
SIZE_BATCH = 100

# The library's own line limit; a SEARCH answer over it is ``too_many_matches``.
LINE_LIMIT = 1_000_000

# The biggest literal any command but the message fetch may announce.
LITERAL_OTHER = 64 * 1024

# The range IMAP allows for a UID and for a validity number (RFC 3501, section 2.3.1.1).
UID_MAX = 2**32 - 1

# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FetchOutcome:
    """
    What a run did, in six numbers that always add up.

    ``matched == saved + already + too_large + skipped + left`` holds for every run.

    Attributes:
        matched (int): Messages the server listed for the search, plus the tokens it sent that
            were not valid UIDs.
        saved (int): Messages written in this run.
        already (int): Messages found on disk by name and so not downloaded.
        too_large (int): Messages announced over the cap, or cut at the cap while arriving.
        skipped (int): A UID that could not be used, or a message the server would not give.
        left (int): New messages beyond ``--limit`` or beyond the deadline, for a later run.
    """

    matched: int
    saved: int
    already: int
    too_large: int
    skipped: int
    left: int


@dataclass(frozen=True, slots=True)
class SearchResult:
    """
    The answer of a search, with what was not a usable UID counted instead of dropped silently.

    Attributes:
        uids (tuple[int, ...]): The valid UIDs, in the order the server sent them.
        dropped (int): The tokens that were not an integer in ``1..UID_MAX``.
    """

    uids: tuple[int, ...]
    dropped: int


# ---------------------------------------------------------------------------
# The protocol
# ---------------------------------------------------------------------------


class Mailbox(Protocol):
    """
    A mailbox that can be read and never changed, as ``run.py`` sees it.

    Every method may raise ``FetchRefused``. The caller closes the mailbox in a ``finally``.
    """

    def select(self, folder: str) -> int:
        """
        Open a folder read-only.

        Args:
            folder (str): The folder name as the user typed it.

        Returns:
            int: The validity number of the folder, in ``1..UID_MAX``.
        """
        ...

    def search(self, since: date | None) -> SearchResult:
        """
        List the messages that look like DMARC reports.

        Args:
            since (date | None): Only messages received on or after this day; ``None`` for all.

        Returns:
            SearchResult: The valid UIDs, ascending, and the count of tokens that were not UIDs.
        """
        ...

    def sizes(self, uids: Sequence[int]) -> dict[int, int]:
        """
        Ask the size the server announces for each message.

        Args:
            uids (Sequence[int]): The messages to ask about.

        Returns:
            dict[int, int]: The announced size in bytes; a UID the server did not answer for is
                missing.
        """
        ...

    def message(self, uid: int, limit: int) -> bytes | None:
        """
        Download one message without marking it read.

        Args:
            uid (int): The message.
            limit (int): The cap in bytes; the answer holds at most ``limit + 1`` bytes.

        Returns:
            bytes | None: The raw message, or ``None`` when the server gives no body.
        """
        ...

    def close(self) -> None:
        """Say goodbye to the server and drop the connection; a failure here is ignored."""
        ...
