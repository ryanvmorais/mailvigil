"""
Tests that the accented Portuguese text is the folded text with its accents put back (spec 006
ADR-9, RF-06).

Isolation: nothing touches the disk and no command runs. Every text is rendered twice from the same
input, with ``PORTUGUESE`` and with ``PORTUGUESE_ASCII``; the accented lines, folded, must equal the
others line by line. That one check carries the layout rule: a table that aligns in ASCII aligns
with accents, every line stays within 80 columns, and the figures are the same. The inputs are the
stress inputs of the English tests (a 100-character name, IPv6 addresses, counts of ``10**12``).
"""

from __future__ import annotations

import html
from collections.abc import Callable

import pytest
from tests.test_render import extreme_summary, failing_source, make_summary
from tests.test_render_fetch import _DIRECTORY, _OUTCOME
from tests.test_render_verdict import make_verdict, verdicts_of

from mailvigil.fetch.errors import FetchReason, FetchRefused
from mailvigil.messages import PORTUGUESE, PORTUGUESE_ASCII, Messages
from mailvigil.messages.fold import fold_text
from mailvigil.render import no_reports_message, render_summary
from mailvigil.render_fetch import refusal_line, render_fetch
from mailvigil.render_html import render_html
from mailvigil.render_verdict import render_tally, render_verdict
from mailvigil.reports import IngestionResult
from mailvigil.verdict import judge

# The line limit of the text layout (spec 004 RF-09): accents must not push a line past it.
_WIDTH = 80


def same_lines(render: Callable[[Messages], str], *, columns: bool = True) -> None:
    """
    Render with both catalogs and compare line by line, folded.

    Args:
        render (Callable[[Messages], str]): The text of one input in a language.
        columns (bool, optional): Whether the text is laid out in 80 columns. A refusal line is one
            sentence on standard error and has no such limit. Default: ``True``.
    """
    accented = render(PORTUGUESE).split("\n")
    folded = render(PORTUGUESE_ASCII).split("\n")
    assert [fold_text(line) for line in accented] == folded
    if columns:
        assert all(len(line) <= _WIDTH for line in accented)
    assert [len(line) for line in accented] == [len(line) for line in folded]


# ---------------------------------------------------------------------------
# The text of the two commands
# ---------------------------------------------------------------------------

_SUMMARIES = {
    "plain": make_summary(),
    "failing": make_summary(failing=(failing_source(), failing_source(ip="192.0.2.20"))),
    "extreme": extreme_summary(),
}

_VERDICTS = {
    "ready": make_verdict(),
    "too-early": make_verdict(days=3),
    "not-ready": make_verdict(sources=(failing_source(messages=900),)),
}


@pytest.mark.parametrize("name", _SUMMARIES)
def test_a_summary_keeps_its_layout_with_accents(name: str) -> None:
    same_lines(lambda messages: render_summary(_SUMMARIES[name], "mailvigil.toml", messages))


@pytest.mark.parametrize("name", _VERDICTS)
def test_a_verdict_keeps_its_layout_with_accents(name: str) -> None:
    same_lines(lambda messages: render_verdict(_VERDICTS[name], messages))


def test_the_tally_and_the_no_reports_message_keep_their_layout_with_accents() -> None:
    same_lines(lambda messages: render_tally(verdicts_of(2, 1, 1), messages))
    same_lines(lambda messages: no_reports_message(IngestionResult(), ["example.com"], messages))


def test_the_accented_verdict_reads_as_portuguese() -> None:
    text = render_verdict(_VERDICTS["too-early"], PORTUGUESE)
    assert "CEDO DEMAIS para dizer" in text
    assert "período coberto" in text
    assert "necessário" in text


# ---------------------------------------------------------------------------
# fetch
# ---------------------------------------------------------------------------


def test_the_fetch_text_keeps_its_layout_with_accents() -> None:
    same_lines(lambda messages: render_fetch(_OUTCOME, _DIRECTORY, messages))
    for reason in FetchReason:
        same_lines(
            lambda messages, reason=reason: refusal_line(FetchRefused(reason), messages),
            columns=False,
        )


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------


def page(messages: Messages) -> str:
    """Render the page of a verdict in a language."""
    summary = make_summary()
    return render_html(summary, judge(summary), messages)


def test_the_page_has_the_accents_as_character_references_and_stays_ascii() -> None:
    document = page(PORTUGUESE)
    assert document.isascii()
    assert PORTUGUESE.html.group_data in html.unescape(document)
    assert "&#" in document
    assert 'lang="pt-BR"' in document


def test_the_folded_page_and_the_accented_page_say_the_same_in_ascii_letters() -> None:
    assert fold_text(html.unescape(page(PORTUGUESE))) == html.unescape(page(PORTUGUESE_ASCII))
