"""
Discovery: from the paths a caller gave to the ordered list of files worth reading.

A path that is a file is always kept, because the user pointed at it on purpose. A path that is a
folder is searched one level deep for the providers' attachment names and for mail files (``.eml``
and ``.mbox``) and nothing else, because a mail client's download folder holds much more than
reports. Each file says whether the user named it or the search found it, which decides whether a
mail file with nothing in it is worth a word (ADR-5 of 007). The result is deterministic: the same
paths give the same files in the same order on every platform (RNF-05). Nothing here opens a file
or looks at its content; that is the reader's job.
"""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from mailvigil.reports.errors import Reason
from mailvigil.reports.model import SkippedFile

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# The attachment name the providers use, ``provider!domain!begin!end.ext``, possibly followed by a
# ``(1)`` the browser adds to a second download. Carried over from the source script. ``ASCII``
# keeps ``\d`` to ``0-9``, so a period written in another script does not pass for a timestamp.
_ATTACHMENT = re.compile(r"[^!]+![^!]+!\d+!\d+.*\.(zip|gz|xml)", re.IGNORECASE | re.ASCII)

# A mail file is recognized by its suffix alone, whatever its name: a client saves a message under
# its subject and a mailbox under the name of the folder it exports.
_MAIL_SUFFIXES = frozenset({".eml", ".mbox"})

# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Source:
    """
    A file to read, and how it came to be on the list.

    Attributes:
        path (Path): The file as the caller or the folder listing gave it.
        explicit (bool): ``True`` when the user named the file, ``False`` when a folder search
            found it.
    """

    path: Path
    explicit: bool


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def _list_folder(folder: Path) -> list[Path]:
    """
    List the attachments and mail files directly inside a folder, in name order.

    Args:
        folder (Path): The folder to list.

    Returns:
        list[Path]: The regular files whose name follows the attachment pattern or whose suffix is
            ``.eml`` or ``.mbox``, in one name order. Subfolders and everything else are left out
            without a word.

    Raises:
        OSError: When the folder cannot be listed.
    """
    # Sorted by the name as a string, not by ``Path``: ``Path`` ordering is case-insensitive on
    # Windows and case-sensitive elsewhere, and the listing order is whatever the file system gives.
    entries = sorted(folder.iterdir(), key=lambda entry: entry.name)
    return [
        entry
        for entry in entries
        if (_ATTACHMENT.fullmatch(entry.name) is not None or entry.suffix.lower() in _MAIL_SUFFIXES)
        and entry.is_file()
    ]


def discover(paths: Sequence[Path]) -> tuple[tuple[Source, ...], tuple[SkippedFile, ...]]:
    """
    Turn the paths a caller gave into the files to read.

    Args:
        paths (Sequence[Path]): Files and folders, in the order the caller wants them read.

    Returns:
        tuple[tuple[Source, ...], tuple[SkippedFile, ...]]: The files to read, in the order of
            ``paths`` (and by name inside each folder), each file once with the flag of the spelling
            that came first; and the paths that could not be looked at, as ``UNREADABLE``.
    """
    sources: list[Source] = []
    skipped: list[SkippedFile] = []
    seen: set[str] = set()

    for path in paths:
        try:
            # Anything but a folder is kept as given: a file whatever its name, and a pipe or a
            # device is left for the reader to refuse, which also keeps it from blocking the run.
            is_folder = stat.S_ISDIR(path.stat().st_mode)
            found = _list_folder(path) if is_folder else [path]
        except OSError as error:
            skipped.append(SkippedFile(path, Reason.UNREADABLE, type(error).__name__))
            continue

        for file in found:
            # The real path, so a link, a ``..`` or a different case does not read a file twice;
            # the first spelling given is the one kept.
            key = os.path.realpath(file)
            if key not in seen:
                seen.add(key)
                sources.append(Source(file, explicit=not is_folder))

    return tuple(sources), tuple(skipped)
