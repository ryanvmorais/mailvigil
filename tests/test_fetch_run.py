"""
Tests of the loop of ``fetch`` against a fake mailbox (spec 009, stage 3: RF-04, RF-05, RF-07,
RF-08, RNF-03, RNF-04, ADR-1, ADR-8).

Isolation: the mailbox is a ``FakeMailbox`` and the clock a ``ManualClock``, so nothing opens a
socket or waits; every store is a folder inside ``tmp_path``. Messages are synthetic (RNF-06).
Closing the mailbox belongs to the command that opened it, so it is tested with the command, not
here.
"""

from __future__ import annotations

import ast
import os
import time
from datetime import date
from pathlib import Path

import pytest

from fetch_helpers import FakeMailbox, ManualClock, build_message
from mailvigil.fetch import run as run_module
from mailvigil.fetch.errors import FetchReason, FetchRefused
from mailvigil.fetch.model import MAX_MESSAGE_BYTES, FetchOutcome
from mailvigil.fetch.run import fetch_reports
from mailvigil.fetch.store import Store

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAR = 10_000.0


def _store(tmp_path: Path) -> Store:
    """
    Build a store over a folder inside ``tmp_path``.

    Args:
        tmp_path (Path): The test's temporary directory.

    Returns:
        Store: A store whose directory does not exist yet.
    """
    return Store(tmp_path / "saved", "0badc0de")


def _mailbox(*uids: int, validity: int = 1) -> FakeMailbox:
    """
    Build a mailbox that holds one small message per UID.

    Args:
        *uids (int): The UIDs.
        validity (int, optional): The validity number of the folder. Default: ``1``.

    Returns:
        FakeMailbox: A mailbox whose body for each UID is distinct.
    """
    return FakeMailbox(
        bodies={uid: build_message(f"message {uid}") for uid in uids}, validity=validity
    )


def _run(
    mailbox: FakeMailbox,
    store: Store,
    *,
    limit: int = 500,
    since: date | None = None,
    clock: ManualClock | None = None,
    deadline: float = _FAR,
) -> FetchOutcome:
    """
    Run the loop with the defaults most tests share.

    Args:
        mailbox (FakeMailbox): The mailbox.
        store (Store): The store.
        limit (int, optional): The limit of new messages. Default: ``500``.
        since (date | None, optional): The lower bound of the search. Default: ``None``.
        clock (ManualClock | None, optional): The clock. Default: a new one at zero.
        deadline (float, optional): When the run must stop. Default: far away.

    Returns:
        FetchOutcome: What the run did.
    """
    return fetch_reports(
        mailbox,
        "INBOX",
        since,
        store,
        limit,
        clock if clock is not None else ManualClock(),
        deadline,
    )


def _adds_up(outcome: FetchOutcome) -> None:
    """
    Assert the invariant of the six numbers.

    Args:
        outcome (FetchOutcome): The outcome to check.
    """
    assert outcome.matched == (
        outcome.saved + outcome.already + outcome.too_large + outcome.skipped + outcome.left
    )


def _names(store: Store) -> list[str]:
    """
    List the saved messages of a store.

    Args:
        store (Store): The store.

    Returns:
        list[str]: The sorted names of the ``.eml`` files; empty when the directory is missing.
    """
    directory = store.directory
    return sorted(p.name for p in directory.glob("*.eml")) if directory.exists() else []


def _requested(mailbox: FakeMailbox) -> list[int]:
    """
    List the UIDs ``message`` was asked for, in order.

    Args:
        mailbox (FakeMailbox): The mailbox.

    Returns:
        list[int]: The UIDs.
    """
    return [int(str(call[1])) for call in mailbox.called("message")]


# ---------------------------------------------------------------------------
# The ordinary run
# ---------------------------------------------------------------------------


def test_saves_every_new_message_under_its_tagged_name(tmp_path: Path) -> None:
    mailbox, store = _mailbox(3, 5, 8, validity=7), _store(tmp_path)

    outcome = _run(mailbox, store)

    assert outcome == FetchOutcome(matched=3, saved=3, already=0, too_large=0, skipped=0, left=0)
    assert _names(store) == ["0badc0de-7-3.eml", "0badc0de-7-5.eml", "0badc0de-7-8.eml"]
    for uid, body in mailbox.bodies.items():
        assert (store.directory / store.name(7, uid)).read_bytes() == body


def test_selects_the_folder_and_searches_with_the_date(tmp_path: Path) -> None:
    mailbox = _mailbox(1)

    _run(mailbox, _store(tmp_path), since=date(2026, 10, 1))

    assert mailbox.called("select") == [("select", "INBOX")]
    assert mailbox.called("search") == [("search", date(2026, 10, 1))]


def test_an_empty_mailbox_is_all_zeros_and_asks_for_no_size(tmp_path: Path) -> None:
    mailbox = FakeMailbox()

    outcome = _run(mailbox, _store(tmp_path))

    assert outcome == FetchOutcome(0, 0, 0, 0, 0, 0)
    assert mailbox.called("sizes") == []


def test_messages_are_requested_newest_first(tmp_path: Path) -> None:
    mailbox = _mailbox(2, 9, 4, 7)

    _run(mailbox, _store(tmp_path))

    assert _requested(mailbox) == [9, 7, 4, 2]


def test_a_search_in_the_wrong_order_is_still_processed_newest_first(tmp_path: Path) -> None:
    mailbox = _mailbox(1, 2, 3)
    mailbox.listed = [2, 3, 1]

    _run(mailbox, _store(tmp_path))

    assert _requested(mailbox) == [3, 2, 1]


def test_message_is_asked_for_exactly_the_cap(tmp_path: Path) -> None:
    mailbox = _mailbox(1, 2)

    _run(mailbox, _store(tmp_path))

    assert [call[2] for call in mailbox.called("message")] == [MAX_MESSAGE_BYTES] * 2


def test_sizes_are_asked_once_for_the_messages_to_download_only(tmp_path: Path) -> None:
    mailbox, store = _mailbox(1, 2, 3, 4, 5), _store(tmp_path)
    store.save(1, 5, b"saved before")

    _run(mailbox, store, limit=2)

    assert mailbox.called("sizes") == [("sizes", (4, 3))]


# ---------------------------------------------------------------------------
# Reruns, the limit and the validity number
# ---------------------------------------------------------------------------


def test_a_rerun_saves_nothing_and_leaves_every_file_untouched(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _run(_mailbox(1, 2, 3), store)
    before = {name: (store.directory / name).read_bytes() for name in _names(store)}
    again = _mailbox(1, 2, 3)

    outcome = _run(again, store)

    assert outcome == FetchOutcome(matched=3, saved=0, already=3, too_large=0, skipped=0, left=0)
    assert again.called("sizes") == []
    assert again.called("message") == []
    assert {name: (store.directory / name).read_bytes() for name in _names(store)} == before


def test_the_limit_counts_new_messages_only(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save(1, 10, b"saved before")
    store.save(1, 9, b"saved before")
    mailbox = _mailbox(*range(1, 11))

    outcome = _run(mailbox, store, limit=3)

    assert _requested(mailbox) == [8, 7, 6]
    assert outcome == FetchOutcome(matched=10, saved=3, already=2, too_large=0, skipped=0, left=5)
    _adds_up(outcome)


def test_the_next_run_continues_backwards(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _run(_mailbox(*range(1, 7)), store, limit=2)
    second = _mailbox(*range(1, 7))

    outcome = _run(second, store, limit=2)

    assert _requested(second) == [4, 3]
    assert outcome == FetchOutcome(matched=6, saved=2, already=2, too_large=0, skipped=0, left=2)


def test_a_limit_above_the_new_messages_leaves_nothing(tmp_path: Path) -> None:
    outcome = _run(_mailbox(1, 2), _store(tmp_path), limit=500)

    assert outcome.left == 0
    assert outcome.saved == 2


def test_a_changed_validity_number_downloads_again_and_keeps_the_old_files(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    old = _mailbox(1, 2, validity=1)
    _run(old, store)

    outcome = _run(_mailbox(1, 2, validity=2), store)

    assert outcome == FetchOutcome(matched=2, saved=2, already=0, too_large=0, skipped=0, left=0)
    assert _names(store) == [
        "0badc0de-1-1.eml",
        "0badc0de-1-2.eml",
        "0badc0de-2-1.eml",
        "0badc0de-2-2.eml",
    ]


# ---------------------------------------------------------------------------
# What is not saved
# ---------------------------------------------------------------------------


def test_a_size_over_the_cap_is_too_large_and_never_requested(tmp_path: Path) -> None:
    mailbox = _mailbox(1, 2)
    mailbox.announced[2] = MAX_MESSAGE_BYTES + 1

    outcome = _run(mailbox, _store(tmp_path))

    assert outcome == FetchOutcome(matched=2, saved=1, already=0, too_large=1, skipped=0, left=0)
    assert _requested(mailbox) == [1]


def test_a_size_exactly_at_the_cap_is_requested(tmp_path: Path) -> None:
    mailbox = _mailbox(1)
    mailbox.announced[1] = MAX_MESSAGE_BYTES

    outcome = _run(mailbox, _store(tmp_path))

    assert outcome.saved == 1
    assert _requested(mailbox) == [1]


def test_a_message_announced_small_that_arrives_over_the_cap_is_too_large_and_not_saved(
    tmp_path: Path,
) -> None:
    mailbox, store = _mailbox(1, 2), _store(tmp_path)
    mailbox.bodies[2] = b"x" * (MAX_MESSAGE_BYTES + 1)
    mailbox.announced[2] = 100

    outcome = _run(mailbox, store)

    assert outcome == FetchOutcome(matched=2, saved=1, already=0, too_large=1, skipped=0, left=0)
    assert _names(store) == ["0badc0de-1-1.eml"]


def test_a_message_of_exactly_the_cap_is_saved(tmp_path: Path) -> None:
    mailbox, store = FakeMailbox(bodies={1: b"x" * MAX_MESSAGE_BYTES}), _store(tmp_path)

    outcome = _run(mailbox, store)

    assert outcome.saved == 1
    assert (store.directory / store.name(1, 1)).stat().st_size == MAX_MESSAGE_BYTES


def test_a_uid_with_no_size_is_skipped_and_never_requested(tmp_path: Path) -> None:
    mailbox = _mailbox(1, 2)
    mailbox.unsized.add(2)

    outcome = _run(mailbox, _store(tmp_path))

    assert outcome == FetchOutcome(matched=2, saved=1, already=0, too_large=0, skipped=1, left=0)
    assert _requested(mailbox) == [1]


def test_a_body_of_none_is_skipped(tmp_path: Path) -> None:
    mailbox, store = _mailbox(1, 2), _store(tmp_path)
    mailbox.bodies[2] = None

    outcome = _run(mailbox, store)

    assert outcome == FetchOutcome(matched=2, saved=1, already=0, too_large=0, skipped=1, left=0)
    assert _names(store) == ["0badc0de-1-1.eml"]


def test_the_tokens_the_search_dropped_are_matched_and_skipped(tmp_path: Path) -> None:
    mailbox = _mailbox(1, 2)
    mailbox.dropped = 3

    outcome = _run(mailbox, _store(tmp_path))

    assert outcome == FetchOutcome(matched=5, saved=2, already=0, too_large=0, skipped=3, left=0)


def test_a_repeated_uid_is_matched_once_saved_once_and_the_copy_is_skipped(
    tmp_path: Path,
) -> None:
    mailbox = _mailbox(1, 2)
    mailbox.listed = [1, 2, 2]

    outcome = _run(mailbox, _store(tmp_path))

    assert outcome == FetchOutcome(matched=3, saved=2, already=0, too_large=0, skipped=1, left=0)
    assert _requested(mailbox) == [2, 1]


def test_every_kind_of_message_at_once_still_adds_up(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save(1, 9, b"saved before")
    mailbox = _mailbox(*range(1, 10))
    mailbox.announced[8] = MAX_MESSAGE_BYTES + 1
    mailbox.unsized.add(7)
    mailbox.bodies[6] = None
    mailbox.dropped = 2

    outcome = _run(mailbox, store, limit=3)

    # 9 is on disk; 8 too large, 7 unsized and 6 without a body use up the limit of 3; 2 dropped.
    assert outcome == FetchOutcome(matched=11, saved=0, already=1, too_large=1, skipped=4, left=5)
    _adds_up(outcome)


# ---------------------------------------------------------------------------
# The deadline
# ---------------------------------------------------------------------------


def test_a_clock_past_the_deadline_moves_what_is_not_tried_to_left(tmp_path: Path) -> None:
    clock = ManualClock()
    mailbox, store = _mailbox(1, 2, 3, 4, 5), _store(tmp_path)
    mailbox.on_message = lambda uid: clock.advance(60.0)

    outcome = _run(mailbox, store, clock=clock, deadline=100.0)

    # 5 arrives at 60, 4 at 120 (the deadline is checked before each message, so 4 still went),
    # then the clock is past 100 and 3, 2 and 1 are left.
    assert _requested(mailbox) == [5, 4]
    assert outcome == FetchOutcome(matched=5, saved=2, already=0, too_large=0, skipped=0, left=3)
    _adds_up(outcome)


def test_a_clock_already_past_the_deadline_tries_nothing(tmp_path: Path) -> None:
    mailbox = _mailbox(1, 2)

    outcome = _run(mailbox, _store(tmp_path), clock=ManualClock(500.0), deadline=100.0)

    assert mailbox.called("message") == []
    assert outcome == FetchOutcome(matched=2, saved=0, already=0, too_large=0, skipped=0, left=2)


def test_a_clock_exactly_at_the_deadline_still_goes_on(tmp_path: Path) -> None:
    outcome = _run(_mailbox(1), _store(tmp_path), clock=ManualClock(100.0), deadline=100.0)

    assert outcome.saved == 1


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_a_write_failure_raises_with_the_outcome_so_far(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mailbox, store = _mailbox(1, 2, 3, 4), _store(tmp_path)
    real_save = store.save

    def failing_save(validity: int, uid: int, data: bytes) -> None:
        if uid == 2:
            raise FetchRefused(FetchReason.WRITE_FAILED, "No space left on device")
        real_save(validity, uid, data)

    monkeypatch.setattr(store, "save", failing_save)

    with pytest.raises(FetchRefused) as caught:
        _run(mailbox, store)

    assert caught.value.reason is FetchReason.WRITE_FAILED
    assert caught.value.detail == "No space left on device"
    # 4 and 3 were saved; the message that failed and the one after it were not.
    assert caught.value.outcome == FetchOutcome(
        matched=4, saved=2, already=0, too_large=0, skipped=0, left=2
    )
    assert _requested(mailbox) == [4, 3, 2]


def test_a_refusal_from_the_mailbox_during_the_downloads_carries_the_outcome(
    tmp_path: Path,
) -> None:
    mailbox, store = _mailbox(1, 2, 3), _store(tmp_path)
    mailbox.message_failures[2] = FetchRefused(FetchReason.TIMEOUT)

    with pytest.raises(FetchRefused) as caught:
        _run(mailbox, store)

    assert caught.value.reason is FetchReason.TIMEOUT
    assert caught.value.outcome == FetchOutcome(
        matched=3, saved=1, already=0, too_large=0, skipped=0, left=2
    )
    assert _names(store) == ["0badc0de-1-3.eml"]


def test_a_refusal_of_the_size_query_carries_an_outcome_with_nothing_saved(
    tmp_path: Path,
) -> None:
    mailbox = _mailbox(1, 2)
    mailbox.failures["sizes"] = FetchRefused(FetchReason.PROTOCOL_ERROR, "bad answer")

    with pytest.raises(FetchRefused) as caught:
        _run(mailbox, _store(tmp_path))

    assert caught.value.outcome == FetchOutcome(
        matched=2, saved=0, already=0, too_large=0, skipped=0, left=2
    )


@pytest.mark.parametrize("method", ["select", "search"])
def test_a_refusal_before_any_work_carries_no_outcome(tmp_path: Path, method: str) -> None:
    mailbox = _mailbox(1)
    mailbox.failures[method] = FetchRefused(FetchReason.FOLDER_NOT_FOUND)

    with pytest.raises(FetchRefused) as caught:
        _run(mailbox, _store(tmp_path))

    assert caught.value.reason is FetchReason.FOLDER_NOT_FOUND
    assert caught.value.outcome is None
    assert mailbox.called("message") == []


def test_a_refusal_that_already_has_an_outcome_keeps_it(tmp_path: Path) -> None:
    own = FetchOutcome(1, 1, 0, 0, 0, 0)
    mailbox = _mailbox(1)
    mailbox.failures["message"] = FetchRefused(FetchReason.TIMEOUT, outcome=own)

    with pytest.raises(FetchRefused) as caught:
        _run(mailbox, _store(tmp_path))

    assert caught.value.outcome == own


def test_the_loop_does_not_close_the_mailbox(tmp_path: Path) -> None:
    mailbox = _mailbox(1)

    _run(mailbox, _store(tmp_path))

    assert mailbox.closed == 0


# ---------------------------------------------------------------------------
# The stale files
# ---------------------------------------------------------------------------


def test_a_stale_temporary_file_is_removed_at_the_start(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.directory.mkdir()
    stale = store.directory / ".mailvigil-abc123.partial"
    stale.write_bytes(b"half")
    old = time.time() - 3 * 24 * 60 * 60
    os.utime(stale, (old, old))

    _run(_mailbox(1), store)

    assert not stale.exists()


def test_the_clean_up_runs_even_when_the_folder_is_refused(
    tmp_path: Path,
) -> None:
    # The clean-up is step 1 of the design, before the folder is opened.
    store = _store(tmp_path)
    store.directory.mkdir()
    stale = store.directory / ".mailvigil-abc123.partial"
    stale.write_bytes(b"half")
    old = time.time() - 3 * 24 * 60 * 60
    os.utime(stale, (old, old))
    mailbox = _mailbox(1)
    mailbox.failures["select"] = FetchRefused(FetchReason.FOLDER_NOT_FOUND)

    with pytest.raises(FetchRefused):
        _run(mailbox, store)

    assert not stale.exists()


# ---------------------------------------------------------------------------
# No hidden inputs
# ---------------------------------------------------------------------------


def test_the_module_reads_no_time_environment_or_arguments() -> None:
    # The clock and the deadline are arguments, so a test moves time by hand (RNF-04).
    tree = ast.parse(Path(run_module.__file__).read_text(encoding="utf-8"))
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert not imported & {"time", "os", "sys", "argparse", "getpass"}
    names = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert not names & {"environ", "argv", "getenv", "now", "today", "time", "monotonic"}
