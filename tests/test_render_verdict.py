"""
Tests of the text of the verdict: the title, the reason, the rules table, the notes, the next step.

Isolation: nothing touches the disk and no command runs. Verdicts are built with ``make_verdict``,
which judges a small ``Summary`` whose defaults are a clean, long, busy domain, so each test states
only what it changes. The output is read back by its structure (lines, cells), never by its exact
spacing, which the design does not fix. Domains, services and addresses are invented
(``example.com``, ``example.net``; ``192.0.2.0/24``, ``198.51.100.0/24``, ``203.0.113.0/24``,
``2001:db8::/32``; RNF-06).
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from tests.render_verdict_golden import GOLDEN

from mailvigil import verdict as verdict_module
from mailvigil.messages import ENGLISH, PORTUGUESE, Messages
from mailvigil.render_verdict import (
    measured_text,
    missing_text,
    needed_text,
    next_sentence,
    note_sentence,
    reason_sentence,
    render_verdict,
)
from mailvigil.reports import PolicyPublished
from mailvigil.senders import Outcome
from mailvigil.summary import Counts, FailingSource, Period, Summary
from mailvigil.verdict import (
    MAX_UNRECOGNIZED_PER_MILLE,
    MIN_COVERAGE_PERCENT,
    MIN_DAYS_SPANNED,
    MIN_MESSAGES,
    Answer,
    LeftOut,
    Note,
    NoteKind,
    RuleId,
    Verdict,
    judge,
)

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

_FIRST_DAY = date(2026, 9, 1)
_KNOWN_IP = "192.0.2.10"
_CAVEAT = (
    "This reads only the reports you gave it: mail that no receiver reports on, and senders that "
    "were quiet in this period, are not covered."
)


def make_verdict(
    *,
    domain: str = "example.com",
    days: int = 28,
    with_reports: int | None = None,
    ok: int = 2000,
    dkim_only: int = 0,
    spf_only: int = 0,
    sources: tuple[FailingSource, ...] = (),
    p: str = "none",
    pct: int = 100,
    sp: str = "",
    np: str = "",
    earlier_p: tuple[str, ...] = (),
) -> Verdict:
    """
    Judge a ``Summary`` whose figures agree with each other.

    Args:
        domain (str, optional): The domain. Default: ``example.com``.
        days (int, optional): The days the reports span; 0 builds a summary without reports.
            Default: 28.
        with_reports (int | None, optional): The days with a report. Default: ``days``.
        ok (int, optional): Messages where DKIM and SPF passed. Default: 2000.
        dkim_only (int, optional): Fragile messages where only DKIM passed. Default: 0.
        spf_only (int, optional): Fragile messages where only SPF passed. Default: 0.
        sources (tuple[FailingSource, ...], optional): The failing sources; the failing total is
            their sum. Default: none.
        p (str, optional): The latest published ``p``. Default: ``none``.
        pct (int, optional): The latest published ``pct``. Default: 100.
        sp (str, optional): The latest published ``sp``. Default: empty.
        np (str, optional): The latest published ``np``. Default: empty.
        earlier_p (tuple[str, ...], optional): The other ``p`` values seen. Default: none.

    Returns:
        Verdict: What ``judge`` says about it.
    """
    failing = sum(source.messages for source in sources)
    if days == 0:
        return judge(Summary(domain=domain))
    begin = datetime.combine(_FIRST_DAY, datetime.min.time(), tzinfo=UTC)
    period = Period(
        begin=begin,
        end=begin + timedelta(days=days),
        first_day=_FIRST_DAY,
        last_day=_FIRST_DAY + timedelta(days=days - 1),
        days_spanned=days,
        days_with_reports=days if with_reports is None else with_reports,
    )
    return judge(
        Summary(
            domain=domain,
            reports=days,
            reporters=2,
            period=period,
            policy=PolicyPublished(domain=domain, p=p, sp=sp, np=np, pct=pct),
            earlier_p=earlier_p,
            totals=Counts(ok=ok, dkim_only=dkim_only, spf_only=spf_only, failing=failing),
            failing=sources,
        )
    )


def known(
    messages: int, *, service: str = "Example Mailer", ip: str = _KNOWN_IP, **kwargs: Any
) -> FailingSource:
    """
    Build a failing source of a recognized sender.

    Args:
        messages (int): The failing messages.
        service (str, optional): The service name. Default: ``Example Mailer``.
        ip (str, optional): The source address. Default: ``192.0.2.10``.
        **kwargs (object): Other ``FailingSource`` fields, such as ``override_reasons``.

    Returns:
        FailingSource: The source.
    """
    return FailingSource(Outcome.KNOWN, ip, messages, service, **kwargs)


def other(
    messages: int, number: int = 1, outcome: Outcome = Outcome.UNKNOWN, **kwargs: Any
) -> FailingSource:
    """
    Build a failing source that is not recognized.

    Args:
        messages (int): The failing messages.
        number (int, optional): The last byte of its address in ``198.51.100.0/24``. Default: 1.
        outcome (Outcome, optional): What identification said. Default: ``UNKNOWN``.
        **kwargs (object): Other ``FailingSource`` fields, such as ``selectors``.

    Returns:
        FailingSource: The source.
    """
    ip = f"198.51.100.{number}"
    return FailingSource(outcome, ip, messages, **kwargs)


def lines_of(verdict: Verdict) -> list[str]:
    """
    Render a verdict and split it into lines.

    Args:
        verdict (Verdict): The verdict.

    Returns:
        list[str]: The lines of the text.
    """
    return render_verdict(verdict).split("\n")


def flat(text: str) -> str:
    """
    Join the wrapped lines of a text, so a sentence can be searched whatever its line breaks.

    Args:
        text (str): The text.

    Returns:
        str: The text with every run of white space reduced to one space.
    """
    return " ".join(text.split())


def table(verdict: Verdict) -> list[list[str]]:
    """
    Read the rules table back: the header and the five rows, each as its cells.

    Args:
        verdict (Verdict): The verdict.

    Returns:
        list[list[str]]: Six rows of cells; a cell ends where two or more spaces begin.
    """
    lines = lines_of(verdict)
    start = lines.index("Rules") + 1
    return [re.split(r"\s{2,}", line.strip()) for line in lines[start : start + 6]]


# ---------------------------------------------------------------------------
# The title (RF-03, RF-05)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "phrase"),
    [
        ({}, "READY for p=reject"),
        ({"sources": (known(3),)}, "NOT READY for p=reject"),
        ({"days": 10}, "TOO EARLY to say"),
        ({"days": 0}, "TOO EARLY to say"),
        ({"p": "quarantine"}, "READY for p=reject"),
        ({"p": "none"}, "READY for p=reject"),
        ({"p": "?"}, "READY for p=reject"),
    ],
)
def test_the_title_names_the_answer(kwargs: dict[str, Any], phrase: str) -> None:
    """The first line is the domain and one of the three answers, in the words of RF-03."""
    verdict = make_verdict(**kwargs)
    assert lines_of(verdict)[0] == f"MailVigil verdict for example.com: {phrase}"


@pytest.mark.parametrize(
    ("kwargs", "phrase"),
    [
        ({}, "NO PROBLEM SEEN"),
        ({"sources": (known(3),)}, "BLOCKING REAL MAIL"),
        ({"days": 10}, "TOO EARLY to say"),
    ],
)
@pytest.mark.parametrize("p", ["reject", " REJECT "])
def test_a_policy_that_enforces_changes_the_words(
    kwargs: dict[str, Any], phrase: str, p: str
) -> None:
    """Under ``p=reject`` the title is read as "is enforcement blocking real mail" (RF-05)."""
    verdict = make_verdict(p=p, **kwargs)
    first = lines_of(verdict)[0]
    assert first == f"MailVigil verdict for example.com: already at p=reject: {phrase}"


def test_the_reject_wording_changes_nothing_but_the_words() -> None:
    """The same traffic gives the same answer and the same table under ``reject`` (RF-05)."""
    plain = make_verdict(sources=(known(3),))
    enforcing = make_verdict(sources=(known(3),), p="reject")
    assert plain.answer is enforcing.answer is Answer.NOT_READY
    assert table(plain) == table(enforcing)


def test_a_title_too_wide_for_one_line_goes_on_two() -> None:
    """A long domain keeps the answer visible: the answer moves to the second line."""
    domain = "a" * 28 + ".example.com"
    first, second = lines_of(make_verdict(domain=domain, p="reject", sources=(known(3),)))[:2]
    assert first == f"MailVigil verdict for {domain}"
    assert second == "Already at p=reject: BLOCKING REAL MAIL"
    assert max(len(first), len(second)) <= 80


def test_a_very_long_domain_is_cut_in_the_title() -> None:
    """A domain wider than the screen is cut with ``...``; the answer stays whole."""
    first, second = lines_of(make_verdict(domain="a" * 250 + ".example.com"))[:2]
    assert len(first) == 80 and first.endswith("...")
    assert second == "READY for p=reject"


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"days": 10},
        {"days": 0},
        {"sources": (known(3),)},
        {"sources": (other(40),)},
        {"p": "reject"},
        {"p": "reject", "sources": (known(3),)},
        {"p": "quarantine", "dkim_only": 10, "spf_only": 5, "pct": 50, "sp": "reject"},
    ],
)
def test_the_words_safe_and_attack_never_appear(kwargs: dict[str, Any]) -> None:
    """The verdict never promises safety and never calls a failing source an attack (RF-03)."""
    text = render_verdict(make_verdict(**kwargs)).lower()
    assert "safe" not in text
    assert "attack" not in text


# ---------------------------------------------------------------------------
# The reason: a recognized sender fails (rule 4)
# ---------------------------------------------------------------------------


def test_rule_four_names_each_recognized_source() -> None:
    """The reason lists the service, its failing messages and its address."""
    verdict = make_verdict(
        sources=(known(12), known(1, service="Example Billing", ip="192.0.2.20"))
    )
    text = render_verdict(verdict)
    assert "Why: a recognized sender fails DMARC." in text
    assert "  Example Mailer: 12 failing messages from 192.0.2.10" in text.split("\n")
    assert "  Example Billing: 1 failing message from 192.0.2.20" in text.split("\n")


def test_rule_four_shows_the_override_types_next_to_the_source() -> None:
    """A forwarded or list message still fails; the reason types explain it (RF-03)."""
    source = known(3, override_reasons=("forwarded", "mailing_list"))
    line = "  Example Mailer: 3 failing messages from 192.0.2.10 (forwarded, mailing_list)"
    assert line in lines_of(make_verdict(sources=(source,)))


def test_rule_four_says_when_a_source_has_no_address() -> None:
    """A report may leave the address empty: the line says so instead of printing nothing."""
    verdict = make_verdict(sources=(known(3, ip=""),))
    assert "  Example Mailer: 3 failing messages from no address" in lines_of(verdict)


def test_rule_four_prints_ten_sources_and_counts_the_rest() -> None:
    """More than ten recognized sources print ten and a line that still counts the others."""
    sources = tuple(known(12 - i, ip=f"192.0.2.{i + 1}") for i in range(12))
    lines = lines_of(make_verdict(sources=sources))
    printed = [line for line in lines if line.startswith("  Example Mailer: ")]
    assert len(printed) == 10
    assert "  ... and 2 other sources: 3 failing messages" in lines


def test_rule_four_decides_the_reason_even_when_rule_five_also_fails() -> None:
    """The reason is about the first failed problem rule; the table still shows both."""
    verdict = make_verdict(sources=(known(3), other(300)))
    text = render_verdict(verdict)
    assert "a recognized sender fails DMARC" in text
    assert "unrecognized sources are" not in flat(text)
    assert [row[-1] for row in table(verdict)[4:]] == ["FAIL", "FAIL"]


# ---------------------------------------------------------------------------
# The reason: unrecognized sources fail (rule 5)
# ---------------------------------------------------------------------------


def test_rule_five_prints_the_share_the_limit_and_the_first_five_sources() -> None:
    """The share comes with its counts and the limit; five sources print, the rest are counted."""
    sources = tuple(other(m, number=i + 1) for i, m in enumerate((30, 20, 10, 8, 6, 4, 2)))
    verdict = make_verdict(sources=sources)
    text = render_verdict(verdict)
    lines = text.split("\n")
    assert (
        "Why: failures from unrecognized sources are 3.8% of the messages (80 of 2080); the limit "
        "is 0.5%." in flat(text)
    )
    assert "  198.51.100.1  unrecognized: 30 failing messages" in lines
    assert "  198.51.100.5  unrecognized: 6 failing messages" in lines
    assert not any(line.startswith("  198.51.100.6") for line in lines)
    assert "  ... and 2 other sources: 6 failing messages" in lines


def test_rule_five_labels_a_foreign_domain_and_a_failing_signature() -> None:
    """The labels of 004 are kept, with the configured selectors that were involved."""
    sources = (
        other(40, 1, Outcome.FOREIGN_DOMAIN, selectors=("s1",)),
        other(30, 2, Outcome.FAILING_SIGNATURE, selectors=("s1", "s2")),
        other(20, 3, Outcome.FOREIGN_DOMAIN),
    )
    lines = lines_of(make_verdict(sources=sources))
    assert "  198.51.100.1  foreign domain (selector s1): 40 failing messages" in lines
    assert "  198.51.100.2  failing signature (selectors s1, s2): 30 failing messages" in lines
    assert "  198.51.100.3  foreign domain: 20 failing messages" in lines


def test_rule_five_shows_the_override_types_and_a_missing_address() -> None:
    """Every listed source carries its override types, whoever the sender is."""
    sources = (
        FailingSource(Outcome.UNKNOWN, "", 40, override_reasons=("forwarded",)),
        other(30, 2),
    )
    lines = lines_of(make_verdict(sources=sources))
    assert "  no address  unrecognized: 40 failing messages (forwarded)" in lines


# ---------------------------------------------------------------------------
# The reason: too early
# ---------------------------------------------------------------------------


def test_too_early_says_how_much_each_failed_data_rule_lacks() -> None:
    """Days and messages missing are named, with their rule (RF-03)."""
    verdict = make_verdict(days=27, ok=80)
    lines = lines_of(verdict)
    assert "Why: not enough reports to tell yet." in lines
    assert "  period covered: need 1 more day" in lines
    assert "  messages seen: need 20 more messages" in lines
    assert not any(line.startswith("  days with a report") for line in lines)


def test_too_early_counts_the_days_with_a_report_that_are_missing() -> None:
    """Twenty of twenty-eight days with a report lack three (rounded up from 22.4)."""
    lines = lines_of(make_verdict(days=28, with_reports=20))
    assert "  days with a report: need 3 more days" in lines


def test_too_early_with_no_reports_says_that_none_was_kept() -> None:
    """With no reports at all the one line is that none was kept, not three amounts missing."""
    lines = lines_of(make_verdict(days=0))
    assert "  no report was kept for this domain" in lines
    assert not any("need " in line for line in lines)


def test_too_early_with_zero_messages_asks_for_them() -> None:
    """Reports present but empty: the missing messages are the whole threshold."""
    lines = lines_of(make_verdict(ok=0))
    assert "  messages seen: need 100 more messages" in lines


# ---------------------------------------------------------------------------
# The reason: ready
# ---------------------------------------------------------------------------


def test_ready_says_that_every_rule_passes() -> None:
    """A clean table prints no list of sources."""
    lines = lines_of(make_verdict())
    assert "Why: every rule passes." in lines
    assert not any(line.startswith("Still failing") for line in lines)


def test_ready_still_lists_the_unrecognized_sources_under_the_limit() -> None:
    """The first five print, and the others are counted (ADR-3)."""
    sources = tuple(other(1, number=i + 1) for i in range(7))
    lines = lines_of(make_verdict(sources=sources))
    assert "Why: every rule passes." in lines
    assert "Still failing from unrecognized sources, under the limit:" in lines
    assert "  198.51.100.5  unrecognized: 1 failing message" in lines
    assert not any(line.startswith("  198.51.100.6") for line in lines)
    assert "  ... and 2 other sources: 2 failing messages" in lines


# ---------------------------------------------------------------------------
# The rules table (RF-03)
# ---------------------------------------------------------------------------


def test_the_table_has_the_five_rules_with_what_was_measured_and_needed() -> None:
    """Id, name, measured, needed and result for each rule."""
    verdict = make_verdict(days=28, with_reports=27, ok=12468, sources=(known(12),))
    assert table(verdict) == [
        ["rule", "measured", "needed", "result"],
        ["1", "period covered", "28 days", ">= 28", "pass"],
        ["2", "days with a report", "27 of 28 (96.4%)", ">= 80%", "pass"],
        ["3", "messages seen", "12480", ">= 100", "pass"],
        ["4", "recognized failures", "12", "<= 0", "FAIL"],
        ["5", "unrecognized failures", "0 (0%)", "<= 0.5%", "pass"],
    ]


def test_a_failed_data_rule_reads_fail_too_early_and_a_problem_rule_reads_fail() -> None:
    """The two kinds of failure are told apart in the last column (RF-01)."""
    verdict = make_verdict(days=27, sources=(other(40),))
    results = [row[-1] for row in table(verdict)[1:]]
    assert results == ["fail (too early)", "pass", "pass", "pass", "FAIL"]


def test_a_share_is_printed_beside_its_count() -> None:
    """The share of rule 5 comes with the messages it counts; a tiny share is never ``0%``."""
    verdict = make_verdict(ok=99990, sources=(other(10),))
    assert table(verdict)[5][2] == "10 (<0.1%)"
    assert table(make_verdict(sources=(other(20),)))[5][2] == "20 (1.0%)"


def test_no_reports_gives_a_table_without_a_division() -> None:
    """Zero days and zero messages print as zeros."""
    rows = table(make_verdict(days=0))
    assert rows[1][2] == "0 days"
    assert rows[2][2] == "0 of 0 (0%)"
    assert rows[3][2] == "0"
    assert [row[-1] for row in rows[1:]] == [
        "fail (too early)",
        "fail (too early)",
        "fail (too early)",
        "pass",
        "pass",
    ]


# ---------------------------------------------------------------------------
# The notes (RF-04)
# ---------------------------------------------------------------------------


def notes_of(verdict: Verdict) -> list[str]:
    """
    Read the notes back, one sentence each.

    Args:
        verdict (Verdict): The verdict.

    Returns:
        list[str]: The notes, joined across their wrapped lines; empty when there is no section.
    """
    text = render_verdict(verdict)
    if "\nNotes\n" not in text:
        return []
    section = text.split("\nNotes\n")[1].split("\n\n")[0]
    return [flat(note) for note in re.split(r"(?m)^  - ", section)[1:]]


def test_no_notes_prints_no_section() -> None:
    """Nothing to say, no title either."""
    assert notes_of(make_verdict()) == []
    assert "Notes" not in render_verdict(make_verdict())


def test_each_note_says_its_one_thing() -> None:
    """One sentence per note, with the numbers it was given."""
    assert notes_of(make_verdict(ok=1900, dkim_only=60, spf_only=40)) == [
        "Fragile traffic: 100 of 2000 messages (5.0%) pass by only one of DKIM and SPF; 40 of "
        "those by SPF only, which forwarding breaks."
    ]
    assert notes_of(make_verdict(pct=50)) == [
        "The policy applies to only 50% of the mail (pct=50)."
    ]
    assert notes_of(make_verdict(earlier_p=("none", "quarantine"))) == [
        "The policy changed during the period (earlier p: none, quarantine), so the figures mix "
        "policies."
    ]
    assert notes_of(make_verdict(sp="reject")) == [
        "Subdomains have their own policy (sp=reject): moving p does not change it."
    ]
    assert notes_of(make_verdict(sp="reject", np="quarantine")) == [
        "Subdomains have their own policy (sp=reject, np=quarantine): moving p does not change it."
    ]
    assert notes_of(make_verdict(p="quarantine")) == [
        "The policy is p=quarantine now; this verdict is about moving to p=reject."
    ]


def test_several_notes_come_in_the_order_of_their_kinds() -> None:
    """Fragile traffic first, quarantine last, as ``NoteKind`` orders them."""
    verdict = make_verdict(p="quarantine", dkim_only=10, pct=50, earlier_p=("none",))
    kinds = [note.kind for note in verdict.notes]
    assert kinds == sorted(kinds, key=list(NoteKind).index)
    sentences = notes_of(verdict)
    assert len(sentences) == len(kinds) == 4
    assert sentences[0].startswith("Fragile traffic")
    assert sentences[-1].startswith("The policy is p=quarantine")


def test_every_kind_of_note_has_a_text() -> None:
    """A kind added to ``NoteKind`` later cannot reach the output as a bare key or an error."""
    base = make_verdict()
    for kind in NoteKind:
        note = Note(kind, numbers=(1, 2, 3), texts=("a", "b"))
        out = render_verdict(dataclasses.replace(base, notes=(note,)))
        assert len(re.findall(r"(?m)^  - ", out)) == 1


# ---------------------------------------------------------------------------
# The next step and the caveat (RF-03)
# ---------------------------------------------------------------------------


def next_step(verdict: Verdict) -> str:
    """
    Read the next step back.

    Args:
        verdict (Verdict): The verdict.

    Returns:
        str: The sentence after ``Next:``, joined across its lines; empty when there is none.
    """
    text = render_verdict(verdict)
    for paragraph in text.split("\n\n"):
        if paragraph.startswith("Next:"):
            return flat(paragraph)
    return ""


def test_the_next_step_for_a_recognized_sender_names_the_service() -> None:
    """Rule 4: make it sign with the domain or add its servers to SPF."""
    assert next_step(make_verdict(sources=(known(3),))) == (
        "Next: make Example Mailer sign with your domain (DKIM) or add its servers to SPF, then "
        "collect another period."
    )


def test_the_next_step_for_several_recognized_services_does_not_pick_one() -> None:
    """Two services, or one on two addresses: the sentence is about the list above."""
    two = (known(3), known(2, service="Example Billing", ip="192.0.2.20"))
    assert "make each service listed above sign" in next_step(make_verdict(sources=two))
    same = (known(3), known(2, ip="192.0.2.20"))
    assert "make Example Mailer sign" in next_step(make_verdict(sources=same))


def test_the_next_step_for_unrecognized_sources_points_at_the_configuration() -> None:
    """Rule 5: look at the sources, add the selectors that are yours."""
    assert next_step(make_verdict(sources=(other(40),))) == (
        "Next: look at the sources above and add the selectors of the ones that are yours to "
        "[senders] in the configuration."
    )


def test_the_next_step_for_a_data_rule_is_to_collect_more() -> None:
    """Rules 1 to 3: keep collecting until the marked rules pass."""
    assert next_step(make_verdict(days=10)) == (
        "Next: keep collecting reports until the rules marked 'fail (too early)' pass."
    )


def test_a_ready_verdict_has_no_next_step() -> None:
    """There is nothing left to do."""
    assert next_step(make_verdict()) == ""
    assert "Next:" not in render_verdict(make_verdict())


@pytest.mark.parametrize(
    "kwargs",
    [{}, {"days": 10}, {"days": 0}, {"sources": (known(3),)}, {"sources": (other(40),)}],
)
def test_the_caveat_closes_every_verdict(kwargs: dict[str, Any]) -> None:
    """The last paragraph is always the same sentence."""
    text = render_verdict(make_verdict(**kwargs))
    assert flat(text.split("\n\n")[-1]) == _CAVEAT


def test_the_sections_come_in_order_with_one_blank_line_between() -> None:
    """Title, reason, table, notes, next step, caveat; no trailing newline."""
    verdict = make_verdict(sources=(known(3),), pct=50)
    text = render_verdict(verdict)
    starts = [paragraph.split("\n")[0].split(" ")[0] for paragraph in text.split("\n\n")]
    assert starts == ["MailVigil", "Why:", "Rules", "Notes", "Next:", "This"]
    assert not text.endswith("\n")
    assert "\n\n\n" not in text


def test_the_text_is_the_same_each_time() -> None:
    """Rendering reads nothing but the verdict (RNF-02)."""
    verdict = make_verdict(sources=(known(3), other(40)), pct=50)
    assert render_verdict(verdict) == render_verdict(verdict)


# ---------------------------------------------------------------------------
# The layout (004 RF-09)
# ---------------------------------------------------------------------------

_LONG_NAME = "N" * 100
_V6 = "2001:db8:85a3:8d3:1319:8a2e:370:7344"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sources": (known(12, service=_LONG_NAME),)},
        {"sources": (known(12, service=_LONG_NAME, ip=_V6, override_reasons=("forwarded",)),)},
        {"sources": (known(12, ip=_V6, override_reasons=("forwarded", "mailing_list", "other")),)},
        {"sources": (other(40, selectors=("s" * 60,), outcome=Outcome.FAILING_SIGNATURE),)},
        {"sources": (FailingSource(Outcome.UNKNOWN, _V6, 40, override_reasons=("forwarded",)),)},
        {"ok": 10**12, "sources": (known(10**12, service=_LONG_NAME, ip=_V6),)},
        {"ok": 10**12, "sources": (FailingSource(Outcome.UNKNOWN, _V6, 10**12),)},
        {"ok": 10**30, "sources": (FailingSource(Outcome.UNKNOWN, _V6, 10**29),)},
        {"days": 0, "domain": "a" * 200 + ".example.com"},
        {"p": "reject", "domain": "a" * 60 + ".example.com", "sources": (known(3),)},
        {"earlier_p": ("n" * 90,), "sp": "s" * 90, "np": "n" * 90, "dkim_only": 5, "pct": 50},
        {"days": 10, "p": "quarantine"},
    ],
)
def test_no_line_is_wider_than_eighty_columns(kwargs: dict[str, Any]) -> None:
    """Long names, IPv6 addresses and huge counts are cut or wrapped, never overflowing."""
    lines = lines_of(make_verdict(**kwargs))
    assert max(len(line) for line in lines) <= 80


def test_a_name_wider_than_its_line_is_cut_with_dots_and_keeps_its_numbers() -> None:
    """The name is what gives way: the count and the address stay readable."""
    verdict = make_verdict(sources=(known(12, service=_LONG_NAME),))
    line = next(line for line in lines_of(verdict) if "failing messages from" in line)
    assert "..." in line
    assert line.endswith(": 12 failing messages from 192.0.2.10")


def test_a_huge_count_is_printed_whole() -> None:
    """A count of ``10**12`` is not abbreviated anywhere."""
    verdict = make_verdict(ok=10**12, sources=(FailingSource(Outcome.UNKNOWN, _KNOWN_IP, 10**12),))
    text = render_verdict(verdict)
    assert "1000000000000 (50.0%)" in text
    assert "1000000000000 failing messages" in text


def test_the_output_is_ascii_apart_from_names() -> None:
    """Every character outside the names is ASCII."""
    verdict = make_verdict(
        sources=(known(3), other(40)), pct=50, dkim_only=5, p="quarantine", earlier_p=("none",)
    )
    assert render_verdict(verdict).isascii()


def test_the_output_has_no_color_and_no_control_code() -> None:
    """Text from a report is made inert: no escape, no carriage return, no stray line break."""
    nasty = "Evil\x1b[31m Mailer\r\nRED\x07"
    verdict = make_verdict(sources=(known(3, service=nasty, ip="192.0.2.10\x1b[0m"),))
    text = render_verdict(verdict)
    assert "\x1b" not in text and "\r" not in text and "\x07" not in text
    assert all(char == "\n" or char.isprintable() for char in text)


# ---------------------------------------------------------------------------
# The criterion cannot drift from the text (RNF-05)
# ---------------------------------------------------------------------------


def test_the_needed_column_is_built_from_the_constants() -> None:
    """With the real constants the column reads them back, in the unit of each rule."""
    per_mille = f"{MAX_UNRECOGNIZED_PER_MILLE // 10}.{MAX_UNRECOGNIZED_PER_MILLE % 10}%"
    assert [row[3] for row in table(make_verdict())[1:]] == [
        f">= {MIN_DAYS_SPANNED}",
        f">= {MIN_COVERAGE_PERCENT}%",
        f">= {MIN_MESSAGES}",
        "<= 0",
        f"<= {per_mille}",
    ]


@pytest.mark.parametrize(
    ("name", "value", "kwargs", "needed", "sentence"),
    [
        ("MIN_DAYS_SPANNED", 14, {"days": 10}, ">= 14", "need 4 more days"),
        ("MIN_COVERAGE_PERCENT", 90, {"with_reports": 20}, ">= 90%", "need 6 more days"),
        ("MIN_MESSAGES", 500, {"ok": 300}, ">= 500", "need 200 more messages"),
        (
            "MAX_UNRECOGNIZED_PER_MILLE",
            20,
            {"sources": (other(300),)},
            "<= 2.0%",
            "the limit is 2.0%",
        ),
    ],
)
def test_changing_a_constant_changes_the_column_and_the_explanation(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: int,
    kwargs: dict[str, Any],
    needed: str,
    sentence: str,
) -> None:
    """Nothing in the text retypes a threshold: move the constant and the text follows."""
    monkeypatch.setattr(verdict_module, name, value)
    verdict = make_verdict(**kwargs)
    assert needed in [row[3] for row in table(verdict)[1:]]
    assert sentence in flat(render_verdict(verdict))


# ---------------------------------------------------------------------------
# A share never reads against its result (RF-08, ADR-8)
# ---------------------------------------------------------------------------


def _measured_cell(verdict: Verdict, row: int) -> str:
    """Return the "measured" cell of a rule (1 to 5) of the rendered table."""
    return table(verdict)[row][2]


@pytest.mark.parametrize("failing", [151, 160])
def test_a_failed_share_that_rounds_to_the_limit_is_printed_beyond_it(failing: int) -> None:
    """151 and 160 of 30000 both round to 0.5%, the limit, and both fail: neither may read 0.5%."""
    verdict = make_verdict(ok=30000 - failing, sources=(other(failing),))
    text = flat(render_verdict(verdict))

    assert _measured_cell(verdict, 5).startswith(f"{failing} (>0.5%)")
    assert f">0.5% of the messages ({failing} of 30000); the limit is 0.5%" in text
    assert "FAIL" in table(verdict)[5]
    assert "(0.5%)" not in text


def test_a_share_exactly_at_the_limit_still_prints_as_the_limit() -> None:
    """150 of 30000 is 0.5% and passes: the text is what it was before."""
    verdict = make_verdict(ok=29850, sources=(other(150),))
    assert _measured_cell(verdict, 5) == "150 (0.5%)"
    assert table(verdict)[5][-1] == "pass"


def test_a_failed_share_that_rounds_above_the_limit_prints_as_before() -> None:
    """170 of 30000 rounds to 0.6%: that already reads as over 0.5%."""
    verdict = make_verdict(ok=29830, sources=(other(170),))
    assert _measured_cell(verdict, 5) == "170 (0.6%)"
    assert "0.6% of the messages (170 of 30000)" in flat(render_verdict(verdict))


def test_the_coverage_rule_prints_less_than_the_limit_when_it_fails_at_80_percent() -> None:
    """2399 of 3000 days is 79.97%: it fails, and 80.0% beside ``>= 80%`` would read as a pass."""
    verdict = make_verdict(days=3000, with_reports=2399)
    assert _measured_cell(verdict, 2) == "2399 of 3000 (<80%)"
    assert table(verdict)[2][-1] == "fail (too early)"


def test_the_coverage_rule_at_exactly_the_limit_prints_the_rounded_share() -> None:
    """2400 of 3000 days is 80% and passes."""
    verdict = make_verdict(days=3000, with_reports=2400)
    assert _measured_cell(verdict, 2) == "2400 of 3000 (80.0%)"


def test_a_coverage_failure_clearly_under_the_limit_prints_as_before() -> None:
    """20 of 28 days is 71.4%."""
    verdict = make_verdict(days=28, with_reports=20)
    assert _measured_cell(verdict, 2) == "20 of 28 (71.4%)"


def test_the_beyond_the_limit_form_follows_the_rule_not_the_text() -> None:
    """A hand-built rule that passed prints the rounded share even when it equals the limit."""
    verdict = make_verdict(ok=29849, sources=(other(151),))
    rules = tuple(
        dataclasses.replace(r, passed=True) if r.id is RuleId.UNRECOGNIZED_FAILURES else r
        for r in verdict.rules
    )
    forged = dataclasses.replace(verdict, rules=rules)
    assert _measured_cell(forged, 5) == "151 (0.5%)"


# ---------------------------------------------------------------------------
# The verdict says what was left out (RF-09, ADR-9)
# ---------------------------------------------------------------------------


def _with_left_out(left_out: LeftOut, **kwargs: Any) -> Verdict:
    """Judge a verdict and attach the figures of what was left out."""
    return dataclasses.replace(make_verdict(**kwargs), left_out=left_out)


def _left_out_text(verdict: Verdict) -> str:
    """Return the left-out sentence of the rendered text, or an empty string."""
    paragraphs = render_verdict(verdict).split("\n\n")
    found = [flat(p) for p in paragraphs if p.startswith("Left out")]
    return found[0] if found else ""


def test_nothing_left_out_prints_no_line_and_no_section() -> None:
    """The text is exactly what it was before RF-09."""
    verdict = make_verdict()
    assert "Left out" not in render_verdict(verdict)
    assert render_verdict(dataclasses.replace(verdict, left_out=LeftOut())) == render_verdict(
        verdict
    )


@pytest.mark.parametrize(
    ("left_out", "expected"),
    [
        (
            LeftOut(skipped=1),
            "Left out of this verdict: 1 file skipped. mailvigil summary shows why.",
        ),
        (
            LeftOut(skipped=2),
            "Left out of this verdict: 2 files skipped. mailvigil summary shows why.",
        ),
        (
            LeftOut(duplicates=1),
            "Left out of this verdict: 1 duplicate. mailvigil summary shows why.",
        ),
        (
            LeftOut(other_domain=1),
            "Left out of this verdict: 1 report of another domain. mailvigil summary shows why.",
        ),
        (
            LeftOut(other_domain=3),
            "Left out of this verdict: 3 reports of other domains. mailvigil summary shows why.",
        ),
        (
            LeftOut(skipped=2, duplicates=1, other_domain=3),
            "Left out of this verdict: 2 files skipped, 1 duplicate, 3 reports of other domains. "
            "mailvigil summary shows why.",
        ),
    ],
)
def test_the_left_out_sentence_names_only_the_parts_above_zero(
    left_out: LeftOut, expected: str
) -> None:
    """Each part has its own singular and plural, and a part at zero is left out of the line."""
    assert _left_out_text(_with_left_out(left_out)) == expected


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"days": 10},
        {"sources": (known(3),)},
        {"sources": (other(500),)},
        {"days": 0},
    ],
)
def test_the_line_sits_between_the_next_step_and_the_caveat_for_every_answer(
    kwargs: dict[str, Any],
) -> None:
    """READY, TOO EARLY and NOT READY all show it, always just before the closing sentence."""
    verdict = _with_left_out(LeftOut(skipped=1), **kwargs)
    paragraphs = render_verdict(verdict).split("\n\n")

    assert flat(paragraphs[-1]) == _CAVEAT
    assert paragraphs[-2].startswith("Left out of this verdict")
    if verdict.deciding is not None:
        assert paragraphs[-3].startswith("Next:")


def test_the_line_never_names_a_file() -> None:
    """File names stay in ``summary``, where the reasons are."""
    text = render_verdict(_with_left_out(LeftOut(skipped=4, duplicates=2, other_domain=1)))
    assert ".xml" not in text
    assert ".zip" not in text
    assert ".gz" not in text


def test_the_line_fits_80_columns_with_huge_counts() -> None:
    """Counts of ``10**12`` wrap instead of overflowing the screen."""
    huge = 10**12
    verdict = _with_left_out(LeftOut(skipped=huge, duplicates=huge, other_domain=huge))
    assert all(len(line) <= 80 for line in lines_of(verdict))
    assert all(ord(ch) < 128 for ch in render_verdict(verdict))
    assert str(huge) in _left_out_text(verdict)


# ---------------------------------------------------------------------------
# The text is pinned, whole, in both languages (008 RNF-05, ADR-2)
# ---------------------------------------------------------------------------


def _all_notes() -> Verdict:
    """Judge a clean verdict and attach one note of every kind."""
    notes = (
        Note(NoteKind.FRAGILE, numbers=(120, 80, 2000)),
        Note(NoteKind.PARTIAL_POLICY, numbers=(50,)),
        Note(NoteKind.POLICY_CHANGED, texts=("none", "quarantine")),
        Note(NoteKind.SUBDOMAIN_POLICY, texts=("none", "reject")),
        Note(NoteKind.CURRENTLY_QUARANTINE),
    )
    return dataclasses.replace(make_verdict(p="quarantine"), notes=notes)


def _many_recognized() -> Verdict:
    """Twelve failing sources of recognized senders: two more than the text prints."""
    sources = tuple(
        known(40 - number, service=f"Example Mailer {number}", ip=f"192.0.2.{number}")
        for number in range(1, 13)
    )
    return make_verdict(sources=sources)


# The verdicts whose whole text is recorded below. The refactor of 008 stage 1 must leave every
# one byte for byte as it was, in English and in Brazilian Portuguese.
PINNED_CASES: dict[str, Callable[[], Verdict]] = {
    "ready": make_verdict,
    "ready_still_failing": lambda: make_verdict(sources=(other(5, selectors=("s1",)),)),
    "ready_enforcing": lambda: make_verdict(p="reject"),
    "too_early_no_report": lambda: make_verdict(days=0),
    "too_early_missing": lambda: make_verdict(days=10, with_reports=8, ok=50),
    "recognized_one": lambda: make_verdict(sources=(known(30),)),
    "recognized_overrides": lambda: make_verdict(
        sources=(known(30, override_reasons=("forwarded", "mailing_list")),)
    ),
    "recognized_several": lambda: make_verdict(
        sources=(known(30), known(20, service="Example Mail Two", ip="192.0.2.11"))
    ),
    "recognized_over_limit": _many_recognized,
    "unrecognized_at_limit": lambda: make_verdict(ok=29840, sources=(other(160),)),
    "unrecognized_over_limit": lambda: make_verdict(
        ok=2000,
        sources=tuple(other(20 - number, number) for number in range(1, 8)),
    ),
    "all_notes": _all_notes,
    "left_out": lambda: _with_left_out(LeftOut(skipped=2, duplicates=1, other_domain=3)),
}


@pytest.mark.parametrize("case", sorted(PINNED_CASES))
@pytest.mark.parametrize(("code", "messages"), [("en", ENGLISH), ("pt-BR", PORTUGUESE)])
def test_the_text_of_a_fixed_verdict_is_recorded_whole(
    case: str, code: str, messages: Messages
) -> None:
    """The guard of the 008 refactor: words and layout stay what they were, byte for byte."""
    text = render_verdict(PINNED_CASES[case](), messages)

    assert tuple(text.split("\n")) == GOLDEN[case][code]


# ---------------------------------------------------------------------------
# The sentences the HTML report shares with the text (008 RF-02, ADR-2)
# ---------------------------------------------------------------------------


def test_the_reason_sentence_for_each_of_the_five_cases() -> None:
    """The sentence comes without its label, so the page can place it where it wants."""
    cases = [
        (make_verdict(), "every rule passes."),
        (make_verdict(days=10, with_reports=8, ok=50), "not enough reports to tell yet."),
        (make_verdict(days=0), "not enough reports to tell yet."),
        (make_verdict(sources=(known(30),)), "a recognized sender fails DMARC."),
        (
            make_verdict(ok=29840, sources=(other(160),)),
            "failures from unrecognized sources are >0.5% of the messages (160 of 30000); "
            "the limit is 0.5%.",
        ),
    ]

    for verdict, sentence in cases:
        assert reason_sentence(verdict, ENGLISH) == sentence


def test_the_reason_sentence_is_what_the_text_prints_after_the_label() -> None:
    """Both renderers read the same sentence, so they cannot drift."""
    for build in PINNED_CASES.values():
        verdict = build()
        for messages in (ENGLISH, PORTUGUESE):
            label = messages.verdict.why_label
            first = flat(render_verdict(verdict, messages).split("\n\n")[1])
            assert first.startswith(f"{label} {flat(reason_sentence(verdict, messages))}")


def test_the_next_sentence_is_empty_when_ready_and_one_sentence_otherwise() -> None:
    """Nothing is left to do for a ready verdict; every other answer has one thing to do."""
    assert next_sentence(make_verdict(), ENGLISH) == ""
    for verdict in (
        make_verdict(days=0),
        make_verdict(sources=(known(30),)),
        make_verdict(ok=29840, sources=(other(160),)),
    ):
        sentence = next_sentence(verdict, ENGLISH)
        assert sentence
        assert not sentence.startswith("Next")
        assert "\n" not in sentence


@pytest.mark.parametrize(
    ("messages", "above", "below"),
    [(ENGLISH, "above", "below"), (PORTUGUESE, "acima", "abaixo")],
    ids=["en", "pt-BR"],
)
def test_the_next_sentence_points_below_on_the_page_and_above_in_the_text(
    messages: Messages, above: str, below: str
) -> None:
    """The text prints the sources before the next step and the page prints them after it."""
    pointing = (
        make_verdict(ok=29840, sources=(other(160),)),
        make_verdict(sources=(known(30), known(20, service="Example Campaigns", ip="192.0.2.11"))),
    )
    for verdict in pointing:
        assert above in next_sentence(verdict, messages)
        assert below not in next_sentence(verdict, messages)
        assert below in next_sentence(verdict, messages, on_page=True)
        assert above not in next_sentence(verdict, messages, on_page=True)
    # The other sentences do not say where the sources are, so the page repeats the text.
    for verdict in (make_verdict(days=0), make_verdict(sources=(known(30),)), make_verdict()):
        assert next_sentence(verdict, messages, on_page=True) == next_sentence(verdict, messages)


def test_measured_needed_and_missing_text_for_each_rule() -> None:
    """The figures of the rules table, one rule at a time, are public."""
    verdict = make_verdict(days=10, with_reports=8, ok=50, sources=(other(1),))
    by_id = {rule.id: rule for rule in verdict.rules}

    assert measured_text(by_id[RuleId.PERIOD], ENGLISH) == "10 days"
    assert measured_text(by_id[RuleId.COVERAGE], ENGLISH) == "8 of 10 (80.0%)"
    assert measured_text(by_id[RuleId.VOLUME], ENGLISH) == "51"
    assert measured_text(by_id[RuleId.RECOGNIZED_FAILURES], ENGLISH) == "0"
    assert measured_text(by_id[RuleId.UNRECOGNIZED_FAILURES], ENGLISH) == "1 (2.0%)"
    assert needed_text(by_id[RuleId.PERIOD]) == f">= {MIN_DAYS_SPANNED}"
    assert needed_text(by_id[RuleId.COVERAGE]) == f">= {MIN_COVERAGE_PERCENT}%"
    assert needed_text(by_id[RuleId.VOLUME]) == f">= {MIN_MESSAGES}"
    assert needed_text(by_id[RuleId.RECOGNIZED_FAILURES]) == "<= 0"
    assert needed_text(by_id[RuleId.UNRECOGNIZED_FAILURES]) == "<= 0.5%"
    assert missing_text(by_id[RuleId.PERIOD], ENGLISH) == "need 18 more days"
    assert missing_text(by_id[RuleId.VOLUME], ENGLISH) == "need 49 more messages"


@pytest.mark.parametrize("messages", [ENGLISH, PORTUGUESE])
def test_the_sentence_of_every_kind_of_note_is_filled(messages: Messages) -> None:
    """The test iterates ``NoteKind``: a kind added later cannot reach the page as a bare key."""
    for kind in NoteKind:
        note = Note(kind, numbers=(1, 2, 3), texts=("a", "b"))
        sentence = note_sentence(note, messages)

        assert sentence
        assert "{" not in sentence
        assert str(kind) not in sentence
