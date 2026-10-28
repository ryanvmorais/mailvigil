"""
Tests of ``render_html`` against hostile and extreme input (spec 008, RF-06, RF-09, ADR-8).

Isolation: pure functions over built values. The attack strings are put in every field that reaches
the page (the domain, the service names, the selectors, the addresses, the override reasons, the
mechanisms' results, the policy values); the page is parsed with the standard library and judged by
what the parser finds. The proof that nothing became markup is a comparison: the page made from the
attacks must have exactly the elements and the attributes of the page made from innocent values, so
no attack created one. Domains and addresses are invented (RNF-07).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import date, timedelta

import pytest
from tests.html_helpers import Page, make_days, make_period, not_ready_summary

from mailvigil.html_style import CONTENT_SECURITY_POLICY
from mailvigil.messages import ENGLISH, PORTUGUESE, Messages
from mailvigil.render_html import render_html
from mailvigil.reports import PolicyPublished
from mailvigil.senders import Outcome
from mailvigil.summary import Counts, FailingSource, SenderRow, Summary
from mailvigil.verdict import Answer, judge

# Short enough to survive the cut of a policy value, so each can be found again as plain text.
ATTACKS = (
    "<script>alert(1)</script>",
    '"><img src=x onerror=alert(1)>',
    "'><svg onload=alert(1)>",
    "&lt;b&gt; & &amp;",
    "</style><script>x</script>",
    "<!-- c -->",
    "--> <b>",
    "javascript:alert(1)",
    "<a href='javascript:x'>y</a>",
    "\u202e\u2066reversed",
    "ctl\x00\x07\x1b[31mred\x7f",
)

# A value that is not an attack, to build the page the attacks must be identical to.
_INNOCENT = "innocent"

# The elements that could run or load something: none may ever appear, whatever the text says.
_BANNED = {"script", "iframe", "object", "embed", "form", "link", "base"}


def hostile_run(value: str) -> Summary:
    """
    Build a failing month with ``value`` in every field that reaches the page.

    Args:
        value (str): The text to plant.

    Returns:
        Summary: A summary with a recognized and a foreign failing source, both senders and the
            policy carrying ``value``.
    """
    base = not_ready_summary()
    known = FailingSource(
        Outcome.KNOWN,
        value,
        10,
        service=value,
        selectors=(value,),
        dkim=(value,),
        spf=(value,),
        override_reasons=(value, value),
    )
    foreign = FailingSource(
        Outcome.FOREIGN_DOMAIN, value, 2, selectors=(value, value), override_reasons=(value,)
    )
    return replace(
        base,
        domain=value,
        policy=PolicyPublished(domain=value, p=value, sp=value, np=value),
        earlier_p=(value,),
        senders=(
            SenderRow(Outcome.KNOWN, service=value, counts=Counts(ok=100, failing=10)),
            SenderRow(Outcome.UNKNOWN, source_ip=value, counts=Counts(failing=2)),
            SenderRow(Outcome.FOREIGN_DOMAIN, source_ip=value, selectors=(value,)),
        ),
        failing=(known, foreign),
    )


def page_with(value: str, messages: Messages = ENGLISH) -> Page:
    """
    Render the hostile run and parse the page.

    Args:
        value (str): The text to plant.
        messages (Messages, optional): The language. Default: English.

    Returns:
        Page: The parsed document.
    """
    summary = hostile_run(value)
    return Page(render_html(summary, judge(summary), messages))


def shape(page: Page) -> tuple[Counter[str], Counter[str]]:
    """
    Describe the markup of a page without its text: how many elements and attributes of each name.

    Args:
        page (Page): The parsed page.

    Returns:
        tuple[Counter[str], Counter[str]]: The tags and the attribute names, counted.
    """
    tags = Counter(tag for tag, _attrs in page.elements)
    names = Counter(name for _tag, attrs in page.elements for name in attrs)
    return tags, names


# ---------------------------------------------------------------------------
# The attacks (RF-06)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("attack", ATTACKS)
def test_an_attack_never_creates_an_element_or_an_attribute(attack: str) -> None:
    assert shape(page_with(attack)) == shape(page_with(_INNOCENT))


@pytest.mark.parametrize("attack", ATTACKS)
def test_an_attack_leaves_no_script_no_handler_and_no_link_out(attack: str) -> None:
    page = page_with(attack)
    assert not _BANNED & {tag for tag, _attrs in page.elements}
    for tag, attrs in page.elements:
        assert not any(name.startswith("on") for name in attrs), tag
        assert "src" not in attrs and "srcdoc" not in attrs and "formaction" not in attrs
        assert attrs.get("href") is None or str(attrs["href"]).startswith("#")
    refresh = [a for t, a in page.elements if t == "meta" and a.get("http-equiv") == "refresh"]
    assert refresh == []
    assert page.comments == []


@pytest.mark.parametrize("attack", ATTACKS)
def test_an_attack_keeps_the_policy_of_the_page(attack: str) -> None:
    page = page_with(attack)
    policies = [
        attrs["content"]
        for tag, attrs in page.elements
        if tag == "meta" and attrs.get("http-equiv") == "Content-Security-Policy"
    ]
    assert policies == [CONTENT_SECURITY_POLICY]
    assert "</style" not in page.stylesheet.lower() and "<" not in page.stylesheet


@pytest.mark.parametrize("attack", ATTACKS)
def test_an_attack_shows_only_as_the_text_of_a_node(attack: str) -> None:
    printable = "".join(c for c in attack if c.isprintable() and c not in "\u202e\u2066").strip()
    page = page_with(attack)
    assert printable in page.text


@pytest.mark.parametrize("attack", ATTACKS)
def test_the_page_made_from_an_attack_is_ascii(attack: str) -> None:
    summary = hostile_run(attack)
    assert render_html(summary, judge(summary)).isascii()


def test_control_and_bidirectional_characters_do_not_reach_the_page() -> None:
    page = page_with("a\x00b\x1bc\u202ed\u2066e")
    assert "\x00" not in page.text and "\x1b" not in page.text
    assert "\u202e" not in page.text and "\u2066" not in page.text


def test_a_very_long_value_is_cut_and_the_page_stays_small() -> None:
    summary = hostile_run("A" * 1_000_000)
    document = render_html(summary, judge(summary))
    assert len(document) < 200_000
    assert "A" * 400 not in document


def test_the_attacks_are_also_harmless_in_portuguese() -> None:
    for attack in ATTACKS:
        assert shape(page_with(attack, PORTUGUESE)) == shape(page_with(_INNOCENT, PORTUGUESE))


# ---------------------------------------------------------------------------
# Extreme input (RF-09)
# ---------------------------------------------------------------------------


def extreme(summary: Summary) -> Page:
    """
    Render a summary with its own verdict and check the page is a valid, safe document.

    Args:
        summary (Summary): The summary, usually an extreme one.

    Returns:
        Page: The parsed page, for the checks of the test.
    """
    document = render_html(summary, judge(summary))
    page = Page(document)
    assert document.startswith("<!doctype html>") and document.isascii()
    assert page.count("h1") == 1
    assert not _BANNED & {tag for tag, _attrs in page.elements}
    return page


def test_a_period_of_a_century_is_a_bounded_page() -> None:
    first = date(1926, 1, 1)
    length = 36525
    per_day = Counts(ok=1)
    summary = replace(
        not_ready_summary(),
        period=make_period(first, length),
        days=make_days(first, 3, per_day),
        covered=((first, first + timedelta(days=2)),),
    )
    document = render_html(summary, judge(summary))
    assert len(document) < 200_000
    assert Page(document).count("rect") < 500


def test_one_day_with_a_huge_count_is_a_valid_page() -> None:
    huge = Counts(ok=10**15, dkim_only=3, failing=10**9)
    summary = replace(
        not_ready_summary(),
        totals=huge,
        days=make_days(date(2026, 9, 1), 29, huge)[:1],
    )
    extreme(summary)


def test_a_situation_with_no_messages_is_still_named() -> None:
    summary = replace(not_ready_summary(), totals=Counts(ok=1200))
    page = extreme(summary)
    assert ENGLISH.html.situation_failing in page.text


def test_every_rule_failing_is_a_not_ready_page() -> None:
    first = date(2026, 9, 1)
    summary = Summary(
        domain="example.com",
        reports=1,
        reporters=1,
        period=make_period(first, 1),
        totals=Counts(failing=40),
        senders=(SenderRow(Outcome.UNKNOWN, source_ip="198.51.100.1", counts=Counts(failing=40)),),
        failing=(FailingSource(Outcome.UNKNOWN, "198.51.100.1", 40),),
        days=make_days(first, 1, Counts(failing=40)),
        covered=((first, first),),
    )
    verdict = judge(summary)
    failed = [rule for rule in verdict.rules if not rule.passed]
    assert verdict.answer is Answer.NOT_READY and len(failed) >= 3
    assert len(extreme(summary).with_class("fail")) == len(failed)


def test_a_run_with_nothing_in_it_is_a_valid_page() -> None:
    page = extreme(Summary(domain="example.com"))
    assert ENGLISH.summary.no_period in " ".join(page.texts)
    assert page.with_class("stack") == []
    assert page.count("table") == 0


def test_a_source_with_no_address_is_named() -> None:
    summary = replace(
        not_ready_summary(), failing=(FailingSource(Outcome.UNKNOWN, "", 3),), senders=()
    )
    assert ENGLISH.common.no_address in extreme(summary).text


def test_many_failing_sources_are_cut_and_counted() -> None:
    sources = tuple(FailingSource(Outcome.UNKNOWN, f"198.51.100.{n}", 1) for n in range(1, 60))
    summary = replace(not_ready_summary(), failing=sources)
    page = extreme(summary)
    assert "198.51.100.59" not in page.text
    assert "198.51.100.1" in page.text
