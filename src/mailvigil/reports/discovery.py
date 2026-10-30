"""
Discovery: from the paths a caller gave to the ordered list of files worth reading.

A path that is a file is always kept, because the user pointed at it on purpose. A path that is a
folder is searched for the providers' attachment names and for mail files (``.eml`` and ``.mbox``)
and nothing else, because a mail client's download folder holds much more than reports: one level
deep, or the subfolders too when the caller asks (ADR-9 of 002). The files with a report's suffix
whose name did not qualify are counted, so the reader learns that something was passed over. Each
file says whether the user named it or the search found it, which decides whether a mail file with
nothing in it is worth a word (ADR-5 of 007). The result is deterministic: the same paths give the
same files in the same order on every platform (RNF-05). Nothing here opens a file or looks at its
content; that is the reader's job.
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

# The suffixes of a report file. A file with one of them whose name is not the providers' is counted
# as passed over; a file with any other suffix is not, because a download folder holds thousands.
_REPORT_SUFFIXES = frozenset({".zip", ".gz", ".xml"})

# How many levels of subfolders ``--recursive`` goes down, below the folder the user named. A bound,
# so a very deep tree (or one a link brings back around) cannot keep the search busy for long.
MAX_FOLDER_DEPTH = 8

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


def _is_link(path: Path) -> bool:
    """
    Tell if a path is a symbolic link or, on Windows, a junction.

    Args:
        path (Path): The path to look at, without following it.

    Returns:
        bool: ``True`` for a link or a junction.
    """
    return path.is_symlink() or path.is_junction()


def _list_folder(
    folder: Path,
    recursive: bool,
    depth: int,
    skipped: list[SkippedFile],
    passed: list[Path],
) -> list[Path]:
    """
    List the attachments and mail files inside a folder, and below it when asked.

    Args:
        folder (Path): The folder to list.
        recursive (bool): ``True`` to go into the subfolders too.
        depth (int): How many levels below the folder the user named this one is; ``0`` for the
            folder itself.
        skipped (list[SkippedFile]): Receives a subfolder that cannot be listed, as ``UNREADABLE``;
            the folder the user named raises instead, so the caller reports it.
        passed (list[Path]): Receives the regular files with a report's suffix whose name does not
            qualify.

    Returns:
        list[Path]: The regular files whose name follows the attachment pattern or whose suffix is
            ``.eml`` or ``.mbox``: the folder's own, in name order, then those of each subfolder in
            name order, depth first. Everything else is left out without a word. A subfolder that
            is a link is not entered (it could lead back up), and none is entered past
            ``MAX_FOLDER_DEPTH``.

    Raises:
        OSError: When the folder cannot be listed and is the one the user named.
    """
    # Sorted by the name as a string, not by ``Path``: ``Path`` ordering is case-insensitive on
    # Windows and case-sensitive elsewhere, and the listing order is whatever the file system gives.
    entries = sorted(folder.iterdir(), key=lambda entry: entry.name)
    found: list[Path] = []
    for entry in entries:
        if _ATTACHMENT.fullmatch(entry.name) is not None or entry.suffix.lower() in _MAIL_SUFFIXES:
            if entry.is_file():
                found.append(entry)
        elif entry.suffix.lower() in _REPORT_SUFFIXES and entry.is_file():
            passed.append(entry)

    if recursive and depth < MAX_FOLDER_DEPTH:
        for entry in entries:
            if _is_link(entry) or not entry.is_dir():
                continue
            try:
                found.extend(_list_folder(entry, recursive, depth + 1, skipped, passed))
            except OSError as error:
                skipped.append(SkippedFile(entry, Reason.UNREADABLE, type(error).__name__))
    return found


def discover(
    paths: Sequence[Path], recursive: bool = False
) -> tuple[tuple[Source, ...], tuple[SkippedFile, ...], int]:
    """
    Turn the paths a caller gave into the files to read.

    Args:
        paths (Sequence[Path]): Files and folders, in the order the caller wants them read.
        recursive (bool, optional): ``True`` to search the subfolders of each folder too. Default:
            ``False``.

    Returns:
        tuple[tuple[Source, ...], tuple[SkippedFile, ...], int]: The files to read, in the order of
            ``paths`` (and by name inside each folder), each file once with the flag of the spelling
            that came first; the paths that could not be looked at, as ``UNREADABLE``; and how many
            files a folder search passed over for a name that is not the providers' although the
            suffix is a report's (a file the user named, or that was found, is not counted).
    """
    sources: list[Source] = []
    skipped: list[SkippedFile] = []
    seen: set[str] = set()
    passed_over: set[str] = set()

    for path in paths:
        passed: list[Path] = []
        try:
            # Anything but a folder is kept as given: a file whatever its name, and a pipe or a
            # device is left for the reader to refuse, which also keeps it from blocking the run.
            is_folder = stat.S_ISDIR(path.stat().st_mode)
            found = _list_folder(path, recursive, 0, skipped, passed) if is_folder else [path]
        except OSError as error:
            skipped.append(SkippedFile(path, Reason.UNREADABLE, type(error).__name__))
            continue

        passed_over.update(os.path.realpath(file) for file in passed)
        for file in found:
            # The real path, so a link, a ``..`` or a different case does not read a file twice;
            # the first spelling given is the one kept.
            key = os.path.realpath(file)
            if key not in seen:
                seen.add(key)
                sources.append(Source(file, explicit=not is_folder))

    # Taken at the end: a file passed over in one folder may be named, or found, by another path.
    return tuple(sources), tuple(skipped), len(passed_over - seen)
