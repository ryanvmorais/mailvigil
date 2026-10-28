"""
The loop of ``fetch``: which messages to download, in which order, and what to do with each.

``fetch_reports`` drives a ``Mailbox`` and a ``Store`` and knows nothing about IMAP, so it runs
against a fake in the tests. It reads no clock and no environment: the clock and the deadline are
arguments, so a test moves time by hand. It does not close the mailbox; whoever opened it does, in a
``finally`` (spec 009, ADR-1, ADR-8).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from mailvigil.fetch.errors import FetchRefused
from mailvigil.fetch.model import MAX_MESSAGE_BYTES, FetchOutcome, Mailbox
from mailvigil.fetch.store import Store

__all__ = ["fetch_reports"]


def fetch_reports(
    mailbox: Mailbox,
    folder: str,
    since: date | None,
    store: Store,
    limit: int,
    clock: Callable[[], float],
    deadline: float,
) -> FetchOutcome:
    """
    Download the report messages of a folder that the store does not hold yet.

    The newest messages come first, because UIDs grow with arrival and a verdict about today's mail
    needs the recent ones; the limit counts only messages not yet on disk, so a rerun with the same
    limit goes on backwards instead of doing nothing.

    Args:
        mailbox (Mailbox): The mailbox to read; this function never closes it.
        folder (str): The folder to read, as the user typed it.
        since (date | None): Only messages received on or after this day; ``None`` for all.
        store (Store): Where the messages are kept.
        limit (int): The most new messages to download in this run.
        clock (Callable[[], float]): Reads the time, in the same unit as ``deadline``.
        deadline (float): The reading of ``clock`` past which no new download starts.

    Returns:
        FetchOutcome: What the run did, in numbers that add up to ``matched``.

    Raises:
        FetchRefused: When the mailbox or the disk refuses. The refusals that come after the search
            carry the outcome so far, with the messages not tried counted in ``left``.
    """
    # 1. A crash leaves temporary files; clear them before anything is written.
    store.clean_stale()
    validity = mailbox.select(folder)
    # 2. What the server lists, newest first.
    found = mailbox.search(since)

    # A server that repeats a UID would otherwise be saved twice under one name.
    newest_first = sorted(set(found.uids), reverse=True)
    matched = len(found.uids) + found.dropped
    skipped = found.dropped + len(found.uids) - len(newest_first)

    # 3. Drop what is on disk, then split the rest at the limit.
    new = [uid for uid in newest_first if not store.has(validity, uid)]
    already = len(newest_first) - len(new)
    todo = new[:limit]
    left = len(new) - len(todo)

    saved = too_large = 0
    queue: list[int] = []
    # What the run has not tried yet, so a refusal can say how many messages are still to fetch.
    untried = len(todo)
    try:
        # 4. Sizes: an unanswered UID is skipped, an oversized one is never requested.
        announced = mailbox.sizes(todo) if todo else {}
        for uid in todo:
            size = announced.get(uid)
            if size is None:
                skipped += 1
            elif size > MAX_MESSAGE_BYTES:
                too_large += 1
            else:
                queue.append(uid)

        # 5. One message at a time, stopping at the deadline.
        for position, uid in enumerate(queue):
            untried = len(queue) - position
            if clock() > deadline:
                left += untried
                break
            # The adapter hands back at most one byte over the cap, which is enough to tell.
            data = mailbox.message(uid, MAX_MESSAGE_BYTES)
            if data is None:
                skipped += 1
            elif len(data) > MAX_MESSAGE_BYTES:
                too_large += 1
            else:
                store.save(validity, uid, data)
                saved += 1
    except FetchRefused as exc:
        if exc.outcome is None:
            exc.outcome = FetchOutcome(
                matched=matched,
                saved=saved,
                already=already,
                too_large=too_large,
                skipped=skipped,
                left=left + untried,
            )
        raise

    return FetchOutcome(
        matched=matched,
        saved=saved,
        already=already,
        too_large=too_large,
        skipped=skipped,
        left=left,
    )
