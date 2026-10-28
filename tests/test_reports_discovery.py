"""
Tests of discovery (RF-06, RNF-05): which files ``discover`` hands to the reader, and in what order.

Isolation: discovery looks at names and file types only, never at content, so the files here are
empty and live under ``tmp_path``; nothing touches the network or an environment variable. The one
test that needs a folder that cannot be listed replaces ``Path.iterdir`` for that folder, because a
permission error cannot be built the same way on every platform.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from mailvigil.reports.discovery import discover
from mailvigil.reports.errors import Reason

# A name that follows the providers' attachment pattern, ``provider!domain!begin!end.ext``.
_NAME = "google.com!example.com!1790000000!1790086399.zip"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _touch(directory: Path, name: str) -> Path:
    """
    Create an empty regular file.

    Args:
        directory (Path): Where to create it, normally ``tmp_path`` or a folder under it.
        name (str): The file name, which is what discovery looks at.

    Returns:
        Path: The file created.
    """
    path = directory / name
    path.touch()
    return path


def _names(files: tuple[Path, ...]) -> list[str]:
    """
    Reduce discovered files to their names, to compare without the temporary folder.

    Args:
        files (tuple[Path, ...]): The files ``discover`` returned.

    Returns:
        list[str]: The file names, in the same order.
    """
    return [file.name for file in files]


# ---------------------------------------------------------------------------
# Files and folders
# ---------------------------------------------------------------------------


def test_a_file_is_kept_whatever_its_name(tmp_path: Path) -> None:
    # The user pointed at it on purpose, so even a name no provider would use is read.
    chosen = _touch(tmp_path, "notes.txt")

    files, skipped = discover([chosen])

    assert files == (chosen,)
    assert skipped == ()


def test_a_folder_keeps_only_names_that_follow_the_attachment_pattern(tmp_path: Path) -> None:
    kept = [
        _touch(tmp_path, _NAME),
        _touch(tmp_path, "yahoo.com!example.com!1!2.xml.gz"),
        _touch(tmp_path, "Outlook.com!example.com!1!2!extra.XML"),
    ]
    for ignored in (
        "report.zip",
        "notes.txt",
        "google.com!example.com!begin!end.zip",
        "!example.com!1!2.zip",
        "google.com!example.com!1!2.csv",
    ):
        _touch(tmp_path, ignored)

    files, skipped = discover([tmp_path])

    assert sorted(files) == sorted(kept)
    assert skipped == ()


def test_a_folder_keeps_the_copy_suffix_a_browser_adds(tmp_path: Path) -> None:
    copy = _touch(tmp_path, "google.com!example.com!1!2 (1).zip")
    _touch(tmp_path, "report (1).zip")  # no provider, domain or period: not an attachment

    files, _ = discover([tmp_path])

    assert files == (copy,)


def test_subfolders_are_not_entered_and_are_not_reported(tmp_path: Path) -> None:
    inner = tmp_path / "inner"
    inner.mkdir()
    _touch(inner, _NAME)
    # A directory whose name looks like an attachment is still not a regular file.
    (tmp_path / "yahoo.com!example.com!1!2.zip").mkdir()

    files, skipped = discover([tmp_path])

    assert files == ()
    assert skipped == ()


def test_an_empty_folder_and_no_paths_give_nothing(tmp_path: Path) -> None:
    assert discover([tmp_path]) == ((), ())
    assert discover([]) == ((), ())


# ---------------------------------------------------------------------------
# Order and duplicates
# ---------------------------------------------------------------------------


def test_a_folder_is_listed_in_name_order_whatever_the_case(tmp_path: Path) -> None:
    """Files come sorted by the name as a string, the same on every platform."""
    # ``Path`` ordering is case-insensitive on Windows and case-sensitive on Linux, and a listing
    # follows the file system. Sorting the name as a string gives the same order everywhere: every
    # upper-case letter before any lower-case one, so "C" comes before "a". (Names that differ only
    # in case cannot coexist on Windows, so these differ in the letter.)
    for name in ("a!x!1!2.xml", "C!x!1!2.xml", "B!x!1!2.xml", "d!x!1!2.xml"):
        _touch(tmp_path, name)

    files, _ = discover([tmp_path])

    assert _names(files) == ["B!x!1!2.xml", "C!x!1!2.xml", "a!x!1!2.xml", "d!x!1!2.xml"]


def test_the_order_of_the_given_paths_is_kept(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    in_second = _touch(second, "a!x!1!2.xml")
    in_first = _touch(first, "z!x!1!2.xml")
    loose = _touch(tmp_path, "loose.txt")

    files, _ = discover([second, loose, first])

    assert files == (in_second, loose, in_first)


def test_the_same_file_given_twice_is_read_once(tmp_path: Path) -> None:
    chosen = _touch(tmp_path, _NAME)

    files, _ = discover([chosen, chosen])

    assert files == (chosen,)


def test_a_file_given_directly_and_through_its_folder_is_read_once(tmp_path: Path) -> None:
    chosen = _touch(tmp_path, _NAME)

    assert discover([chosen, tmp_path])[0] == (chosen,)
    assert discover([tmp_path, chosen])[0] == (chosen,)


def test_two_spellings_of_one_file_keep_the_first(tmp_path: Path) -> None:
    """A ``..`` in the path is the same file as the plain one; the first spelling given stays."""
    (tmp_path / "sub").mkdir()
    plain = _touch(tmp_path, _NAME)
    roundabout = tmp_path / "sub" / ".." / _NAME

    files, _ = discover([roundabout, plain])

    assert files == (roundabout,)


# ---------------------------------------------------------------------------
# Paths that cannot be read
# ---------------------------------------------------------------------------


def test_a_missing_path_is_skipped_and_the_others_are_still_discovered(tmp_path: Path) -> None:
    missing = tmp_path / "nowhere.zip"
    good = _touch(tmp_path, _NAME)

    files, skipped = discover([missing, tmp_path])

    assert files == (good,)
    assert [(entry.path, entry.reason) for entry in skipped] == [(missing, Reason.UNREADABLE)]
    assert skipped[0].detail  # names the cause, for logs


def test_a_folder_that_cannot_be_listed_is_skipped_and_the_others_are_still_discovered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    locked = tmp_path / "locked"
    locked.mkdir()
    open_folder = tmp_path / "open"
    open_folder.mkdir()
    good = _touch(open_folder, _NAME)
    real_iterdir = Path.iterdir

    def iterdir(self: Path) -> Iterator[Path]:
        """List any folder as usual, except ``locked``, which pretends to deny permission."""
        if self == locked:
            raise PermissionError(13, "denied")
        return real_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", iterdir)

    files, skipped = discover([locked, open_folder])

    assert files == (good,)
    assert [(entry.path, entry.reason) for entry in skipped] == [(locked, Reason.UNREADABLE)]
