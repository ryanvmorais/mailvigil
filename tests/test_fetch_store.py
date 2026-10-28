"""
Tests of the store of ``fetch``: the file names, the atomic write and the stale temporary files
(spec 009, stage 2: RF-06, RF-07, RNF-05, ADR-6).

Isolation: every directory is a ``tmp_path``; no network, no environment variable. Failures of the
disk are made by replacing ``os.replace``, ``os.fsync``, ``os.unlink`` and ``os.fdopen`` in the
store module, so no test depends on a full disk or on file permissions. Hosts, users and folders are
invented (RNF-06).
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

import pytest

from mailvigil.fetch import store as store_module
from mailvigil.fetch.errors import FetchReason, FetchRefused
from mailvigil.fetch.store import Store, tag_of

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_HEX8 = re.compile(r"[0-9a-f]{8}")
_DAY = 24 * 60 * 60

# Text that must never reach a file name: separators, a parent reference, a reserved Windows name,
# control characters and a bidirectional override.
_HOSTILE = [
    "../../etc/passwd",
    "a/b\\c",
    "CON",
    "NUL.eml",
    "line\nbreak\x00nul",
    "‮gnp.exe",
    "x" * 5000,
    "",
]


def _store(tmp_path: Path, tag: str = "0badc0de") -> Store:
    """
    Build a store over a folder inside ``tmp_path``.

    Args:
        tmp_path (Path): The test's temporary directory.
        tag (str, optional): The tag of the store. Default: a fixed one.

    Returns:
        Store: A store whose directory does not exist yet.
    """
    return Store(tmp_path / "saved", tag)


def _files(directory: Path) -> list[str]:
    """
    List the names in a directory.

    Args:
        directory (Path): The directory to list.

    Returns:
        list[str]: The sorted names; empty when the directory does not exist.
    """
    return sorted(p.name for p in directory.iterdir()) if directory.exists() else []


def _boom(*_args: object, **_kwargs: object) -> None:
    """
    Stand in for a call of ``os`` that fails.

    Raises:
        OSError: Always, as a full disk does.
    """
    raise OSError(28, "No space left on device")


# ---------------------------------------------------------------------------
# The tag
# ---------------------------------------------------------------------------


def test_tag_is_eight_hex_digits() -> None:
    assert _HEX8.fullmatch(tag_of("imap.example.invalid", "ana", "INBOX"))


def test_tag_is_stable_for_the_same_mailbox() -> None:
    first = tag_of("imap.example.invalid", "ana", "INBOX")
    assert first == tag_of("imap.example.invalid", "ana", "INBOX")


@pytest.mark.parametrize(
    "other",
    [
        ("imap.other.invalid", "ana", "INBOX"),
        ("imap.example.invalid", "bia", "INBOX"),
        ("imap.example.invalid", "ana", "Reports"),
    ],
)
def test_tag_changes_when_host_user_or_folder_changes(other: tuple[str, str, str]) -> None:
    assert tag_of("imap.example.invalid", "ana", "INBOX") != tag_of(*other)


def test_tag_keeps_the_fields_apart() -> None:
    # Without a separator, ("ab", "c") and ("a", "bc") would hash the same text.
    assert tag_of("ab", "c", "f") != tag_of("a", "bc", "f")


@pytest.mark.parametrize("hostile", _HOSTILE)
def test_hostile_host_user_and_folder_give_only_a_tag(hostile: str) -> None:
    assert _HEX8.fullmatch(tag_of(hostile, hostile, hostile))


# ---------------------------------------------------------------------------
# The name
# ---------------------------------------------------------------------------


def test_name_is_tag_validity_uid(tmp_path: Path) -> None:
    assert _store(tmp_path, "0badc0de").name(7, 42) == "0badc0de-7-42.eml"


def test_name_stays_inside_the_directory(tmp_path: Path) -> None:
    store = _store(tmp_path, tag_of("../..", "\\", "CON"))
    name = store.name(2**32 - 1, 2**32 - 1)
    assert Path(name).name == name
    assert (store.directory / name).parent == store.directory


# ---------------------------------------------------------------------------
# has and save
# ---------------------------------------------------------------------------


def test_has_is_false_before_and_true_after_a_save(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert store.has(1, 10) is False
    store.save(1, 10, b"mail")
    assert store.has(1, 10) is True


def test_has_tells_messages_apart_by_validity_and_uid(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save(1, 10, b"mail")
    assert store.has(2, 10) is False
    assert store.has(1, 11) is False


def test_has_is_false_when_the_directory_does_not_exist(tmp_path: Path) -> None:
    assert _store(tmp_path).has(1, 1) is False


def test_save_creates_a_missing_directory_of_several_levels(tmp_path: Path) -> None:
    store = Store(tmp_path / "a" / "b" / "c", "0badc0de")
    store.save(1, 1, b"mail")
    assert (tmp_path / "a" / "b" / "c" / "0badc0de-1-1.eml").is_file()


def test_save_writes_the_exact_bytes_and_leaves_no_temporary_file(tmp_path: Path) -> None:
    store = _store(tmp_path)
    data = bytes(range(256)) + b"\r\nSubject: x\r\n"
    store.save(3, 9, data)
    assert (store.directory / store.name(3, 9)).read_bytes() == data
    assert _files(store.directory) == [store.name(3, 9)]


def test_two_saves_of_one_message_leave_one_correct_file(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save(1, 1, b"first")
    store.save(1, 1, b"second")
    assert _files(store.directory) == [store.name(1, 1)]
    assert (store.directory / store.name(1, 1)).read_bytes() == b"second"


def test_save_of_an_empty_message_is_a_file(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save(1, 1, b"")
    assert store.has(1, 1)


# ---------------------------------------------------------------------------
# Failures of the disk
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("call", ["replace", "fsync"])
def test_a_failing_os_call_is_write_failed_and_leaves_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, call: str
) -> None:
    store = _store(tmp_path)
    monkeypatch.setattr(store_module.os, call, _boom)
    with pytest.raises(FetchRefused) as caught:
        store.save(1, 1, b"mail")
    assert caught.value.reason is FetchReason.WRITE_FAILED
    assert _files(store.directory) == []


def test_a_failing_write_is_write_failed_and_leaves_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    real_fdopen = os.fdopen

    class _Full:
        """A file whose write fails like a full disk but whose descriptor still closes."""

        def __init__(self, fd: int) -> None:
            """Wrap the descriptor the store got from ``mkstemp``."""
            self._file = real_fdopen(fd, "wb")

        def __enter__(self) -> _Full:
            return self

        def __exit__(self, *_exc: object) -> None:
            self._file.close()

        def write(self, _data: bytes) -> int:
            raise OSError(28, "No space left on device")

    monkeypatch.setattr(store_module.os, "fdopen", lambda fd, _mode: _Full(fd))
    with pytest.raises(FetchRefused) as caught:
        store.save(1, 1, b"mail")
    assert caught.value.reason is FetchReason.WRITE_FAILED
    assert _files(store.directory) == []


def test_a_directory_that_cannot_be_created_is_write_failed(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_bytes(b"not a directory")
    with pytest.raises(FetchRefused) as caught:
        Store(blocker / "inside", "0badc0de").save(1, 1, b"mail")
    assert caught.value.reason is FetchReason.WRITE_FAILED


def test_a_failed_save_keeps_the_file_that_was_already_there(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    store.save(1, 1, b"good")
    monkeypatch.setattr(store_module.os, "replace", _boom)
    with pytest.raises(FetchRefused):
        store.save(1, 1, b"bad")
    assert (store.directory / store.name(1, 1)).read_bytes() == b"good"
    assert _files(store.directory) == [store.name(1, 1)]


def test_a_temporary_file_that_cannot_be_removed_does_not_hide_the_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    monkeypatch.setattr(store_module.os, "replace", _boom)
    monkeypatch.setattr(store_module.os, "unlink", _boom)
    with pytest.raises(FetchRefused) as caught:
        store.save(1, 1, b"mail")
    assert caught.value.reason is FetchReason.WRITE_FAILED


def test_the_detail_of_a_write_failure_is_cleaned_and_short(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)

    def hostile(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk\x00 full‮" + "x" * 500)

    monkeypatch.setattr(store_module.os, "replace", hostile)
    with pytest.raises(FetchRefused) as caught:
        store.save(1, 1, b"mail")
    assert len(caught.value.detail) <= 200
    assert "\x00" not in caught.value.detail
    assert "‮" not in caught.value.detail


# ---------------------------------------------------------------------------
# clean_stale
# ---------------------------------------------------------------------------


def _age(path: Path, seconds: float) -> None:
    """
    Make a file look ``seconds`` old.

    Args:
        path (Path): The file.
        seconds (float): How old it should seem.
    """
    moment = time.time() - seconds
    os.utime(path, (moment, moment))


def test_clean_stale_removes_an_old_partial_and_keeps_the_rest(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save(1, 1, b"mail")
    store.directory.joinpath(".mailvigil-old.partial").write_bytes(b"x")
    store.directory.joinpath(".mailvigil-new.partial").write_bytes(b"x")
    store.directory.joinpath("notes.txt").write_bytes(b"x")
    store.directory.joinpath(".mailvigil-odd.eml").write_bytes(b"x")
    _age(store.directory / ".mailvigil-old.partial", 2 * _DAY)
    _age(store.directory / ".mailvigil-new.partial", _DAY / 2)
    _age(store.directory / store.name(1, 1), 30 * _DAY)

    store.clean_stale()

    assert _files(store.directory) == sorted(
        [store.name(1, 1), ".mailvigil-new.partial", "notes.txt", ".mailvigil-odd.eml"]
    )


def test_clean_stale_without_a_directory_does_nothing(tmp_path: Path) -> None:
    _store(tmp_path).clean_stale()
    assert not (tmp_path / "saved").exists()


def test_clean_stale_ignores_a_failure_to_remove(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A stale file that cannot be removed is not a reason to refuse the run.
    store = _store(tmp_path)
    store.directory.mkdir()
    partial = store.directory / ".mailvigil-old.partial"
    partial.write_bytes(b"x")
    _age(partial, 2 * _DAY)
    monkeypatch.setattr(Path, "unlink", _boom)
    store.clean_stale()
    assert partial.exists()
