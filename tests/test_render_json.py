"""
Tests of the JSON documents: the keys and their order, the nulls, the complete lists and the
properties that make the output a contract (spec 006, RF-01 to RF-03).

Isolation: nothing touches the disk and no command runs. ``Summary`` and ``Verdict`` values are
built in the test with ``make_summary`` and ``make_verdict``, whose defaults are a clean, long,
busy domain, so each test states only what it changes. Domains, services and addresses are invented
(``example.com``, ``example.net``; ``192.0.2.0/24``, ``198.51.100.0/24``, ``203.0.113.0/24``;
RNF-06).
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime, timedelta
from itertools import permutations
from pathlib import Path
from types import MappingProxyType

import pytest

from mailvigil.config import Config
from mailvigil.fetch.model import FetchOutcome
from mailvigil.render_json import dumps, fetch_document, summary_document, verdict_document
from mailvigil.reports import (
    DkimResult,
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
    DayCounts,
    FailingSource,
    Period,
    SenderRow,
    Summary,
    summarize,
)
from mailvigil.verdict import Answer, Note, NoteKind, RuleId, Verdict, judge

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

_FIRST_DAY = datetime(2026, 9, 1, tzinfo=UTC)
_KNOWN_IP = "192.0.2.10"
_OTHER_IP = "198.51.100.7"


def make_summary(
    *,
    days: int = 28,
    with_reports: int | None = None,
    ok: int = 2000,
    dkim_only: int = 0,
    spf_only: int = 0,
    senders: tuple[SenderRow, ...] | None = None,
    failing: tuple[FailingSource, ...] = (),
    p: str = "none",
    sp: str = "",
    np: str = "",
    pct: int = 100,
    earlier_p: tuple[str, ...] = (),
    skipped: tuple[SkippedFile, ...] = (),
    duplicates: int = 0,
    other_domain: int = 0,
    passed_over: int = 0,
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
        senders (tuple[SenderRow, ...] | None, optional): The rows of the table. Default: one
            known row holding the ``ok`` messages.
        failing (tuple[FailingSource, ...], optional): The failing sources; the failing total is
            their sum. Default: none.
        p (str, optional): The latest published ``p``. Default: ``none``.
        sp (str, optional): The published ``sp``. Default: empty.
        np (str, optional): The published ``np``. Default: empty.
        pct (int, optional): The published ``pct``. Default: 100.
        earlier_p (tuple[str, ...], optional): The other ``p`` values seen. Default: none.
        skipped (tuple[SkippedFile, ...], optional): The refused files. Default: none.
        duplicates (int, optional): Reports dropped as already seen. Default: 0.
        other_domain (int, optional): Reports of another domain. Default: 0.
        passed_over (int, optional): Files passed over by name. Default: 0.

    Returns:
        Summary: The summary.
    """
    by_reason: dict[Reason, int] = {}
    for file in skipped:
        by_reason[file.reason] = by_reason.get(file.reason, 0) + 1
    left_out = {
        "skipped": skipped,
        "skipped_by_reason": tuple(by_reason.items()),
        "duplicates": duplicates,
        "other_domain": other_domain,
        "passed_over": passed_over,
    }
    if days == 0:
        return Summary(domain="example.com", **left_out)  # type: ignore[arg-type]
    if senders is None:
        senders = (SenderRow(Outcome.KNOWN, service="Example Mailer", counts=Counts(ok=ok)),)
    period = Period(
        begin=_FIRST_DAY,
        end=_FIRST_DAY + timedelta(days=days),
        first_day=_FIRST_DAY.date(),
        last_day=(_FIRST_DAY + timedelta(days=days - 1)).date(),
        days_spanned=days,
        days_with_reports=days if with_reports is None else with_reports,
    )
    return Summary(
        domain="example.com",
        selectors_configured=1,
        reports=days,
        reporters=2,
        period=period,
        policy=PolicyPublished(domain="example.com", p=p, sp=sp, np=np, pct=pct),
        earlier_p=earlier_p,
        totals=Counts(
            ok=ok,
            dkim_only=dkim_only,
            spf_only=spf_only,
            failing=sum(source.messages for source in failing),
        ),
        recognized_messages=ok,
        senders=senders,
        failing=failing,
        **left_out,  # type: ignore[arg-type]
    )


def source(
    n: int = 1,
    *,
    outcome: Outcome = Outcome.UNKNOWN,
    service: str = "",
    messages: int = 3,
) -> FailingSource:
    """
    Build a failing source with an address of its own.

    Args:
        n (int, optional): Which address of ``203.0.113.0/24`` to use. Default: 1.
        outcome (Outcome, optional): What identification said. Default: ``UNKNOWN``.
        service (str, optional): The service name. Default: empty.
        messages (int, optional): The failing messages. Default: 3.

    Returns:
        FailingSource: The source.
    """
    return FailingSource(
        outcome,
        f"203.0.113.{n}",
        messages,
        service=service,
        dkim=("fail",),
        spf=("none",),
        override_reasons=("forwarded",),
    )


def make_verdict(**kwargs: object) -> Verdict:
    """
    Judge a ``make_summary`` summary.

    Args:
        **kwargs (object): The arguments of ``make_summary``.

    Returns:
        Verdict: The verdict of that summary.
    """
    return judge(make_summary(**kwargs))  # type: ignore[arg-type]


def roundtrip(document: dict[str, object]) -> dict[str, object]:
    """
    Write a document and read it back, as a consumer would.

    Args:
        document (dict[str, object]): A document from ``render_json``.

    Returns:
        dict[str, object]: What ``json.loads`` reads.
    """
    loaded = json.loads(dumps(document))
    assert isinstance(loaded, dict)
    return loaded


# ---------------------------------------------------------------------------
# The summary document (RF-02, RF-03)
# ---------------------------------------------------------------------------


def test_the_summary_document_has_its_keys_in_the_documented_order() -> None:
    """The keys, in order, are the contract; ``schema_version``, ``command`` and ``domain`` lead."""
    document = summary_document(make_summary(), "mailvigil.toml")

    assert list(document) == [
        "schema_version",
        "command",
        "domain",
        "config",
        "reports",
        "period",
        "policy",
        "earlier_p",
        "totals",
        "recognized_messages",
        "senders",
        "failing",
        "skipped",
        "skipped_by_reason",
        "duplicates",
        "other_domain",
        "passed_over",
    ]
    assert document["schema_version"] == 1
    assert document["command"] == "summary"
    assert document["domain"] == "example.com"
    assert document["config"] == {"source": "mailvigil.toml", "selectors": 1}
    assert document["reports"] == {"count": 28, "reporters": 2}


def test_the_period_and_the_policy_are_written_as_data() -> None:
    """Days are ``YYYY-MM-DD`` and the counts are integers; no ratio is computed."""
    document = summary_document(make_summary(days=10, with_reports=7, p="quarantine", pct=50), None)

    assert document["period"] == {
        "first_day": "2026-09-01",
        "last_day": "2026-09-10",
        "days_spanned": 10,
        "days_with_reports": 7,
    }
    assert document["policy"] == {"p": "quarantine", "sp": None, "np": None, "pct": 50}


def test_without_reports_the_period_and_the_policy_are_null() -> None:
    """A value the model may not have is ``null``, never missing and never empty (RF-03)."""
    document = summary_document(make_summary(days=0), None)

    assert document["period"] is None
    assert document["policy"] is None
    assert document["senders"] == []
    assert document["failing"] == []
    assert document["totals"] == {"ok": 0, "dkim_only": 0, "spf_only": 0, "failing": 0, "total": 0}


def test_an_empty_sp_and_np_are_null_and_a_present_one_is_kept() -> None:
    """The subdomain policies are strings when published and ``null`` when absent."""
    document = summary_document(make_summary(sp="reject", np=""), None)

    assert document["policy"] == {"p": "none", "sp": "reject", "np": None, "pct": 100}


def test_the_config_source_is_null_without_a_file() -> None:
    """With no file the source is ``null``, not an empty string."""
    document = summary_document(make_summary(), None)

    assert document["config"] == {"source": None, "selectors": 1}


def test_the_totals_have_the_five_counts() -> None:
    """``counts`` carries ``ok``, ``dkim_only``, ``spf_only``, ``failing`` and ``total``."""
    failing = (source(messages=4),)
    document = summary_document(make_summary(ok=10, dkim_only=3, spf_only=2, failing=failing), None)

    assert document["totals"] == {
        "ok": 10,
        "dkim_only": 3,
        "spf_only": 2,
        "failing": 4,
        "total": 19,
    }


def test_a_sender_row_and_a_failing_source_have_their_documented_shape() -> None:
    """The ``sender`` and ``source`` objects, with ``null`` for what a row does not have."""
    rows = (
        SenderRow(Outcome.KNOWN, service="Example Mailer", counts=Counts(ok=5)),
        SenderRow(
            Outcome.UNKNOWN, source_ip=_OTHER_IP, selectors=("s9",), counts=Counts(failing=2)
        ),
    )
    failing = (source(1, outcome=Outcome.KNOWN, service="Example Mailer", messages=2),)
    document = summary_document(make_summary(senders=rows, failing=failing), None)

    senders = document["senders"]
    assert isinstance(senders, list)
    assert list(senders[0]) == ["outcome", "service", "source_ip", "selectors", "counts"]
    assert senders[0] == {
        "outcome": "known",
        "service": "Example Mailer",
        "source_ip": None,
        "selectors": [],
        "counts": {"ok": 5, "dkim_only": 0, "spf_only": 0, "failing": 0, "total": 5},
    }
    assert senders[1]["service"] is None
    assert senders[1]["source_ip"] == _OTHER_IP
    assert senders[1]["selectors"] == ["s9"]
    failing_documents = document["failing"]
    assert isinstance(failing_documents, list)
    assert list(failing_documents[0]) == [
        "outcome",
        "service",
        "source_ip",
        "messages",
        "selectors",
        "dkim",
        "spf",
        "override_reasons",
    ]
    assert failing_documents[0]["dkim"] == ["fail"]
    assert failing_documents[0]["spf"] == ["none"]
    assert failing_documents[0]["override_reasons"] == ["forwarded"]


def test_every_sender_and_failing_source_is_there_beyond_the_text_limits() -> None:
    """The text shows 10 rows and 5 sources; the document has all of them (RF-02)."""
    rows = tuple(
        SenderRow(Outcome.UNKNOWN, source_ip=f"198.51.100.{n}", counts=Counts(ok=1))
        for n in range(1, 31)
    )
    failing = tuple(source(n) for n in range(1, 21))

    document = summary_document(make_summary(senders=rows, failing=failing), None)

    assert isinstance(document["senders"], list)
    assert isinstance(document["failing"], list)
    assert len(document["senders"]) == 30
    assert len(document["failing"]) == 20


def test_a_skipped_file_carries_its_name_without_its_folder_and_no_detail() -> None:
    """No path of the machine reaches the document, and the English detail stays out."""
    skipped = (
        SkippedFile(Path("private") / "folder" / "a.xml", Reason.MALFORMED_XML, "bad tag"),
        SkippedFile(Path("private") / "folder" / "b.zip", Reason.NOT_AN_ARCHIVE, "bad zip"),
        SkippedFile(Path("c.xml"), Reason.MALFORMED_XML, "bad tag"),
        SkippedFile(Path("box.mbox"), Reason.NOT_AN_ARCHIVE, "bad zip", "#2 r.zip"),
    )

    document = summary_document(make_summary(skipped=skipped), None)

    assert document["skipped"] == [
        {"name": "a.xml", "part": None, "reason": "malformed_xml"},
        {"name": "b.zip", "part": None, "reason": "not_an_archive"},
        {"name": "c.xml", "part": None, "reason": "malformed_xml"},
        {"name": "box.mbox", "part": "#2 r.zip", "reason": "not_an_archive"},
    ]
    assert document["skipped_by_reason"] == [
        {"reason": "malformed_xml", "count": 2},
        {"reason": "not_an_archive", "count": 2},
    ]
    assert "private" not in dumps(document)
    assert "bad tag" not in dumps(document)


def test_the_duplicates_and_the_other_domain_are_integers() -> None:
    """What was left out is counted, not described."""
    document = summary_document(make_summary(duplicates=2, other_domain=1), None)

    assert document["duplicates"] == 2
    assert document["other_domain"] == 1


# ---------------------------------------------------------------------------
# The verdict document (RF-02, RF-04)
# ---------------------------------------------------------------------------


def test_the_verdict_document_has_its_keys_in_the_documented_order() -> None:
    """The keys, in order, with the three common ones first."""
    document = verdict_document(make_verdict())

    assert list(document) == [
        "schema_version",
        "command",
        "domain",
        "answer",
        "enforcing",
        "deciding",
        "rules",
        "recognized_failing",
        "unrecognized_failing",
        "notes",
        "left_out",
    ]
    assert document["schema_version"] == 1
    assert document["command"] == "verdict"
    assert document["domain"] == "example.com"
    assert document["answer"] == "ready"
    assert document["enforcing"] == "none"


def test_deciding_is_null_exactly_when_the_answer_is_ready() -> None:
    """A ready verdict has no deciding rule; the others name one by its stable word."""
    ready = verdict_document(make_verdict())
    too_early = verdict_document(make_verdict(days=2))
    not_ready = verdict_document(
        make_verdict(failing=(source(1, outcome=Outcome.KNOWN, service="Example Mailer"),))
    )

    assert ready["deciding"] is None
    assert too_early["answer"] == "too_early"
    assert too_early["deciding"] == "period_covered"
    assert not_ready["answer"] == "not_ready"
    assert not_ready["deciding"] == "recognized_failures"


def test_enforcing_is_null_without_reports() -> None:
    """No report means no published policy, so ``enforcing`` is ``null``, not an empty string."""
    document = verdict_document(make_verdict(days=0))

    assert document["enforcing"] is None
    assert document["answer"] == "too_early"


def test_the_five_rules_are_in_order_with_their_words_units_and_comparisons() -> None:
    """Each rule has a stable word and the unit of what ``needed`` and ``measured`` count."""
    document = verdict_document(make_verdict())

    rules = document["rules"]
    assert isinstance(rules, list)
    assert [(r["id"], r["unit"], r["comparison"]) for r in rules] == [
        ("period_covered", "days", "at_least"),
        ("days_with_report", "percent_of_days", "at_least"),
        ("messages_seen", "messages", "at_least"),
        ("recognized_failures", "messages", "at_most"),
        ("unrecognized_failures", "per_mille_of_messages", "at_most"),
    ]
    assert list(rules[0]) == [
        "id",
        "kind",
        "measured",
        "whole",
        "needed",
        "unit",
        "comparison",
        "passed",
        "missing",
    ]
    assert rules[1]["kind"] == "data"
    assert rules[3]["kind"] == "problem"


def test_a_rule_carries_the_integers_of_005_and_no_ratio() -> None:
    """Part, whole and threshold are integers so the consumer can repeat the arithmetic."""
    document = verdict_document(make_verdict(days=10, with_reports=5, ok=100))

    rules = document["rules"]
    assert isinstance(rules, list)
    assert rules[1]["measured"] == 5
    assert rules[1]["whole"] == 10
    assert rules[1]["needed"] == 80
    assert rules[1]["passed"] is False
    assert rules[1]["missing"] == 3
    assert all(isinstance(r[key], int) for r in rules for key in ("measured", "whole", "needed"))


def test_every_rule_id_has_a_word_and_a_unit() -> None:
    """A sixth rule cannot reach the output without a stable word and a unit."""
    document = verdict_document(make_verdict())

    rules = document["rules"]
    assert isinstance(rules, list)
    assert len(rules) == len(RuleId)
    for rule_id, rule in zip(RuleId, rules, strict=True):
        assert isinstance(rule["id"], str)
        assert rule["id"].isidentifier()
        assert isinstance(rule["unit"], str)
        assert rule["unit"].isidentifier(), rule_id


def test_both_failing_lists_are_complete_beyond_the_text_limits() -> None:
    """The text keeps 5 and 10; the document has every recognized and every other source."""
    known = tuple(source(n, outcome=Outcome.KNOWN, service="Example Mailer") for n in range(1, 13))
    unknown = tuple(source(n) for n in range(20, 40))

    document = verdict_document(make_verdict(failing=known + unknown))

    assert isinstance(document["recognized_failing"], list)
    assert isinstance(document["unrecognized_failing"], list)
    assert len(document["recognized_failing"]) == 12
    assert len(document["unrecognized_failing"]) == 20
    assert document["recognized_failing"][0]["outcome"] == "known"


def test_the_notes_are_kind_numbers_and_texts() -> None:
    """A note is written as the three things ``judge`` builds, with ``null`` for an absent text."""
    verdict = make_verdict(dkim_only=4, spf_only=1, pct=50, earlier_p=("none",), sp="reject")

    document = verdict_document(verdict)

    notes = document["notes"]
    assert isinstance(notes, list)
    assert [note["kind"] for note in notes] == [
        "fragile",
        "partial_policy",
        "policy_changed",
        "subdomain_policy",
    ]
    assert list(notes[0]) == ["kind", "numbers", "texts"]
    assert notes[0]["numbers"] == [5, 1, 2005]
    assert notes[2]["texts"] == ["none"]
    assert notes[3]["texts"] == ["reject", None]


def test_every_note_kind_is_written_by_its_value() -> None:
    """The note kinds are the stable words of the enum, whatever the numbers and texts."""
    base = make_verdict()
    verdict = Verdict(
        domain=base.domain,
        answer=base.answer,
        enforcing=base.enforcing,
        rules=base.rules,
        deciding=base.deciding,
        recognized_failing=(),
        unrecognized_failing=(),
        notes=tuple(Note(kind) for kind in NoteKind),
    )

    document = verdict_document(verdict)

    notes = document["notes"]
    assert isinstance(notes, list)
    assert [note["kind"] for note in notes] == [kind.value for kind in NoteKind]


def test_left_out_is_four_integers() -> None:
    """What the summary did not count, as numbers."""
    skipped = (SkippedFile(Path("a.xml"), Reason.MALFORMED_XML, ""),)

    document = verdict_document(
        make_verdict(skipped=skipped, duplicates=2, other_domain=3, passed_over=4)
    )

    assert document["left_out"] == {
        "skipped": 1,
        "duplicates": 2,
        "other_domain": 3,
        "passed_over": 4,
    }


def test_the_answer_is_the_same_under_reject_and_under_none() -> None:
    """The enforcing form changes ``enforcing``, never ``answer`` or ``deciding`` (RF-04)."""
    failing = (source(1, outcome=Outcome.KNOWN, service="Example Mailer"),)

    under_none = verdict_document(make_verdict(p="none", failing=failing))
    under_reject = verdict_document(make_verdict(p="reject", failing=failing))

    assert under_none["answer"] == under_reject["answer"] == "not_ready"
    assert under_none["deciding"] == under_reject["deciding"]
    assert under_reject["enforcing"] == "reject"
    assert make_verdict(p="reject").answer is Answer.READY


# ---------------------------------------------------------------------------
# The properties (RF-01, RF-07)
# ---------------------------------------------------------------------------


def test_two_builds_of_the_same_input_are_byte_equal() -> None:
    """No clock, no machine path and no random order reach the document."""
    failing = (source(1), source(2, outcome=Outcome.KNOWN, service="Example Mailer"))

    first = dumps(summary_document(make_summary(failing=failing), "mailvigil.toml"))
    second = dumps(summary_document(make_summary(failing=failing), "mailvigil.toml"))

    assert first == second
    assert dumps(verdict_document(make_verdict(failing=failing))) == dumps(
        verdict_document(make_verdict(failing=failing))
    )


def test_the_days_of_a_summary_do_not_reach_the_documents() -> None:
    """Spec 008, RF-08: the per-day counts are internal and the schema of 006 does not change."""
    plain = make_summary()
    days = (DayCounts(_FIRST_DAY.date(), 1, Counts(ok=7)),)
    covered = ((_FIRST_DAY.date(), _FIRST_DAY.date()),)
    dated = dataclasses.replace(plain, days=days, covered=covered)

    assert dumps(summary_document(dated, "mailvigil.toml")) == dumps(
        summary_document(plain, "mailvigil.toml")
    )
    assert dumps(verdict_document(judge(dated))) == dumps(verdict_document(judge(plain)))


def _report(report_id: str, day: int, ip: str, selector: str) -> Report:
    """
    Build a one-day report with one failing record.

    Args:
        report_id (str): The id of the report.
        day (int): How many days after the first day it starts.
        ip (str): The source address.
        selector (str): The DKIM selector of the record.

    Returns:
        Report: The report.
    """
    begin = _FIRST_DAY + timedelta(days=day)
    record = Record(
        source_ip=ip,
        count=3,
        dkim_evaluated="fail",
        spf_evaluated="fail",
        header_from="example.com",
        dkim=(DkimResult("example.com", selector, "fail"),),
    )
    return Report(
        reporter="Example Mail",
        report_id=report_id,
        begin=begin,
        end=begin + timedelta(days=1),
        policy=PolicyPublished(domain="example.com", p="none"),
        records=(record,),
        source_file=f"{report_id}.xml",
    )


def test_the_same_reports_in_any_order_give_equal_documents() -> None:
    """Order of the files must not reach the bytes: ``summarize`` sorts, the document keeps it."""
    reports = (
        _report("r1", 0, "203.0.113.1", "s1"),
        _report("r2", 1, "203.0.113.2", "s2"),
        _report("r3", 2, "203.0.113.3", "s1"),
    )
    config = Config("example.com", MappingProxyType({"s1": "Example Mailer"}))
    documents = set()
    for order in permutations(reports):
        summary = summarize(IngestionResult(reports=order), config)
        documents.add(
            (dumps(summary_document(summary, None)), dumps(verdict_document(judge(summary))))
        )

    assert len(documents) == 1


def test_an_awkward_service_name_round_trips_and_the_output_is_ascii() -> None:
    """A quote, a backslash, a control character and a non-ASCII letter survive ``json.loads``."""
    name = 'Mailer "A" \\ B\x07 ção'
    rows = (SenderRow(Outcome.KNOWN, service=name, counts=Counts(ok=1)),)
    failing = (source(1, outcome=Outcome.KNOWN, service=name),)
    summary = make_summary(senders=rows, failing=failing)

    text = dumps(summary_document(summary, None))

    assert text.isascii()
    loaded = json.loads(text)
    assert loaded["senders"][0]["service"] == name
    assert loaded["failing"][0]["service"] == name
    verdict_text = dumps(verdict_document(judge(summary)))
    assert verdict_text.isascii()
    assert json.loads(verdict_text)["recognized_failing"][0]["service"] == name


def test_dumps_has_no_trailing_newline_and_is_indented() -> None:
    """The command adds the newline; the document is readable by a person."""
    text = dumps(summary_document(make_summary(), None))

    assert not text.endswith("\n")
    assert text.startswith('{\n  "schema_version": 1,\n  "command": "summary"')


def test_dumps_refuses_a_value_that_is_not_json() -> None:
    """``NaN`` would be invalid JSON; it must be an error, not output."""
    with pytest.raises(ValueError, match="Out of range float"):
        dumps({"value": float("nan")})


# ---------------------------------------------------------------------------
# The fetch document (spec 009, ADR-11)
# ---------------------------------------------------------------------------


def test_the_fetch_document_is_the_six_numbers_in_the_documented_order() -> None:
    """``schema_version`` and ``command`` lead, there is no ``domain`` and no path."""
    outcome = FetchOutcome(matched=12, saved=9, already=2, too_large=0, skipped=0, left=1)

    document = fetch_document(outcome)

    assert list(document) == [
        "schema_version",
        "command",
        "matched",
        "saved",
        "already",
        "too_large",
        "skipped",
        "left",
    ]
    assert document["schema_version"] == 1
    assert document["command"] == "fetch"
    assert [document[key] for key in list(document)[2:]] == [12, 9, 2, 0, 0, 1]


def test_the_fetch_document_is_ascii_json_that_dumps_cleanly() -> None:
    """The same writer as the other documents: ASCII, parseable, the numbers as integers."""
    outcome = FetchOutcome(matched=3, saved=1, already=1, too_large=0, skipped=0, left=1)

    text = dumps(fetch_document(outcome))

    assert text.isascii()
    assert json.loads(text)["saved"] == 1
