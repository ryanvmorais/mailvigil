"""
Tests of ``render_html``: the page that prints a ``Summary`` and a ``Verdict`` (spec 008, RF-02,
RF-05, RF-07, RF-08, RNF-03, RNF-04).

Isolation: a pure function over invented values, no disk and no command (``tests/html_helpers.py``
builds three runs, one for each answer). The page is judged through the standard library's parser,
never by comparing a whole string; the facts are compared with what the text format says for the
same run, since the two must agree (RF-02). The attack strings are in ``test_render_html_hostile``.
"""

from __future__ import annotations

import itertools
import re
from datetime import timedelta
from pathlib import Path

import pytest
from tests.html_helpers import (
    Page,
    early_summary,
    judged,
    make_days,
    make_period,
    not_ready_summary,
    ready_summary,
)

from mailvigil import __version__
from mailvigil.html_style import CONTENT_SECURITY_POLICY
from mailvigil.messages import ENGLISH, PORTUGUESE, Messages
from mailvigil.render import render_summary
from mailvigil.render_html import render_html
from mailvigil.render_verdict import (
    answer_phrase,
    measured_text,
    next_sentence,
    note_sentence,
    reason_sentence,
    render_verdict,
)
from mailvigil.senders import Outcome
from mailvigil.summary import Counts, FailingSource, SenderRow, Summary
from mailvigil.verdict import Answer, Verdict, judge

# The README shows this file, so the page must draw the same path (one symbol for the tool).
_SYMBOL_FILE = (
    Path(__file__).resolve().parent.parent / "docs" / "images" / "mailvigil-dmarc-analyzer-logo.svg"
)

_RUNS = {
    Answer.READY: ready_summary,
    Answer.TOO_EARLY: early_summary,
    Answer.NOT_READY: not_ready_summary,
}


def page_of(answer: Answer, messages: Messages = ENGLISH) -> tuple[str, Page, Summary, Verdict]:
    """
    Render the invented run of an answer and parse it.

    Args:
        answer (Answer): Which run.
        messages (Messages): The language. Default: English.

    Returns:
        tuple[str, Page, Summary, Verdict]: The document, its parsed form, and the values it was
            made from.
    """
    summary, verdict = judged(_RUNS[answer]())
    assert verdict.answer is answer
    document = render_html(summary, verdict, messages)
    return document, Page(document), summary, verdict


answers = pytest.mark.parametrize("answer", list(Answer))
languages = pytest.mark.parametrize("messages", [ENGLISH, PORTUGUESE], ids=["en", "pt-BR"])

# ---------------------------------------------------------------------------
# Structure (RF-02, RF-07)
# ---------------------------------------------------------------------------


@answers
def test_the_page_is_one_ascii_document_that_ends_in_a_newline(answer: Answer) -> None:
    document, _page, _summary, _verdict = page_of(answer)
    assert document.startswith("<!doctype html>")
    assert document.isascii()
    assert document.endswith("</html>\n")


@answers
def test_the_page_carries_the_policy_that_forbids_loading_anything(answer: Answer) -> None:
    _document, page, _summary, _verdict = page_of(answer)
    policies = [
        attrs["content"]
        for tag, attrs in page.elements
        if tag == "meta" and attrs.get("http-equiv") == "Content-Security-Policy"
    ]
    assert policies == [CONTENT_SECURITY_POLICY]


@answers
@languages
def test_the_page_declares_its_language_and_has_a_title(answer: Answer, messages: Messages) -> None:
    _document, page, _summary, _verdict = page_of(answer, messages)
    html = next(attrs for tag, attrs in page.elements if tag == "html")
    assert html["lang"] == messages.html.lang
    assert page.count("title") == 1


@answers
def test_the_only_h1_is_the_answer(answer: Answer) -> None:
    _document, page, _summary, verdict = page_of(answer)
    phrase = answer_phrase(verdict, ENGLISH)
    assert [text for level, text in page.headings if level == 1] == [
        phrase[:1].upper() + phrase[1:]
    ]


@answers
def test_the_headings_never_skip_a_level(answer: Answer) -> None:
    _document, page, _summary, _verdict = page_of(answer)
    levels = [level for level, _text in page.headings]
    assert levels[0] == 1
    assert all(after <= before + 1 for before, after in itertools.pairwise(levels))


@answers
def test_the_sections_come_in_the_order_of_the_design(answer: Answer) -> None:
    _document, page, summary, _verdict = page_of(answer)
    html, text = ENGLISH.html, ENGLISH.summary
    expected = [
        html.rules_title,
        html.mix_title.of(summary.totals.total),
        html.days_title,
        text.senders_title,
        html.failing_heading,
    ]
    sections = [title for level, title in page.headings if level == 2]
    assert sections[: len(expected)] == expected


@answers
def test_every_table_header_says_what_it_heads(answer: Answer) -> None:
    _document, page, _summary, _verdict = page_of(answer)
    headers = [attrs for tag, attrs in page.elements if tag == "th"]
    assert headers
    assert all(attrs.get("scope") in {"col", "row"} for attrs in headers)


@answers
def test_every_svg_is_named_or_marked_decorative(answer: Answer) -> None:
    _document, page, _summary, _verdict = page_of(answer)
    drawings = [attrs for tag, attrs in page.elements if tag == "svg"]
    assert drawings
    for attrs in drawings:
        decorative = attrs.get("aria-hidden") == "true"
        named = attrs.get("role") == "img" and bool(attrs.get("aria-label"))
        assert decorative or named


@answers
def test_the_symbol_in_the_header_is_the_one_of_the_svg_file(answer: Answer) -> None:
    # The file is what the README shows; the page draws the same path, so the tool has one symbol.
    _document, page, _summary, _verdict = page_of(answer)
    marks = [attrs for tag, attrs in page.elements if tag == "path" and "fill-rule" in attrs]
    assert len(marks) == 1
    assert marks[0]["fill-rule"] == "evenodd"
    found = re.search(r' d="([^"]+)"', _SYMBOL_FILE.read_text(encoding="utf-8"))
    assert found is not None
    assert marks[0]["d"] == found.group(1)


@answers
def test_the_scrolling_boxes_can_be_reached_from_the_keyboard(answer: Answer) -> None:
    _document, page, _summary, _verdict = page_of(answer)
    boxes = page.with_class("scroll")
    assert boxes
    assert all(box.get("tabindex") == "0" and box.get("aria-label") for box in boxes)


def test_the_five_rules_are_in_two_groups() -> None:
    _document, page, _summary, _verdict = page_of(Answer.NOT_READY)
    groups = [text for level, text in page.headings if level == 3]
    assert groups[:2] == [ENGLISH.html.group_data, ENGLISH.html.group_problem]
    assert len(page.with_class("meter")) == 5


def test_the_footer_names_the_version() -> None:
    _document, page, _summary, _verdict = page_of(Answer.READY)
    assert ENGLISH.html.footer.format(version=__version__) in page.texts


# ---------------------------------------------------------------------------
# What each answer shows (RF-02, RF-05)
# ---------------------------------------------------------------------------


def test_a_ready_page_has_no_deciding_rule_and_no_failing_sources() -> None:
    _document, page, _summary, verdict = page_of(Answer.READY)
    assert verdict.deciding is None
    assert page.with_class("next") == []
    assert page.with_class("meter") and not page.with_class("fail")
    assert page.with_class("fails") == []
    assert ENGLISH.summary.no_failures in page.texts


def test_a_ready_page_with_a_source_still_failing_says_so() -> None:
    summary = ready_summary()
    ok = Counts(ok=1200, dkim_only=13, failing=5)
    summary = Summary(
        **{
            **vars_of(summary),
            "totals": ok,
            "senders": (SenderRow(Outcome.UNKNOWN, source_ip="198.51.100.9", counts=ok),),
            "failing": (FailingSource(Outcome.UNKNOWN, "198.51.100.9", 5),),
        }
    )
    verdict = judge(summary)
    assert verdict.answer is Answer.READY
    page = Page(render_html(summary, verdict))
    assert ENGLISH.verdict.still_failing in page.texts
    assert "198.51.100.9" in page.text


def vars_of(summary: Summary) -> dict[str, object]:
    """
    Read the fields of a summary, to build a changed copy of it.

    Args:
        summary (Summary): The summary.

    Returns:
        dict[str, object]: Field name to value.
    """
    return {name: getattr(summary, name) for name in summary.__dataclass_fields__}


def test_a_too_early_page_says_what_is_missing() -> None:
    _document, page, _summary, verdict = page_of(Answer.TOO_EARLY)
    missing = [rule for rule in verdict.rules if not rule.passed]
    assert missing
    assert page.with_class("next")
    assert len(page.with_class("fail")) == len(missing)
    assert ENGLISH.verdict.need_days.of(missing[0].missing) in page.text


def test_a_not_ready_page_lists_the_failing_sources_recognized_first() -> None:
    _document, page, _summary, _verdict = page_of(Answer.NOT_READY)
    groups = [text for level, text in page.headings if level == 3]
    assert groups[-2:] == [ENGLISH.summary.failing_recognized, ENGLISH.summary.failing_unrecognized]
    assert len(page.with_class("fails")) == 2
    assert page.text.index("192.0.2.10") < page.text.index(
        "203.0.113.7", page.text.index("192.0.2")
    )


def test_a_failing_source_names_its_address_its_messages_and_what_failed() -> None:
    _document, page, _summary, _verdict = page_of(Answer.NOT_READY)
    detail = ENGLISH.summary.source_detail.format(
        messages=ENGLISH.common.message.of(10), dkim="fail", spf="softfail"
    )
    assert any("192.0.2.10" in text and detail in text for text in page.texts)
    assert "forwarded" in page.text


def test_the_policy_box_shows_the_subdomain_policies_only_when_present() -> None:
    _document, ready, _summary, _verdict = page_of(Answer.READY)
    _document, bad, _summary, _verdict = page_of(Answer.NOT_READY)
    assert ready.terms == ["p", "pct"]
    assert bad.terms == ["p", "sp", "np", "pct"]


def test_no_policy_box_when_the_reports_gave_no_policy() -> None:
    summary = ready_summary()
    summary = Summary(**{**vars_of(summary), "policy": None})
    page = Page(render_html(summary, judge(summary)))
    assert page.with_class("policy") == []


def test_every_note_of_the_verdict_is_on_the_page() -> None:
    _document, page, _summary, verdict = page_of(Answer.NOT_READY)
    assert len(verdict.notes) >= 3
    for note in verdict.notes:
        assert note_sentence(note, ENGLISH) in page.texts
    assert ENGLISH.verdict.notes_title in [text for _level, text in page.headings]


def test_there_is_no_notes_block_without_notes() -> None:
    summary = ready_summary()
    summary = Summary(**{**vars_of(summary), "totals": Counts(ok=1218)})
    verdict = judge(summary)
    assert verdict.notes == ()
    page = Page(render_html(summary, verdict))
    assert ENGLISH.verdict.notes_title not in [text for _level, text in page.headings]


def test_what_was_left_out_appears_only_when_something_was() -> None:
    _document, early, _summary, _verdict = page_of(Answer.TOO_EARLY)
    _document, ready, _summary, _verdict = page_of(Answer.READY)
    title = ENGLISH.summary.left_out_title
    assert title in [text for _level, text in early.headings]
    assert title not in [text for _level, text in ready.headings]
    assert "1 file skipped" in early.texts
    assert "2 duplicates" in early.texts
    assert "1 report of another domain" in early.texts


def test_the_page_shows_no_path_and_no_file_name() -> None:
    document, _page, _summary, _verdict = page_of(Answer.TOO_EARLY)
    assert "notes.txt" not in document


def test_the_senders_table_has_a_row_per_sender_and_a_total() -> None:
    _document, page, summary, _verdict = page_of(Answer.NOT_READY)
    table = ENGLISH.summary
    assert table.senders_title in [text for _level, text in page.headings]
    assert "Example Mail" in page.texts
    assert "203.0.113.7" in page.text
    assert ENGLISH.common.kinds[Outcome.UNKNOWN] in page.text
    assert str(summary.totals.total) in page.texts


# ---------------------------------------------------------------------------
# Parity with the text format (RF-02)
# ---------------------------------------------------------------------------


@answers
def test_the_answer_the_reason_and_the_next_step_are_the_ones_of_the_text(answer: Answer) -> None:
    _document, page, _summary, verdict = page_of(answer)
    text = render_verdict(verdict)
    sentence = reason_sentence(verdict, ENGLISH)
    assert sentence in page.texts
    assert " ".join(sentence.split()) in " ".join(text.split())
    following = next_sentence(verdict, ENGLISH, on_page=True)
    if following:
        assert following in page.texts


@answers
def test_the_five_figures_are_the_ones_of_the_text(answer: Answer) -> None:
    _document, page, _summary, verdict = page_of(answer)
    text = render_verdict(verdict)
    for rule in verdict.rules:
        figure = measured_text(rule, ENGLISH)
        assert figure in page.text
        assert figure in text
        assert ENGLISH.verdict.rule_names[rule.id] in page.texts


@answers
def test_the_senders_and_the_failing_sources_are_the_ones_of_the_summary(answer: Answer) -> None:
    _document, page, summary, _verdict = page_of(answer)
    text = render_summary(summary, None)
    for row in summary.senders:
        label = row.service or row.source_ip
        assert label in text
        assert label in page.text
    for source in summary.failing:
        assert source.source_ip in text
        assert source.source_ip in page.text


def test_the_texts_of_the_sections_are_read_from_the_catalog() -> None:
    _document, page, summary, _verdict = page_of(Answer.NOT_READY)
    titles = [text for level, text in page.headings if level == 2]
    assert ENGLISH.html.rules_title in titles
    assert ENGLISH.html.mix_title.of(summary.totals.total) in titles
    assert ENGLISH.html.days_title in titles


# ---------------------------------------------------------------------------
# Language and contract (RF-08, RNF-03, RNF-04)
# ---------------------------------------------------------------------------


@answers
def test_portuguese_gives_a_portuguese_ascii_page(answer: Answer) -> None:
    document, page, _summary, verdict = page_of(answer, PORTUGUESE)
    assert document.isascii()
    assert 'lang="pt-BR"' in document
    phrase = answer_phrase(verdict, PORTUGUESE)
    assert phrase[:1].upper() + phrase[1:] in [text for _level, text in page.headings]
    assert PORTUGUESE.html.rules_title in [text for _level, text in page.headings]


@answers
def test_two_runs_give_the_same_page(answer: Answer) -> None:
    summary, verdict = judged(_RUNS[answer]())
    assert render_html(summary, verdict) == render_html(summary, verdict)


def test_english_is_the_default_language() -> None:
    summary, verdict = judged(ready_summary())
    assert render_html(summary, verdict) == render_html(summary, verdict, ENGLISH)


def test_a_year_from_a_dozen_senders_stays_under_the_ceiling() -> None:
    first = ready_summary().period.first_day  # type: ignore[union-attr]  # the period of a built summary is never None
    per_day = Counts(ok=300, dkim_only=20, spf_only=10, failing=2)
    year = 365
    totals = Counts(
        ok=per_day.ok * year,
        dkim_only=per_day.dkim_only * year,
        spf_only=per_day.spf_only * year,
        failing=per_day.failing * year,
    )
    senders = tuple(
        SenderRow(Outcome.KNOWN, service=f"Service {number}", counts=Counts(ok=1000 + number))
        for number in range(12)
    )
    summary = Summary(
        domain="example.com",
        reports=year,
        reporters=3,
        period=make_period(first, year),
        totals=totals,
        senders=senders,
        days=make_days(first, year, per_day),
        covered=((first, first + timedelta(days=year - 1)),),
    )
    document = render_html(summary, judge(summary))
    assert len(document) < 200_000


def test_an_unrecognized_source_says_what_kind_it_is_and_which_selectors_are_involved() -> None:
    summary = Summary(
        **{
            **vars_of(not_ready_summary()),
            "failing": (
                FailingSource(Outcome.FOREIGN_DOMAIN, "198.51.100.1", 3, selectors=("s1",)),
                FailingSource(Outcome.FAILING_SIGNATURE, "198.51.100.2", 2),
            ),
        }
    )
    page = Page(render_html(summary, judge(summary)))
    kinds = ENGLISH.common.kinds
    named = ENGLISH.common.selectors_named.of(1, names="s1")
    assert f"{kinds[Outcome.FOREIGN_DOMAIN]} ({named})" in page.texts
    assert kinds[Outcome.FAILING_SIGNATURE] in page.texts


def test_the_policy_list_keeps_its_own_role_and_a_group_names_it() -> None:
    # A ``role`` on the ``dl`` takes its terms out of a list (axe: ``dlitem``, serious).
    _document, page, _summary, _verdict = page_of(Answer.NOT_READY)
    lists = [attrs for tag, attrs in page.elements if tag == "dl"]
    assert lists and all("role" not in attrs and "aria-label" not in attrs for attrs in lists)
    groups = [attrs for tag, attrs in page.elements if attrs.get("role") == "group"]
    assert [attrs.get("aria-label") for attrs in groups] == [ENGLISH.html.policy_label]


def test_an_unrecognized_source_lists_the_spf_domains_that_passed_under_the_owner() -> None:
    summary = Summary(
        **{
            **vars_of(not_ready_summary()),
            "failing": (
                FailingSource(
                    Outcome.UNKNOWN,
                    "198.51.100.1",
                    3,
                    spf_domains=("a.example.com", "<b>.example.com"),
                ),
            ),
        }
    )
    page = Page(render_html(summary, judge(summary)))
    named = ENGLISH.common.spf_domains_named.of(2, names="a.example.com, <b>.example.com")
    assert any(named in found for found in page.texts)
    assert "<b>" not in render_html(summary, judge(summary))
