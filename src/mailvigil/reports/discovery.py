"""
Discovery: from the paths a caller gave to the ordered list of files worth reading.

A path that is a file is always kept, because the user pointed at it on purpose. A path that is a
folder is searched one level deep for the providers' attachment names and nothing else, because a
mail client's download folder holds much more than reports. The result is deterministic: the same
paths give the same files in the same order on every platform (RNF-05). Nothing here opens a file
or looks at its content; that is the reader's job.
"""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Sequence
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

# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def _list_folder(folder: Path) -> list[Path]:
    """
    List the attachments directly inside a folder, in name order.

    Args:
        folder (Path): The folder to list.

    Returns:
        list[Path]: The regular files whose name follows the attachment pattern. Subfolders and
            everything else are left out without a word.

    Raises:
        OSError: When the folder cannot be listed.
    """
    # Sorted by the name as a string, not by ``Path``: ``Path`` ordering is case-insensitive on
    # Windows and case-sensitive elsewhere, and the listing order is whatever the file system gives.
    entries = sorted(folder.iterdir(), key=lambda entry: entry.name)
    return [
        entry
        for entry in entries
        if _ATTACHMENT.fullmatch(entry.name) is not None and entry.is_file()
    ]


def discover(paths: Sequence[Path]) -> tuple[tuple[Path, ...], tuple[SkippedFile, ...]]:
    """
    Turn the paths a caller gave into the files to read.

    Args:
        paths (Sequence[Path]): Files and folders, in the order the caller wants them read.

    Returns:
        tuple[tuple[Path, ...], tuple[SkippedFile, ...]]: The files to read, in the order of
            ``paths`` (and by name inside each folder), each file once; and the paths that could not
            be looked at, as ``UNREADABLE``.
    """
    files: list[Path] = []
    skipped: list[SkippedFile] = []
    seen: set[str] = set()

    for path in paths:
        try:
            # Anything but a folder is kept as given: a file whatever its name, and a pipe or a
            # device is left for the reader to refuse, which also keeps it from blocking the run.
            found = _list_folder(path) if stat.S_ISDIR(path.stat().st_mode) else [path]
        except OSError as error:
            skipped.append(SkippedFile(path, Reason.UNREADABLE, type(error).__name__))
            continue

        for file in found:
            # The real path, so a link, a ``..`` or a different case does not read a file twice;
            # the first spelling given is the one kept.
            key = os.path.realpath(file)
            if key not in seen:
                seen.add(key)
                files.append(file)

    return tuple(files), tuple(skipped)
