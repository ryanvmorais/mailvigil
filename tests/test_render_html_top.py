"""
Tests of the cap on the senders table of the HTML page and of ``top`` (spec 008, ADR-12, issue #71).

Isolation: nothing touches the disk and no command runs. The summary is the invented ``ready`` run
of ``html_helpers`` with many senders added; every address is in ``198.51.100.0/24`` or
``203.0.113.0/24`` (RNF-06).
"""

from __future__ import annotations

import dataclasses

import pytest
from tests.html_helpers import Page, judged, ready_summary

from mailvigil.messages import ENGLISH, PORTUGUESE, Messages
from mailvigil.render_html import _SENDERS_LIMIT, render_html
from mailvigil.senders import Outcome
from mailvigil.summary import Counts, SenderRow, Summary

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def many_senders(count: int) -> Summary:
    """
    Build the ready summary with ``count`` unrecognized senders of 2 messages each.

    Args:
        count (int): How many senders.

    Returns:
        Summary: The summary; its total row is the one of the ready run, not the sum of the rows.
    """
    rows = tuple(
        SenderRow(
            Outcome.UNKNOWN,
            source_ip=f"198.51.{number // 250}.{number % 250 + 1}",
            counts=Counts(ok=2),
        )
        for number in range(count)
    )
    return dataclasses.replace(ready_summary(), senders=rows)


def sender_rows(page: Page) -> int:
    """
    Count the senders the table lists, by their invented addresses.

    Args:
        page (Page): The parsed page.

    Returns:
        int: How many cells hold such an address.
    """
    return sum(1 for text in page.texts if text.startswith("198.51."))


# ---------------------------------------------------------------------------
# The default cap
# ---------------------------------------------------------------------------


def test_the_cap_is_fifty_rows() -> None:
    assert _SENDERS_LIMIT == 50


def test_a_table_within_the_cap_lists_every_sender_and_says_nothing_more() -> None:
    summary, verdict = judged(many_senders(_SENDERS_LIMIT))

    page = Page(render_html(summary, verdict))

    assert sender_rows(page) == _SENDERS_LIMIT
    assert "Not listed here" not in page.text


def test_a_table_past_the_cap_shows_fifty_rows_and_counts_the_rest() -> None:
    summary, verdict = judged(many_senders(_SENDERS_LIMIT + 7))

    page = Page(render_html(summary, verdict))

    assert sender_rows(page) == _SENDERS_LIMIT
    assert "198.51.0.1" in page.text
    assert "Not listed here: 7 other senders (14 messages)." in page.text
    assert "mailvigil summary --json lists every sender." in page.text


def test_one_sender_left_out_is_said_in_the_singular() -> None:
    summary, verdict = judged(many_senders(_SENDERS_LIMIT + 1))

    page = Page(render_html(summary, verdict))

    assert "Not listed here: 1 other sender (2 messages)." in page.text


def test_the_total_row_still_counts_every_message() -> None:
    summary, verdict = judged(many_senders(_SENDERS_LIMIT + 7))

    page = Page(render_html(summary, verdict))

    assert str(summary.totals.total) in page.texts


# ---------------------------------------------------------------------------
# --top moves the cap
# ---------------------------------------------------------------------------


def test_top_moves_the_cap_down() -> None:
    summary, verdict = judged(many_senders(10))

    page = Page(render_html(summary, verdict, ENGLISH, 4))

    assert sender_rows(page) == 4
    assert "Not listed here: 6 other senders (12 messages)." in page.text


def test_top_moves_the_cap_up_past_fifty() -> None:
    summary, verdict = judged(many_senders(_SENDERS_LIMIT + 7))

    page = Page(render_html(summary, verdict, ENGLISH, 80))

    assert sender_rows(page) == _SENDERS_LIMIT + 7
    assert "Not listed here" not in page.text


def test_a_page_of_many_thousand_senders_stays_small() -> None:
    summary, verdict = judged(many_senders(20_000))

    document = render_html(summary, verdict)

    assert len(document) < 200_000


@pytest.mark.parametrize("messages", [ENGLISH, PORTUGUESE], ids=["en", "pt-BR"])
def test_the_line_is_in_both_languages_and_ascii(messages: Messages) -> None:
    summary, verdict = judged(many_senders(_SENDERS_LIMIT + 3))

    document = render_html(summary, verdict, messages)

    assert document.isascii()
    other = messages.html.other_sender.of(3)
    assert (
        messages.html.senders_more.format(senders=other, messages=messages.common.message.of(6))
        in Page(document).text
    )
