"""
Tests of the verdict rules: the five rules, the answer they give, the sources and the notes.

Isolation: nothing touches the disk and no command runs, except one child interpreter that checks
the imports of the module. ``Summary`` values are built in the test with ``make_summary``, whose
defaults are a clean, long, busy domain, so each test states only what it changes. Domains, services
and addresses are invented (``example.com``, ``example.net``; ``192.0.2.0/24``, ``198.51.100.0/24``;
RNF-06).
"""

from __future__ import annotations

import dataclasses
import subprocess
import sys
from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime, timedelta
from itertools import permutations, product
from pathlib import Path
from types import MappingProxyType

import pytest

from mailvigil import verdict as verdict_module
from mailvigil.config import Config
from mailvigil.reports import (
    IngestionResult,
    PolicyPublished,
    Reason,
    Record,
    Report,
    SkippedFile,
)
from mailvigil.senders import Outcome
from mailvigil.summary import (
    Counts,
    FailingSource,
    Period,
    ReporterActivity,
    Summary,
    WithoutReporter,
    summarize,
)
from mailvigil.verdict import (
    MAX_UNRECOGNIZED_PER_MILLE,
    MIN_COVERAGE_PERCENT,
    MIN_DAYS_SPANNED,
    MIN_MESSAGES,
    SILENT_AFTER,
    STALE_AFTER,
    Answer,
    LeftOut,
    Note,
    NoteKind,
    Rule,
    RuleId,
    RuleKind,
    Verdict,
    judge,
    worst_answer,
)

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

# A fixed first day and documentation-range addresses, so no real report enters the tests (RNF-06).
_FIRST_DAY = date(2026, 9, 1)
_KNOWN_IP = "192.0.2.10"
_OTHER_IP = "198.51.100.7"


def make_summary(
    *,
    days: int = 28,
    with_reports: int | None = None,
    ok: int = 2000,
    dkim_only: int = 0,
    spf_only: int = 0,
    recognized_failing: int = 0,
    unrecognized_failing: int = 0,
    sources: tuple[FailingSource, ...] | None = None,
    p: str = "none",
    pct: int = 100,
    sp: str = "",
    np: str = "",
    earlier_p: tuple[str, ...] = (),
    skipped: int = 0,
    duplicates: int = 0,
    other_domain: int = 0,
    reporter_activity: tuple[ReporterActivity, ...] = (),
) -> Summary:
    """
    Build a ``Summary`` of ``example.com`` whose figures agree with each other.

    Args:
        days (int, optional): The days the reports span; 0 builds a summary without reports.
            Default: 28.
        with_reports (int | None, optional): The days with a report. Default: ``days``.
        ok (int, optional): Messages where DKIM and SPF passed. Default: 2000.
        dkim_only (int, optional): Fragile messages where only DKIM passed. Default: 0.
        spf_only (int, optional): Fragile messages where only SPF passed. Default: 0.
        recognized_failing (int, optional): Failing messages of one recognized source. Default: 0.
        unrecognized_failing (int, optional): Failing messages of one unrecognized source.
            Default: 0.
        sources (tuple[FailingSource, ...] | None, optional): The failing sources, replacing the
            two above; the failing total is their sum. Default: built from the two above.
        p (str, optional): The latest published ``p``. Default: ``none``.
        pct (int, optional): The latest published ``pct``. Default: 100.
        sp (str, optional): The latest published ``sp``. Default: empty.
        np (str, optional): The latest published ``np``. Default: empty.
        earlier_p (tuple[str, ...], optional): The other ``p`` values seen. Default: none.
        skipped (int, optional): Files refused. Default: 0.
        duplicates (int, optional): Reports dropped as already seen. Default: 0.
        other_domain (int, optional): Reports of another domain. Default: 0.
        reporter_activity (tuple[ReporterActivity, ...], optional): What each reporter sent.
            Default: none.

    Returns:
        Summary: The summary.
    """
    left_out = {
        "skipped": tuple(
            SkippedFile(Path(f"bad{n}.xml"), Reason.MALFORMED_XML, "") for n in range(skipped)
        ),
        "duplicates": duplicates,
        "other_domain": other_domain,
    }
    if sources is None:
        built: list[FailingSource] = []
        if recognized_failing:
            built.append(
                FailingSource(Outcome.KNOWN, _KNOWN_IP, recognized_failing, "Example Mailer")
            )
        if unrecognized_failing:
            built.append(FailingSource(Outcome.UNKNOWN, _OTHER_IP, unrecognized_failing))
        sources = tuple(built)
    failing = sum(source.messages for source in sources)
    if days == 0:
        return Summary(domain="example.com", **left_out)
    begin = datetime.combine(_FIRST_DAY, datetime.min.time(), tzinfo=UTC)
    last_day = _FIRST_DAY + timedelta(days=days - 1)
    period = Period(
        begin=begin,
        end=begin + timedelta(days=days),
        first_day=_FIRST_DAY,
        last_day=last_day,
        days_spanned=days,
        days_with_reports=days if with_reports is None else with_reports,
    )
    return Summary(
        domain="example.com",
        reports=days,
        reporters=2,
        period=period,
        policy=PolicyPublished(domain="example.com", p=p, sp=sp, np=np, pct=pct),
        earlier_p=earlier_p,
        totals=Counts(ok=ok, dkim_only=dkim_only, spf_only=spf_only, failing=failing),
        failing=sources,
        reporter_activity=reporter_activity,
        **left_out,
    )


def rule(verdict: Verdict, rule_id: RuleId) -> Rule:
    """
    Pick one rule of a verdict.

    Args:
        verdict (Verdict): The verdict.
        rule_id (RuleId): The rule wanted.

    Returns:
        Rule: The rule with that id.
    """
    return verdict.rules[rule_id - 1]


def note_kinds(verdict: Verdict) -> list[NoteKind]:
    """
    List the kinds of the notes of a verdict, in order.

    Args:
        verdict (Verdict): The verdict.

    Returns:
        list[NoteKind]: The kinds.
    """
    return [note.kind for note in verdict.notes]


# ---------------------------------------------------------------------------
# The constants (RNF-05)
# ---------------------------------------------------------------------------


def test_the_thresholds_are_the_ones_of_the_requirements() -> None:
    """The four named constants hold the first proposal, in their documented units."""
    assert MIN_DAYS_SPANNED == 28
    assert MIN_COVERAGE_PERCENT == 80
    assert MIN_MESSAGES == 100
    assert MAX_UNRECOGNIZED_PER_MILLE == 5


def test_the_rules_are_always_the_five_in_id_order() -> None:
    """A verdict carries every rule, ids 1 to 5, whatever the data (RF-02)."""
    for summary in (make_summary(), make_summary(days=0), make_summary(recognized_failing=3)):
        verdict = judge(summary)
        assert [r.id for r in verdict.rules] == [1, 2, 3, 4, 5]
        assert [r.kind for r in verdict.rules] == [
            RuleKind.DATA,
            RuleKind.DATA,
            RuleKind.DATA,
            RuleKind.PROBLEM,
            RuleKind.PROBLEM,
        ]


# ---------------------------------------------------------------------------
# Each rule at its threshold and at the value beside it (RF-02)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("days", "passed"), [(28, True), (27, False), (29, True)])
def test_rule_1_period_needs_28_days_spanned(days: int, passed: bool) -> None:
    """The boundary passes ("at least"), and the value beside it does not."""
    result = rule(judge(make_summary(days=days)), RuleId.PERIOD)
    assert result.passed is passed
    assert (result.measured, result.needed, result.at_least) == (days, 28, True)
    assert result.missing == max(0, 28 - days)


@pytest.mark.parametrize(("with_reports", "passed"), [(23, True), (22, False), (28, True)])
def test_rule_2_coverage_needs_80_percent_of_the_days(with_reports: int, passed: bool) -> None:
    """23 of 28 days is 82.1% and passes; 22 of 28 is 78.6% and fails."""
    result = rule(judge(make_summary(days=28, with_reports=with_reports)), RuleId.COVERAGE)
    assert result.passed is passed
    assert (result.measured, result.whole, result.needed) == (with_reports, 28, 80)
    assert result.at_least is True


def test_rule_2_boundary_is_exact_where_a_float_would_not_be() -> None:
    """12 of 15 days is exactly 80%: integer arithmetic passes it, and 11 of 15 fails."""
    assert rule(judge(make_summary(days=15, with_reports=12)), RuleId.COVERAGE).passed
    assert not rule(judge(make_summary(days=15, with_reports=11)), RuleId.COVERAGE).passed


def test_rule_2_missing_days_round_up() -> None:
    """80% of 28 days is 22.4, so 23 are needed: 22 days lack 1 and 10 days lack 13."""
    assert rule(judge(make_summary(days=28, with_reports=22)), RuleId.COVERAGE).missing == 1
    assert rule(judge(make_summary(days=28, with_reports=10)), RuleId.COVERAGE).missing == 13
    assert rule(judge(make_summary(days=28, with_reports=23)), RuleId.COVERAGE).missing == 0


@pytest.mark.parametrize(("messages", "passed"), [(100, True), (99, False), (101, True)])
def test_rule_3_volume_needs_100_messages(messages: int, passed: bool) -> None:
    """100 messages pass and 99 do not; the failing ones count in the total."""
    result = rule(judge(make_summary(ok=messages)), RuleId.VOLUME)
    assert result.passed is passed
    assert (result.measured, result.needed) == (messages, 100)
    assert result.missing == max(0, 100 - messages)


def test_rule_3_counts_fragile_and_failing_messages_too() -> None:
    """The volume is every message, not only the ones that authenticated."""
    verdict = judge(make_summary(ok=400, dkim_only=300, spf_only=200, unrecognized_failing=100))
    assert rule(verdict, RuleId.VOLUME).measured == 1000
    assert rule(verdict, RuleId.VOLUME).passed


@pytest.mark.parametrize(("failing", "passed"), [(0, True), (1, False)])
def test_rule_4_one_failing_message_under_a_recognized_sender_fails(
    failing: int, passed: bool
) -> None:
    """Zero is the only passing value: a recognized service must not fail at all."""
    result = rule(judge(make_summary(recognized_failing=failing)), RuleId.RECOGNIZED_FAILURES)
    assert result.passed is passed
    assert (result.measured, result.needed, result.at_least) == (failing, 0, False)
    assert result.missing == 0


@pytest.mark.parametrize(("failing", "passed"), [(5000, True), (5001, False), (4999, True)])
def test_rule_5_unrecognized_failures_are_at_most_half_a_percent(
    failing: int, passed: bool
) -> None:
    """5000 of 1,000,000 messages is exactly 0.5% and passes; one more fails."""
    summary = make_summary(ok=1_000_000 - failing, unrecognized_failing=failing)
    result = rule(judge(summary), RuleId.UNRECOGNIZED_FAILURES)
    assert result.passed is passed
    assert (result.measured, result.whole, result.needed) == (failing, 1_000_000, 5)
    assert result.at_least is False
    assert result.missing == 0


def test_rule_5_ignores_the_failures_of_recognized_senders() -> None:
    """A recognized failure is rule 4's business: rule 5 sees only the unrecognized ones."""
    verdict = judge(make_summary(recognized_failing=900, unrecognized_failing=0))
    assert rule(verdict, RuleId.UNRECOGNIZED_FAILURES).measured == 0
    assert rule(verdict, RuleId.UNRECOGNIZED_FAILURES).passed


# ---------------------------------------------------------------------------
# The answers (RF-01, ADR-2)
# ---------------------------------------------------------------------------


def test_every_rule_passing_is_ready() -> None:
    """A long, busy, clean domain is ready, and no rule decides."""
    verdict = judge(make_summary())
    assert verdict.answer is Answer.READY
    assert verdict.deciding is None
    assert all(r.passed for r in verdict.rules)


def test_a_clean_table_with_a_short_window_is_too_early() -> None:
    """Nothing is wrong, but 27 days is not enough evidence yet."""
    verdict = judge(make_summary(days=27))
    assert verdict.answer is Answer.TOO_EARLY
    assert verdict.deciding is RuleId.PERIOD


def test_a_recognized_failure_with_a_short_window_is_not_ready() -> None:
    """A fact already seen beats a short window: more days will not make it pass (ADR-2)."""
    verdict = judge(make_summary(days=3, ok=50, recognized_failing=2))
    assert verdict.answer is Answer.NOT_READY
    assert verdict.deciding is RuleId.RECOGNIZED_FAILURES
    assert not rule(verdict, RuleId.PERIOD).passed


def test_unrecognized_failures_over_the_limit_are_not_ready() -> None:
    """Rule 5 alone decides when it is the only rule that fails."""
    verdict = judge(make_summary(ok=900, unrecognized_failing=100))
    assert verdict.answer is Answer.NOT_READY
    assert verdict.deciding is RuleId.UNRECOGNIZED_FAILURES


def test_both_problem_rules_failing_decide_on_the_first() -> None:
    """``deciding`` is the first failed rule of the kind that decided."""
    verdict = judge(make_summary(ok=900, recognized_failing=10, unrecognized_failing=90))
    assert verdict.answer is Answer.NOT_READY
    assert verdict.deciding is RuleId.RECOGNIZED_FAILURES


def test_several_data_rules_failing_decide_on_the_first() -> None:
    """Rules 1 and 3 fail: the period comes first."""
    verdict = judge(make_summary(days=10, ok=100))
    assert verdict.answer is Answer.TOO_EARLY
    assert verdict.deciding is RuleId.PERIOD


def test_a_failed_rule_of_each_kind_together_is_not_ready() -> None:
    """A data rule and a problem rule failing: the problem rule decides."""
    verdict = judge(make_summary(days=10, ok=100, unrecognized_failing=100))
    assert verdict.answer is Answer.NOT_READY
    assert verdict.deciding is RuleId.UNRECOGNIZED_FAILURES


# ---------------------------------------------------------------------------
# Empty input (RF-01, RF-02, ADR-4)
# ---------------------------------------------------------------------------


def test_a_summary_without_reports_is_too_early_without_dividing_by_zero() -> None:
    """Rules 1 to 3 fail, rule 5 passes on 0 <= 0 and the policy is empty."""
    verdict = judge(Summary(domain="example.com"))
    assert verdict.answer is Answer.TOO_EARLY
    assert verdict.deciding is RuleId.PERIOD
    assert [r.passed for r in verdict.rules] == [False, False, False, True, True]
    assert rule(verdict, RuleId.PERIOD).missing == 28
    assert rule(verdict, RuleId.VOLUME).missing == 100
    assert verdict.enforcing == ""
    assert verdict.notes == ()
    assert verdict.recognized_failing == verdict.unrecognized_failing == ()


def test_reports_with_zero_messages_are_too_early() -> None:
    """A long window with nothing in it fails the volume only, and rule 5 passes on 0 <= 0."""
    verdict = judge(make_summary(ok=0))
    assert verdict.answer is Answer.TOO_EARLY
    assert verdict.deciding is RuleId.VOLUME
    assert [r.passed for r in verdict.rules] == [True, True, False, True, True]
    assert rule(verdict, RuleId.VOLUME).missing == 100


def test_the_missing_amount_is_zero_for_a_problem_rule() -> None:
    """``missing`` is for data rules; a failed problem rule lacks nothing."""
    verdict = judge(make_summary(recognized_failing=5, unrecognized_failing=900, ok=100))
    assert rule(verdict, RuleId.RECOGNIZED_FAILURES).missing == 0
    assert rule(verdict, RuleId.UNRECOGNIZED_FAILURES).missing == 0


# ---------------------------------------------------------------------------
# The sources (RF-03, RF-02)
# ---------------------------------------------------------------------------


def test_the_failing_sources_are_split_by_outcome_and_keep_the_order() -> None:
    """``KNOWN`` is recognized; the other three outcomes are not (the order is 004's)."""
    sources = (
        FailingSource(Outcome.UNKNOWN, "198.51.100.1", 50),
        FailingSource(Outcome.KNOWN, "192.0.2.1", 40, "Example Mailer"),
        FailingSource(Outcome.FOREIGN_DOMAIN, "198.51.100.2", 30, selectors=("s1",)),
        FailingSource(Outcome.KNOWN, "192.0.2.2", 20, "Example Mail"),
        FailingSource(Outcome.FAILING_SIGNATURE, "198.51.100.3", 10, selectors=("s2",)),
    )
    verdict = judge(make_summary(sources=sources))
    assert verdict.recognized_failing == (sources[1], sources[3])
    assert verdict.unrecognized_failing == (sources[0], sources[2], sources[4])
    assert rule(verdict, RuleId.RECOGNIZED_FAILURES).measured == 60
    assert rule(verdict, RuleId.UNRECOGNIZED_FAILURES).measured == 90


def test_the_sources_are_filled_whatever_the_answer() -> None:
    """Both lists are there for a ``ready`` verdict too, so the text can mention them (ADR-3)."""
    verdict = judge(make_summary(unrecognized_failing=3))
    assert verdict.answer is Answer.READY
    assert [s.messages for s in verdict.unrecognized_failing] == [3]
    assert verdict.recognized_failing == ()


def test_a_known_source_whose_signature_passed_but_was_not_aligned_still_counts() -> None:
    """A recognized service that failed DMARC is a rule-4 failure, signed or not."""
    source = FailingSource(
        Outcome.KNOWN, "192.0.2.1", 7, "Example Mailer", dkim=("unaligned",), spf=("none",)
    )
    verdict = judge(make_summary(sources=(source,)))
    assert verdict.recognized_failing == (source,)
    assert not rule(verdict, RuleId.RECOGNIZED_FAILURES).passed


def test_the_two_failing_counts_add_up_to_the_failing_total() -> None:
    """Recognized plus unrecognized failing messages is ``totals.failing``."""
    summary = make_summary(recognized_failing=12, unrecognized_failing=30)
    verdict = judge(summary)
    measured = rule(verdict, RuleId.RECOGNIZED_FAILURES).measured
    measured += rule(verdict, RuleId.UNRECOGNIZED_FAILURES).measured
    assert measured == summary.totals.failing == 42


# ---------------------------------------------------------------------------
# The notes (RF-04)
# ---------------------------------------------------------------------------


def test_clean_traffic_has_no_notes() -> None:
    """A note appears only when it applies."""
    assert judge(make_summary()).notes == ()


def test_fragile_traffic_gives_the_numbers() -> None:
    """The note carries the fragile messages, how many are SPF-only, and the total."""
    verdict = judge(make_summary(ok=1500, dkim_only=100, spf_only=400))
    assert verdict.notes == (Note(NoteKind.FRAGILE, numbers=(500, 400, 2000)),)


def test_a_partial_policy_gives_a_note() -> None:
    """``pct`` below 100 means the policy applies to part of the mail only."""
    verdict = judge(make_summary(pct=50))
    assert verdict.notes == (Note(NoteKind.PARTIAL_POLICY, numbers=(50,)),)


def test_a_changed_policy_gives_the_earlier_values() -> None:
    """The note lists the earlier ``p`` values, oldest first."""
    verdict = judge(make_summary(p="quarantine", earlier_p=("none", "reject")))
    assert Note(NoteKind.POLICY_CHANGED, texts=("none", "reject")) in verdict.notes


@pytest.mark.parametrize(
    ("p", "sp", "np", "texts"),
    [
        ("reject", "none", "", ("none", "")),
        ("reject", "", "none", ("", "none")),
        ("none", "reject", "reject", ("reject", "reject")),
    ],
)
def test_a_subdomain_policy_that_differs_gives_a_note(
    p: str, sp: str, np: str, texts: tuple[str, str]
) -> None:
    """``sp`` or ``np`` different from ``p`` says what moving ``p`` will not change."""
    verdict = judge(make_summary(p=p, sp=sp, np=np))
    assert Note(NoteKind.SUBDOMAIN_POLICY, texts=texts) in verdict.notes


@pytest.mark.parametrize(("sp", "np"), [("", ""), ("none", ""), ("", "none"), ("NONE", " none ")])
def test_a_subdomain_policy_equal_to_p_or_absent_gives_no_note(sp: str, np: str) -> None:
    """Absent is not different, and the comparison ignores case and spaces."""
    summary = make_summary(p="none", sp=sp, np=np)
    assert NoteKind.SUBDOMAIN_POLICY not in note_kinds(judge(summary))


def test_quarantine_gives_its_note() -> None:
    """The current policy is named, because the question is still about ``reject``."""
    verdict = judge(make_summary(p="quarantine"))
    assert verdict.notes == (Note(NoteKind.CURRENTLY_QUARANTINE),)


def test_several_notes_come_in_the_order_of_note_kind() -> None:
    """The order is the declaration order of ``NoteKind``, not the order they were found."""
    verdict = judge(
        make_summary(
            p="quarantine",
            sp="none",
            pct=25,
            earlier_p=("none",),
            ok=1900,
            spf_only=100,
        )
    )
    assert note_kinds(verdict) == [
        kind
        for kind in NoteKind
        if kind not in (NoteKind.SILENT_REPORTER, NoteKind.REPORTER_RELIANCE, NoteKind.STALE)
    ]


def test_a_report_older_than_two_weeks_adds_the_stale_note() -> None:
    """The latest report ended 20 days before the run: the note says 20, the answer is unchanged."""
    summary = make_summary()
    assert summary.period is not None
    now = summary.period.end + timedelta(days=20)

    verdict = judge(summary, now)

    assert verdict.notes == (Note(NoteKind.STALE, numbers=(20,)),)
    assert verdict.answer is judge(summary).answer


def test_the_stale_note_needs_more_than_the_limit_and_a_clock() -> None:
    """Exactly fourteen days is not stale, and without a clock there is nothing to compare."""
    summary = make_summary()
    assert summary.period is not None

    assert not judge(summary, summary.period.end + STALE_AFTER).notes
    assert NoteKind.STALE in note_kinds(
        judge(summary, summary.period.end + STALE_AFTER + timedelta(seconds=1))
    )
    assert not judge(summary).notes
    assert not judge(make_summary(days=0), summary.period.end + timedelta(days=99)).notes


def _activity(summary: Summary, *reporters: tuple[str, int, timedelta]) -> Summary:
    """
    Give a summary reporters that went quiet this long before the latest report ended.

    Args:
        summary (Summary): The summary, with a period.
        *reporters (tuple[str, int, timedelta]): The name, the messages and how long before the end
            of the period the latest report of each reporter ended.

    Returns:
        Summary: The same summary with those reporters in ``reporter_activity``.
    """
    assert summary.period is not None
    seen = tuple(
        ReporterActivity(name, messages, summary.period.end - silent)
        for name, messages, silent in reporters
    )
    return dataclasses.replace(summary, reporter_activity=seen)


def test_a_large_reporter_silent_for_over_a_week_adds_the_note_for_the_largest() -> None:
    """Two reporters stopped; the note names the one with most messages, in whole days."""
    summary = _activity(
        make_summary(),
        ("big.example.net", 1200, timedelta(days=10, hours=3)),
        ("mid.example.org", 400, timedelta(days=20)),
        ("live.example.com", 400, timedelta(0)),
    )

    verdict = judge(summary)

    assert verdict.notes == (
        Note(NoteKind.SILENT_REPORTER, numbers=(10, 1200, 2000), texts=("big.example.net",)),
    )
    assert verdict.answer is judge(make_summary()).answer


@pytest.mark.parametrize(
    ("messages", "silent"),
    [(1200, SILENT_AFTER), (199, timedelta(days=30)), (0, timedelta(days=30))],
    ids=["silent exactly a week", "under a tenth of the messages", "no messages"],
)
def test_a_quiet_reporter_below_the_limits_adds_no_note(messages: int, silent: timedelta) -> None:
    """A week is allowed, and a reporter with under a tenth of the messages is not worth a line."""
    summary = _activity(make_summary(), ("some.example.net", messages, silent))

    assert NoteKind.SILENT_REPORTER not in note_kinds(judge(summary))


def test_no_note_changes_the_answer() -> None:
    """Every note at once, and the verdict is still ready."""
    verdict = judge(
        make_summary(p="quarantine", sp="none", pct=25, earlier_p=("none",), spf_only=100)
    )
    assert len(verdict.notes) == 5
    assert verdict.answer is Answer.READY


# ---------------------------------------------------------------------------
# The policy (RF-05)
# ---------------------------------------------------------------------------


def test_enforcing_is_lower_case_and_trimmed() -> None:
    """The published ``p`` is normalized once, and comparisons use that value."""
    assert judge(make_summary(p=" REJECT ")).enforcing == "reject"
    assert judge(make_summary(p="Quarantine")).enforcing == "quarantine"


def test_quarantine_is_found_whatever_its_spelling() -> None:
    """The note follows the normalized value."""
    assert NoteKind.CURRENTLY_QUARANTINE in note_kinds(judge(make_summary(p=" QUARANTINE ")))


@pytest.mark.parametrize("p", ["?", "none", "reject"])
def test_the_policy_does_not_change_the_answer_or_the_rules(p: str) -> None:
    """The same traffic gets the same rules and answer under any policy (ADR-7)."""
    baseline = judge(make_summary(p="none", recognized_failing=4))
    verdict = judge(make_summary(p=p, recognized_failing=4))
    assert verdict.answer is baseline.answer
    assert verdict.rules == baseline.rules
    assert verdict.notes == ()


def test_an_unknown_policy_is_neither_reject_nor_quarantine() -> None:
    """``?`` (a report that does not say) gives no note and is not enforcing."""
    verdict = judge(make_summary(p="?"))
    assert verdict.enforcing == "?"
    assert verdict.notes == ()


# ---------------------------------------------------------------------------
# Properties (RNF-02, RNF-03, RNF-04)
# ---------------------------------------------------------------------------


def _record(ip: str, count: int, dkim: str, spf: str) -> Record:
    """
    Build one record of ``example.com``.

    Args:
        ip (str): The source address.
        count (int): The messages.
        dkim (str): ``policy_evaluated/dkim``.
        spf (str): ``policy_evaluated/spf``.

    Returns:
        Record: The record, with no raw blocks.
    """
    return Record(
        source_ip=ip,
        count=count,
        disposition="none",
        dkim_evaluated=dkim,
        spf_evaluated=spf,
        override_reasons=(),
        header_from="example.com",
        dkim=(),
        spf=(),
    )


def _report(
    report_id: str,
    day: int,
    *records: Record,
    p: str = "none",
    reporter: str = "reporter.example.net",
) -> Report:
    """
    Build one daily report of ``example.com``.

    Args:
        report_id (str): The id the reporter gave it.
        day (int): The day of October 2026 it starts on.
        *records (Record): Its rows.
        p (str, optional): The ``p`` it publishes. Default: ``none``.
        reporter (str, optional): The organization that sent it. Default:
            ``reporter.example.net``.

    Returns:
        Report: The report.
    """
    begin = datetime(2026, 10, day, tzinfo=UTC)
    return Report(
        reporter=reporter,
        report_id=report_id,
        begin=begin,
        end=begin + timedelta(days=1),
        policy=PolicyPublished(domain="example.com", p=p),
        records=records,
        source_file=f"report-{report_id}.xml",
    )


def test_the_same_summary_judged_twice_gives_equal_verdicts() -> None:
    """Nothing depends on the clock, the locale or the file system (RNF-02)."""
    summary = make_summary(recognized_failing=3, unrecognized_failing=20, spf_only=10)
    assert judge(summary) == judge(summary)


def test_the_order_of_the_reports_does_not_change_the_verdict() -> None:
    """``summarize`` neutralizes the order, so every order of the reports judges the same."""
    reports = (
        _report("a", 1, _record("192.0.2.1", 600, "pass", "pass"), p="none"),
        _report("b", 2, _record("198.51.100.1", 5, "fail", "fail"), p="quarantine"),
        _report("c", 3, _record("203.0.113.1", 450, "pass", "fail"), p="reject"),
    )
    config = Config("example.com", MappingProxyType({}))
    verdicts = {
        judge(summarize(IngestionResult(reports=order), config)) for order in permutations(reports)
    }
    assert len(verdicts) == 1


def test_the_verdict_and_its_parts_are_frozen_and_hold_only_tuples() -> None:
    """Assigning raises, and every collection is a tuple (RNF-04)."""
    verdict = judge(make_summary(recognized_failing=3, p="quarantine", spf_only=10))
    for value, field in (
        (verdict, "answer"),
        (verdict.rules[0], "passed"),
        (verdict.notes[0], "numbers"),
    ):
        with pytest.raises(FrozenInstanceError):
            setattr(value, field, None)
    for part in (verdict, *verdict.rules, *verdict.notes):
        for item in dataclasses.fields(part):
            assert not isinstance(getattr(part, item.name), (list, dict, set))
    assert isinstance(verdict.rules, tuple)
    assert isinstance(verdict.notes, tuple)
    assert isinstance(verdict.recognized_failing, tuple)
    assert isinstance(verdict.unrecognized_failing, tuple)


def test_the_answer_and_kind_words_are_the_stable_strings() -> None:
    """The words are what a later ``--json`` will carry."""
    assert [a.value for a in Answer] == ["ready", "too_early", "not_ready"]
    assert [k.value for k in RuleKind] == ["data", "problem"]
    assert [n.value for n in NoteKind] == [
        "fragile",
        "partial_policy",
        "policy_changed",
        "subdomain_policy",
        "currently_quarantine",
        "silent_reporter",
        "reporter_reliance",
        "stale",
    ]


def test_the_verdict_module_imports_no_text_module() -> None:
    """Importing ``mailvigil.verdict`` must not pull in any ``render*`` module (RNF-03)."""
    code = (
        "import sys, mailvigil.verdict; "
        "bad = [m for m in sys.modules if m.startswith('mailvigil.render')]; "
        "sys.exit(1 if bad else 0)"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, check=False)
    assert result.returncode == 0, result.stderr.decode()


# ---------------------------------------------------------------------------
# What was left out (RF-09, ADR-9)
# ---------------------------------------------------------------------------


def test_nothing_left_out_gives_an_empty_left_out() -> None:
    """A verdict built from a clean summary counts nothing as left out."""
    assert judge(make_summary()).left_out == LeftOut(0, 0, 0)


def test_the_three_counts_are_copied_from_the_summary() -> None:
    """Skipped files, duplicates and reports of another domain keep their own figure."""
    verdict = judge(make_summary(skipped=2, duplicates=3, other_domain=4))
    assert verdict.left_out == LeftOut(skipped=2, duplicates=3, other_domain=4)


def test_a_summary_without_reports_still_carries_what_was_left_out() -> None:
    """The refused files matter most when nothing else was kept."""
    verdict = judge(make_summary(days=0, skipped=1, duplicates=1, other_domain=1))
    assert verdict.left_out == LeftOut(1, 1, 1)


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"days": 10},
        {"recognized_failing": 3},
        {"unrecognized_failing": 500},
        {"days": 0},
    ],
)
def test_what_was_left_out_changes_neither_the_answer_nor_the_rules(
    kwargs: dict[str, int],
) -> None:
    """A refused file is not a failing message: the rules and the answer ignore it."""
    plain = judge(make_summary(**kwargs))
    left = judge(make_summary(**kwargs, skipped=5, duplicates=2, other_domain=1))
    assert dataclasses.replace(left, left_out=LeftOut()) == plain


def test_a_ready_verdict_stays_ready_with_skipped_files() -> None:
    """The line is a prompt to look, not a block (ADR-9)."""
    verdict = judge(make_summary(skipped=3))
    assert verdict.answer is Answer.READY
    assert verdict.deciding is None


def test_left_out_is_frozen_and_a_hand_built_verdict_need_not_pass_one() -> None:
    """``LeftOut`` cannot be assigned to, and ``Verdict.left_out`` has a default of nothing."""
    left_out = LeftOut(1, 2, 3)
    with pytest.raises(FrozenInstanceError):
        left_out.skipped = 9  # type: ignore[misc]
    assert LeftOut() == LeftOut(0, 0, 0)
    verdict = judge(make_summary())
    hand_built = Verdict(
        domain=verdict.domain,
        answer=verdict.answer,
        enforcing=verdict.enforcing,
        rules=verdict.rules,
        deciding=verdict.deciding,
        recognized_failing=verdict.recognized_failing,
        unrecognized_failing=verdict.unrecognized_failing,
        notes=verdict.notes,
    )
    assert hand_built.left_out == LeftOut()


# ---------------------------------------------------------------------------
# The worst answer of several domains (spec 010, RF-06, ADR-6)
# ---------------------------------------------------------------------------


def _answering(answer: Answer) -> Verdict:
    """Build a verdict that carries the answer, whatever its rules say: only the answer is read."""
    return dataclasses.replace(judge(make_summary()), answer=answer)


@pytest.mark.parametrize(
    "answers", [mix for size in (1, 2, 3) for mix in product(Answer, repeat=size)]
)
def test_the_worst_answer_is_not_ready_then_too_early_then_ready(
    answers: tuple[Answer, ...],
) -> None:
    """Every sequence of up to three answers gives the one the exit code ranks worst."""
    if Answer.NOT_READY in answers:
        expected = Answer.NOT_READY
    elif Answer.TOO_EARLY in answers:
        expected = Answer.TOO_EARLY
    else:
        expected = Answer.READY
    assert worst_answer(_answering(answer) for answer in answers) is expected


def test_the_worst_answer_of_one_verdict_is_its_own() -> None:
    for answer in Answer:
        assert worst_answer([_answering(answer)]) is answer


def test_the_worst_answer_of_nothing_is_a_callers_mistake() -> None:
    with pytest.raises(ValueError, match="at least one"):
        worst_answer([])


# ---------------------------------------------------------------------------
# The reporter-reliance note (spec 011, RF-01, RF-02, RF-04, RNF-03, ADR-1, ADR-4)
# ---------------------------------------------------------------------------


def _resting(summary: Summary, *entries: WithoutReporter) -> Summary:
    """
    Give a summary its measures without each organization, one entry per organization.

    Args:
        summary (Summary): The summary.
        *entries (WithoutReporter): The entries, in the order of ``reporter_activity``.

    Returns:
        Summary: The same summary with those entries, and as many organizations as entries.
    """
    return dataclasses.replace(summary, without_reporter=entries, reporters=len(entries))


def _without(
    name: str,
    messages: int,
    *,
    days: int = 28,
    with_reports: int | None = None,
    total: int | None = None,
    unrecognized: int = 0,
) -> WithoutReporter:
    """
    Build the measures of a run of 2000 clean messages without one organization's reports.

    Args:
        name (str): The organization.
        messages (int): Its own messages.
        days (int, optional): The days the other reports span. Default: 28.
        with_reports (int | None, optional): The days they cover. Default: ``days``.
        total (int | None, optional): Their messages. Default: 2000 minus ``messages``.
        unrecognized (int, optional): Their unrecognized failing messages. Default: 0.

    Returns:
        WithoutReporter: The entry; no failure under a recognized sender, as on a ``ready`` run.
    """
    return WithoutReporter(
        name=name,
        messages=messages,
        days_spanned=days,
        days_with_reports=days if with_reports is None else with_reports,
        total=2000 - messages if total is None else total,
        recognized_failing=0,
        unrecognized_failing=unrecognized,
    )


def _reliance(verdict: Verdict) -> list[Note]:
    """
    Pick the reporter-reliance notes of a verdict.

    Args:
        verdict (Verdict): The verdict.

    Returns:
        list[Note]: Those notes; at most one.
    """
    return [note for note in verdict.notes if note.kind is NoteKind.REPORTER_RELIANCE]


# Each rule that can turn a ``ready``: without the larger organization, one rule fails; without the
# smaller, the answer is still ``ready``. The run is 2000 clean messages over 28 days.
_TURNING = {
    "period": (
        make_summary(),
        _without("big.example.net", 1500, days=20),
        Note(
            NoteKind.REPORTER_RELIANCE,
            (1500, 2000, 2, 1),
            ("big.example.net", "too_early"),
        ),
    ),
    "coverage": (
        make_summary(),
        _without("big.example.net", 1500, with_reports=22),
        Note(
            NoteKind.REPORTER_RELIANCE,
            (1500, 2000, 2, 2),
            ("big.example.net", "too_early"),
        ),
    ),
    "volume": (
        make_summary(),
        _without("big.example.net", 1901),
        Note(
            NoteKind.REPORTER_RELIANCE,
            (1901, 2000, 2, 3),
            ("big.example.net", "too_early"),
        ),
    ),
    # why: 10 unrecognized failures are within half a percent of 2010 messages, and over it of the
    # 110 left without the clean organization.
    "unrecognized share": (
        make_summary(unrecognized_failing=10),
        _without("big.example.net", 1900, total=110, unrecognized=10),
        Note(
            NoteKind.REPORTER_RELIANCE,
            (1900, 2010, 2, 5),
            ("big.example.net", "not_ready"),
        ),
    ),
}


@pytest.mark.parametrize(("summary", "turning", "expected"), _TURNING.values(), ids=_TURNING)
def test_a_ready_answer_resting_on_one_organization_gives_the_note(
    summary: Summary, turning: WithoutReporter, expected: Note
) -> None:
    """Without the organization one rule fails: the note gives its figures and that rule."""
    other = _without(
        "small.example.org",
        summary.totals.total - turning.messages,
        total=turning.messages,
    )
    assert judge(summary).answer is Answer.READY

    verdict = judge(_resting(summary, turning, other))

    assert _reliance(verdict) == [expected]
    assert verdict.answer is Answer.READY


def test_the_walk_goes_past_an_organization_the_answer_does_not_rest_on() -> None:
    """The larger organization changes nothing; the smaller completes the coverage."""
    summary = _resting(
        make_summary(),
        _without("big.example.net", 1800),
        _without("small.example.org", 200, with_reports=20, total=1800),
    )

    assert _reliance(judge(summary)) == [
        Note(
            NoteKind.REPORTER_RELIANCE,
            (200, 2000, 2, 2),
            ("small.example.org", "too_early"),
        )
    ]


def test_the_largest_of_two_organizations_the_answer_rests_on_is_named() -> None:
    """Both qualify; only the first, the one with most messages, gets the note (ADR-4)."""
    summary = _resting(
        make_summary(),
        _without("big.example.net", 1500, days=20),
        _without("small.example.org", 500, with_reports=20),
    )

    notes = _reliance(judge(summary))

    assert [note.texts[0] for note in notes] == ["big.example.net"]


def test_no_organization_the_answer_rests_on_gives_no_note() -> None:
    """Each organization alone still passes the five rules."""
    summary = _resting(
        make_summary(),
        _without("big.example.net", 1000),
        _without("small.example.org", 1000),
    )

    assert _reliance(judge(summary)) == []


@pytest.mark.parametrize(
    "summary",
    [make_summary(days=20), make_summary(recognized_failing=1), make_summary(days=0)],
    ids=["too early", "not ready", "no reports"],
)
def test_the_note_is_only_for_a_ready_answer(summary: Summary) -> None:
    """``too early`` and ``not ready`` keep the policy as it is, so no note qualifies them."""
    resting = _resting(summary, _without("big.example.net", 1500, days=5))

    assert judge(resting).answer is not Answer.READY
    assert _reliance(judge(resting)) == []


def test_the_note_comes_between_the_silent_reporter_and_the_stale_note() -> None:
    """The order of ``NoteKind``: the two reporter notes side by side."""
    summary = _activity(
        _resting(
            make_summary(),
            _without("big.example.net", 1500, days=20),
            _without("small.example.org", 500),
        ),
        ("big.example.net", 1500, timedelta(days=10)),
        ("small.example.org", 500, timedelta(0)),
    )
    assert summary.period is not None

    verdict = judge(summary, summary.period.end + STALE_AFTER + timedelta(days=1))

    assert note_kinds(verdict) == [
        NoteKind.SILENT_REPORTER,
        NoteKind.REPORTER_RELIANCE,
        NoteKind.STALE,
    ]


def _run(*reports: Report) -> Summary:
    """
    Summarize built reports of ``example.com`` with no sender configured.

    Args:
        *reports (Report): The reports.

    Returns:
        Summary: Their summary.
    """
    config = Config("example.com", MappingProxyType({}))
    return summarize(IngestionResult(reports=reports), config)


def _days(reporter: str, first: int, last: int, count: int) -> list[Report]:
    """
    Build one clean daily report per day of October 2026 from one organization.

    Args:
        reporter (str): The organization.
        first (int): The first day.
        last (int): The last day, included.
        count (int): The messages of each report.

    Returns:
        list[Report]: The reports.
    """
    return [
        _report(
            f"{reporter}-{day}",
            day,
            _record(_OTHER_IP, count, "pass", "pass"),
            reporter=reporter,
        )
        for day in range(first, last + 1)
    ]


def test_a_run_from_one_organization_rests_on_it_alone() -> None:
    """Without its reports there are none: the period fails first, and the count is one."""
    summary = _run(*_days("only.example.net", 1, 28, 10))

    verdict = judge(summary)

    assert verdict.answer is Answer.READY
    assert _reliance(verdict) == [
        Note(
            NoteKind.REPORTER_RELIANCE,
            (280, 280, 1, 1),
            ("only.example.net", "too_early"),
        )
    ]


def test_from_the_summary_the_larger_organization_is_named_and_not_the_first_name() -> None:
    """Two halves of the period; both qualify and the one with most messages is named."""
    summary = _run(
        *_days("a-small.example.org", 1, 14, 10),
        *_days("z-big.example.net", 15, 28, 30),
    )

    assert _reliance(judge(summary)) == [
        Note(
            NoteKind.REPORTER_RELIANCE,
            (420, 560, 2, 1),
            ("z-big.example.net", "too_early"),
        )
    ]


def test_from_the_summary_a_tie_in_messages_is_decided_by_the_name() -> None:
    """Two halves with the same messages: the name first in order is the one named."""
    summary = _run(
        *_days("b.example.net", 1, 14, 10),
        *_days("a.example.org", 15, 28, 10),
    )

    assert _reliance(judge(summary)) == [
        Note(NoteKind.REPORTER_RELIANCE, (140, 280, 2, 1), ("a.example.org", "too_early"))
    ]


def test_from_the_summary_two_organizations_over_the_whole_period_give_no_note() -> None:
    summary = _run(
        *_days("a.example.org", 1, 28, 10),
        *_days("b.example.net", 1, 28, 10),
    )

    verdict = judge(summary)

    assert verdict.answer is Answer.READY
    assert _reliance(verdict) == []


def test_rule_4_cannot_turn_a_ready_answer() -> None:
    """A ready run has no recognized failure, and removing reports cannot add one."""
    for summary in (
        _run(*_days("only.example.net", 1, 28, 10)),
        _run(*_days("a.example.org", 1, 14, 10), *_days("b.example.net", 15, 28, 30)),
        _resting(make_summary(unrecognized_failing=10), _TURNING["unrecognized share"][1]),
    ):
        assert judge(summary).answer is Answer.READY
        assert rule(judge(summary), RuleId.RECOGNIZED_FAILURES).measured == 0
        assert summary.without_reporter
        for entry in summary.without_reporter:
            assert entry.recognized_failing == 0


def _without_note(verdict: Verdict) -> Verdict:
    """
    Drop the reporter-reliance note of a verdict, to compare the rest with a verdict without it.

    Args:
        verdict (Verdict): The verdict.

    Returns:
        Verdict: The same verdict without that note.
    """
    kept = tuple(note for note in verdict.notes if note.kind is not NoteKind.REPORTER_RELIANCE)
    return dataclasses.replace(verdict, notes=kept)


@pytest.mark.parametrize(
    "summary",
    [
        *(_resting(summary, turning) for summary, turning, _ in _TURNING.values()),
        _run(*_days("only.example.net", 1, 28, 10)),
        _run(*_days("a.example.org", 1, 14, 10), *_days("b.example.net", 15, 28, 30)),
        _resting(make_summary(days=20, skipped=2), _without("big.example.net", 1500, days=5)),
        _resting(
            make_summary(recognized_failing=3),
            _without("big.example.net", 1500, days=5),
        ),
    ],
)
def test_the_note_changes_nothing_else_of_the_verdict(summary: Summary) -> None:
    """Answer, deciding rule, rules, sources and what was left out are as without the entries."""
    without_entries = dataclasses.replace(summary, without_reporter=())

    verdict = judge(summary)

    assert _without_note(verdict) == judge(without_entries)


def test_a_threshold_of_the_verdict_moves_the_note_with_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The check reads the thresholds of ``verdict.py`` and no number of its own (RNF-03)."""
    rests_on_period = _resting(
        make_summary(),
        _without("big.example.net", 1500, days=20),
        _without("small.example.org", 500),
    )
    rests_on_nothing = _resting(
        make_summary(),
        _without("big.example.net", 1500),
        _without("small.example.org", 500),
    )
    assert _reliance(judge(rests_on_period))
    assert not _reliance(judge(rests_on_nothing))

    monkeypatch.setattr(verdict_module, "MIN_DAYS_SPANNED", 20)
    assert not _reliance(judge(rests_on_period))

    monkeypatch.setattr(verdict_module, "MIN_MESSAGES", 600)
    assert _reliance(judge(rests_on_nothing)) == [
        Note(
            NoteKind.REPORTER_RELIANCE,
            (1500, 2000, 2, 3),
            ("big.example.net", "too_early"),
        )
    ]
    assert judge(rests_on_nothing).answer is Answer.READY
