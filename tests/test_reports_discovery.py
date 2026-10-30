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

from mailvigil.reports.discovery import MAX_FOLDER_DEPTH, Source, discover
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

    sources, skipped, _ = discover([chosen])

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

    sources, skipped, _ = discover([tmp_path])

    assert sorted(_paths(sources)) == sorted(kept)
    assert skipped == ()


def test_a_folder_keeps_the_copy_suffix_a_browser_adds(tmp_path: Path) -> None:
    copy = _touch(tmp_path, "google.com!example.com!1!2 (1).zip")
    _touch(tmp_path, "report (1).zip")  # no provider, domain or period: not an attachment

    sources, _, _ = discover([tmp_path])

    assert _paths(sources) == (copy,)


def test_subfolders_are_not_entered_and_are_not_reported(tmp_path: Path) -> None:
    inner = tmp_path / "inner"
    inner.mkdir()
    _touch(inner, _NAME)
    # A directory whose name looks like an attachment is still not a regular file.
    (tmp_path / "yahoo.com!example.com!1!2.zip").mkdir()

    sources, skipped, _ = discover([tmp_path])

    assert sources == ()
    assert skipped == ()


def test_an_empty_folder_and_no_paths_give_nothing(tmp_path: Path) -> None:
    assert discover([tmp_path]) == ((), (), 0)
    assert discover([]) == ((), (), 0)


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

    sources, _, _ = discover([tmp_path])

    assert _names(sources) == ["B!x!1!2.xml", "C!x!1!2.xml", "a!x!1!2.xml", "d!x!1!2.xml"]


def test_the_order_of_the_given_paths_is_kept(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    in_second = _touch(second, "a!x!1!2.xml")
    in_first = _touch(first, "z!x!1!2.xml")
    loose = _touch(tmp_path, "loose.txt")

    sources, _, _ = discover([second, loose, first])

    assert _paths(sources) == (in_second, loose, in_first)


def test_the_same_file_given_twice_is_read_once(tmp_path: Path) -> None:
    chosen = _touch(tmp_path, _NAME)

    sources, _, _ = discover([chosen, chosen])

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

    sources, _, _ = discover([roundabout, plain])

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

    sources, skipped, _ = discover([tmp_path])

    assert sorted(_paths(sources)) == sorted(mail)
    assert skipped == ()


def test_mail_files_and_attachments_share_one_name_order(tmp_path: Path) -> None:
    for name in ("b.eml", "a!x!1!2.zip", "C.mbox", "d!x!1!2.xml"):
        _touch(tmp_path, name)

    sources, _, _ = discover([tmp_path])

    assert _names(sources) == ["C.mbox", "a!x!1!2.zip", "b.eml", "d!x!1!2.xml"]


def test_a_mail_folder_does_not_enter_subfolders_or_list_a_folder_named_like_mail(
    tmp_path: Path,
) -> None:
    inner = tmp_path / "inner"
    inner.mkdir()
    _touch(inner, "deep.eml")
    (tmp_path / "folder.mbox").mkdir()

    sources, skipped, _ = discover([tmp_path])

    assert sources == ()
    assert skipped == ()


def test_explicit_is_true_for_a_named_file_and_false_for_a_listed_one(tmp_path: Path) -> None:
    folder = tmp_path / "folder"
    folder.mkdir()
    listed_mail = _touch(folder, "listed.eml")
    listed_attachment = _touch(folder, _NAME)
    named = _touch(tmp_path, "named.eml")

    sources, _, _ = discover([named, folder])

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

    sources, skipped, _ = discover([missing, tmp_path])

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

    sources, skipped, _ = discover([locked, open_folder])

    assert _paths(sources) == (good,)
    assert [(entry.path, entry.reason) for entry in skipped] == [(locked, Reason.UNREADABLE)]


# ---------------------------------------------------------------------------
# Subfolders and the files passed over (ADR-9 of 002)
# ---------------------------------------------------------------------------


def _nest(root: Path, *parts: str) -> Path:
    """
    Create nested folders.

    Args:
        root (Path): The folder to start from.
        *parts (str): The folder names, outermost first.

    Returns:
        Path: The innermost folder.
    """
    folder = root.joinpath(*parts)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def test_subfolders_are_searched_only_when_asked(tmp_path: Path) -> None:
    top = _touch(tmp_path, _NAME)
    deep = _touch(_nest(tmp_path, "2026-09"), _NAME)

    assert _paths(discover([tmp_path])[0]) == (top,)
    assert _paths(discover([tmp_path], recursive=True)[0]) == (top, deep)


def test_a_recursive_search_lists_a_folder_then_its_subfolders_in_name_order(
    tmp_path: Path,
) -> None:
    _touch(_nest(tmp_path, "b"), "z!x!1!2.xml")
    _touch(_nest(tmp_path, "a", "inner"), "y!x!1!2.xml")
    _touch(_nest(tmp_path, "a"), "x!x!1!2.xml")
    _touch(tmp_path, "w!x!1!2.xml")

    sources, _, _ = discover([tmp_path], recursive=True)

    assert [source.path.relative_to(tmp_path).as_posix() for source in sources] == [
        "w!x!1!2.xml",
        "a/x!x!1!2.xml",
        "a/inner/y!x!1!2.xml",
        "b/z!x!1!2.xml",
    ]
    assert not any(source.explicit for source in sources)


def test_a_recursive_search_stops_at_the_depth_limit(tmp_path: Path) -> None:
    folder = tmp_path
    expected = []
    for level in range(MAX_FOLDER_DEPTH + 2):
        expected.append(_touch(folder, _NAME))
        folder = _nest(folder, f"level{level}")

    sources, _, _ = discover([tmp_path], recursive=True)

    # The folder named by the user is level 0 and ``MAX_FOLDER_DEPTH`` levels lie below it.
    assert _paths(sources) == tuple(expected[: MAX_FOLDER_DEPTH + 1])


def test_a_recursive_search_does_not_enter_a_linked_folder(tmp_path: Path) -> None:
    real = _nest(tmp_path, "real")
    _touch(real, _NAME)
    link = tmp_path / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("the system does not let this user create a symbolic link")

    sources, _, _ = discover([tmp_path], recursive=True)

    assert _paths(sources) == (real / _NAME,)


def test_a_folder_the_system_reports_as_a_link_is_not_entered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Standing in for a link or a junction, which not every user may create (Windows asks for a
    # privilege); the walk asks the path, so the answer is what counts.
    linked = _nest(tmp_path, "linked")
    _touch(linked, _NAME)
    kept = _touch(_nest(tmp_path, "plain"), _NAME)
    real_is_symlink = Path.is_symlink

    def is_symlink(self: Path) -> bool:
        """Say ``linked`` is a link and ask the system about everything else."""
        return self == linked or real_is_symlink(self)

    monkeypatch.setattr(Path, "is_symlink", is_symlink)

    assert _paths(discover([tmp_path], recursive=True)[0]) == (kept,)


def test_a_folder_that_leads_back_up_does_not_loop(tmp_path: Path) -> None:
    inner = _nest(tmp_path, "inner")
    _touch(inner, _NAME)
    try:
        (inner / "back").symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pytest.skip("the system does not let this user create a symbolic link")

    sources, skipped, _ = discover([tmp_path], recursive=True)

    assert _paths(sources) == (inner / _NAME,)
    assert skipped == ()


def test_a_subfolder_that_cannot_be_listed_is_skipped_and_the_rest_is_still_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    locked = _nest(tmp_path, "locked")
    good = _touch(_nest(tmp_path, "open"), _NAME)
    real_iterdir = Path.iterdir

    def iterdir(self: Path) -> Iterator[Path]:
        """List any folder as usual, except ``locked``, which pretends to deny permission."""
        if self == locked:
            raise PermissionError(13, "denied")
        return real_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", iterdir)

    sources, skipped, _ = discover([tmp_path], recursive=True)

    assert _paths(sources) == (good,)
    assert [(entry.path, entry.reason) for entry in skipped] == [(locked, Reason.UNREADABLE)]


def test_a_report_suffix_with_another_name_is_counted_as_passed_over(tmp_path: Path) -> None:
    _touch(tmp_path, _NAME)
    for name in ("renamed.zip", "Report.XML", "mine.xml.gz", "notes.txt", "photo.png", "x.eml"):
        _touch(tmp_path, name)

    sources, _, passed_over = discover([tmp_path])

    # ``notes.txt`` and ``photo.png`` are not report suffixes, and ``x.eml`` is a candidate.
    assert _names(sources) == [_NAME, "x.eml"]
    assert passed_over == 3


def test_a_subfolder_is_not_counted_unless_it_is_searched(tmp_path: Path) -> None:
    _touch(_nest(tmp_path, "month"), "renamed.zip")

    assert discover([tmp_path])[2] == 0
    assert discover([tmp_path], recursive=True)[2] == 1


def test_a_named_file_and_a_clean_folder_pass_nothing_over(tmp_path: Path) -> None:
    renamed = _touch(tmp_path, "renamed.zip")
    clean = _nest(tmp_path, "clean")
    _touch(clean, _NAME)

    assert discover([renamed])[2] == 0
    assert discover([clean])[2] == 0


def test_a_file_passed_over_in_one_folder_and_named_by_another_path_is_not_counted(
    tmp_path: Path,
) -> None:
    renamed = _touch(tmp_path, "renamed.zip")

    sources, _, passed_over = discover([tmp_path, renamed])

    assert _paths(sources) == (renamed,)
    assert passed_over == 0


def test_the_same_folder_given_twice_counts_a_file_once(tmp_path: Path) -> None:
    _touch(tmp_path, "renamed.zip")

    assert discover([tmp_path, tmp_path])[2] == 1
