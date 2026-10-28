"""
The folder where ``fetch`` keeps the messages it downloaded: their names and an atomic write.

A file is named ``<tag>-<validity>-<uid>.eml``. The tag is a hash of host, user and folder, so two
mailboxes saving into one directory cannot take each other's files; the validity number and the UID
are integers the caller already range-checked, so nothing a third party writes reaches a path. A
message is written to a temporary file in the same directory and moved onto its final name, so a
crash leaves either the whole file or none of it. The module knows nothing about the network
(spec 009, ADR-6).
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import tempfile
import time
from pathlib import Path

from mailvigil.fetch.errors import FetchReason, FetchRefused

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Eight hex digits are 32 bits: enough to tell the few mailboxes one person fetches apart.
TAG_LENGTH = 8

# The shape of a temporary file, so ``clean_stale`` touches nothing else in the directory.
_PARTIAL_PREFIX = ".mailvigil-"
_PARTIAL_SUFFIX = ".partial"

# A run lasts at most 30 minutes (``DEADLINE_SECONDS``), so a temporary file a day old is a crash;
# a younger one may belong to a run in progress.
_STALE_SECONDS = 24 * 60 * 60

# ---------------------------------------------------------------------------
# The tag
# ---------------------------------------------------------------------------


def tag_of(host: str, user: str, folder: str) -> str:
    """
    Build the tag that keeps one mailbox's files apart from another's.

    Args:
        host (str): The server host name.
        user (str): The login.
        folder (str): The folder as the user typed it.

    Returns:
        str: Eight lowercase hex digits, the same for the same three values and nothing else, so
            hostile text cannot shape a file name.
    """
    # NUL cannot occur in a host, user or folder, so the fields cannot run into each other.
    digest = hashlib.sha256(f"{host}\0{user}\0{folder}".encode(errors="surrogatepass"))
    return digest.hexdigest()[:TAG_LENGTH]


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------


class Store:
    """
    A directory of saved messages, written atomically.

    Attributes:
        directory (Path): Where the files go; created on the first save.
        tag (str): The mailbox tag that starts every file name.
    """

    def __init__(self, directory: Path, tag: str) -> None:
        """
        Build a store; nothing is touched on disk yet.

        Args:
            directory (Path): Where the files go.
            tag (str): The mailbox tag, from ``tag_of``.
        """
        self.directory = directory
        self.tag = tag

    def name(self, validity: int, uid: int) -> str:
        """
        Build the file name of a message.

        Args:
            validity (int): The validity number of the folder.
            uid (int): The UID of the message.

        Returns:
            str: ``<tag>-<validity>-<uid>.eml``, built from the tag and two integers only.
        """
        return f"{self.tag}-{validity}-{uid}.eml"

    def has(self, validity: int, uid: int) -> bool:
        """
        Tell whether a message was saved already.

        Args:
            validity (int): The validity number of the folder.
            uid (int): The UID of the message.

        Returns:
            bool: ``True`` when its file is there.
        """
        return (self.directory / self.name(validity, uid)).is_file()

    def save(self, validity: int, uid: int, data: bytes) -> None:
        """
        Write a message so that it is either whole or absent.

        Args:
            validity (int): The validity number of the folder.
            uid (int): The UID of the message.
            data (bytes): The raw message.

        Raises:
            FetchRefused: With ``write_failed`` when the disk refuses anything; the temporary file
                is removed and a file already saved under that name is left as it was.
        """
        temporary: str | None = None
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            # Same directory as the target, so ``os.replace`` stays on one volume and is atomic.
            fd, temporary = tempfile.mkstemp(
                prefix=_PARTIAL_PREFIX, suffix=_PARTIAL_SUFFIX, dir=self.directory
            )
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.directory / self.name(validity, uid))
            temporary = None
        except OSError as exc:
            raise FetchRefused(FetchReason.WRITE_FAILED, str(exc)) from exc
        finally:
            if temporary is not None:
                # Best effort: the refusal above is the news, a leftover is for ``clean_stale``.
                with contextlib.suppress(OSError):
                    os.unlink(temporary)

    def clean_stale(self) -> None:
        """
        Remove the temporary files a crashed run left behind.

        Only ``.mailvigil-*.partial`` files older than a day go; saved messages and anything else
        in the directory stay. A file that cannot be removed is skipped: it is not a reason to
        refuse a run.
        """
        if not self.directory.is_dir():
            return
        limit = time.time() - _STALE_SECONDS
        for path in self.directory.glob(f"{_PARTIAL_PREFIX}*{_PARTIAL_SUFFIX}"):
            try:
                if path.is_file() and path.stat().st_mtime < limit:
                    path.unlink()
            except OSError:
                continue
