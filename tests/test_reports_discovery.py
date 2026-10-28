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

from mailvigil.reports.discovery import Source, discover
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


def _paths(sources: tuple[Source, ...]) -> tuple[Path, ...]:
    """
    Reduce discovered sources to their paths, to compare the files without the flag.

    Args:
        sources (tuple[Source, ...]): The sources ``discover`` returned.

    Returns:
        tuple[Path, ...]: The paths, in the same order.
    """
    return tuple(source.path for source in sources)


def _names(sources: tuple[Source, ...]) -> list[str]:
    """
    Reduce discovered sources to their file names, to compare without the temporary folder.

    Args:
        sources (tuple[Source, ...]): The sources ``discover`` returned.

    Returns:
        list[str]: The file names, in the same order.
    """
    return [source.path.name for source in sources]


# ---------------------------------------------------------------------------
# Files and folders
# ---------------------------------------------------------------------------


def test_a_file_is_kept_whatever_its_name(tmp_path: Path) -> None:
    # The user pointed at it on purpose, so even a name no provider would use is read.
    chosen = _touch(tmp_path, "notes.txt")

    sources, skipped = discover([chosen])

    assert _paths(sources) == (chosen,)
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

    sources, skipped = discover([tmp_path])

    assert sorted(_paths(sources)) == sorted(kept)
    assert skipped == ()


def test_a_folder_keeps_the_copy_suffix_a_browser_adds(tmp_path: Path) -> None:
    copy = _touch(tmp_path, "google.com!example.com!1!2 (1).zip")
    _touch(tmp_path, "report (1).zip")  # no provider, domain or period: not an attachment

    sources, _ = discover([tmp_path])

    assert _paths(sources) == (copy,)


def test_subfolders_are_not_entered_and_are_not_reported(tmp_path: Path) -> None:
    inner = tmp_path / "inner"
    inner.mkdir()
    _touch(inner, _NAME)
    # A directory whose name looks like an attachment is still not a regular file.
    (tmp_path / "yahoo.com!example.com!1!2.zip").mkdir()

    sources, skipped = discover([tmp_path])

    assert sources == ()
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

    sources, _ = discover([tmp_path])

    assert _names(sources) == ["B!x!1!2.xml", "C!x!1!2.xml", "a!x!1!2.xml", "d!x!1!2.xml"]


def test_the_order_of_the_given_paths_is_kept(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    in_second = _touch(second, "a!x!1!2.xml")
    in_first = _touch(first, "z!x!1!2.xml")
    loose = _touch(tmp_path, "loose.txt")

    sources, _ = discover([second, loose, first])

    assert _paths(sources) == (in_second, loose, in_first)


def test_the_same_file_given_twice_is_read_once(tmp_path: Path) -> None:
    chosen = _touch(tmp_path, _NAME)

    sources, _ = discover([chosen, chosen])

    assert _paths(sources) == (chosen,)


def test_a_file_given_directly_and_through_its_folder_is_read_once(tmp_path: Path) -> None:
    chosen = _touch(tmp_path, _NAME)

    assert _paths(discover([chosen, tmp_path])[0]) == (chosen,)
    assert _paths(discover([tmp_path, chosen])[0]) == (chosen,)


def test_two_spellings_of_one_file_keep_the_first(tmp_path: Path) -> None:
    """A ``..`` in the path is the same file as the plain one; the first spelling given stays."""
    (tmp_path / "sub").mkdir()
    plain = _touch(tmp_path, _NAME)
    roundabout = tmp_path / "sub" / ".." / _NAME

    sources, _ = discover([roundabout, plain])

    assert _paths(sources) == (roundabout,)


# ---------------------------------------------------------------------------
# Mail files (RF-06, ADR-5)
# ---------------------------------------------------------------------------


def test_a_folder_lists_eml_and_mbox_files_whatever_their_names_and_case(tmp_path: Path) -> None:
    mail = [
        _touch(tmp_path, "message.eml"),
        _touch(tmp_path, "Inbox.MBOX"),
        _touch(tmp_path, "REPORT.Eml"),
    ]
    _touch(tmp_path, "notes.txt")
    _touch(tmp_path, "message.emlx")

    sources, skipped = discover([tmp_path])

    assert sorted(_paths(sources)) == sorted(mail)
    assert skipped == ()


def test_mail_files_and_attachments_share_one_name_order(tmp_path: Path) -> None:
    for name in ("b.eml", "a!x!1!2.zip", "C.mbox", "d!x!1!2.xml"):
        _touch(tmp_path, name)

    sources, _ = discover([tmp_path])

    assert _names(sources) == ["C.mbox", "a!x!1!2.zip", "b.eml", "d!x!1!2.xml"]


def test_a_mail_folder_does_not_enter_subfolders_or_list_a_folder_named_like_mail(
    tmp_path: Path,
) -> None:
    inner = tmp_path / "inner"
    inner.mkdir()
    _touch(inner, "deep.eml")
    (tmp_path / "folder.mbox").mkdir()

    sources, skipped = discover([tmp_path])

    assert sources == ()
    assert skipped == ()


def test_explicit_is_true_for_a_named_file_and_false_for_a_listed_one(tmp_path: Path) -> None:
    folder = tmp_path / "folder"
    folder.mkdir()
    listed_mail = _touch(folder, "listed.eml")
    listed_attachment = _touch(folder, _NAME)
    named = _touch(tmp_path, "named.eml")

    sources, _ = discover([named, folder])

    assert sources == (
        Source(named, explicit=True),
        Source(listed_attachment, explicit=False),
        Source(listed_mail, explicit=False),
    )


def test_a_file_named_twice_keeps_the_first_spelling_and_its_flag(tmp_path: Path) -> None:
    chosen = _touch(tmp_path, "inbox.eml")

    assert discover([chosen, tmp_path])[0] == (Source(chosen, explicit=True),)
    assert discover([tmp_path, chosen])[0] == (Source(chosen, explicit=False),)


# ---------------------------------------------------------------------------
# Paths that cannot be read
# ---------------------------------------------------------------------------


def test_a_missing_path_is_skipped_and_the_others_are_still_discovered(tmp_path: Path) -> None:
    missing = tmp_path / "nowhere.zip"
    good = _touch(tmp_path, _NAME)

    sources, skipped = discover([missing, tmp_path])

    assert _paths(sources) == (good,)
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

    sources, skipped = discover([locked, open_folder])

    assert _paths(sources) == (good,)
    assert [(entry.path, entry.reason) for entry in skipped] == [(locked, Reason.UNREADABLE)]
