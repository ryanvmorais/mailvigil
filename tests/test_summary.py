"""
Tests of the summary: classification, rows per sender, failing sources and the shape of the model.

Isolation: nothing touches the disk and no command runs. Records, reports and the configuration are
built in the test with the dataclasses, from invented domains (``example.com``, ``example.org``),
invented service names and the documentation address ranges ``192.0.2.0/24``,
``198.51.100.0/24`` and ``203.0.113.0/24`` (RNF-07).
"""

from __future__ import annotations

import dataclasses
import itertools
from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType

import pytest

from mailvigil.config import Config
from mailvigil.reports import (
    DkimResult,
    IngestionResult,
    OverrideReason,
    PolicyPublished,
    Reason,
    Record,
    Report,
    SkippedFile,
    SpfResult,
)
from mailvigil.senders import Outcome
from mailvigil.summary import (
    Counts,
    DayCounts,
    FailingSource,
    Period,
    SenderRow,
    Situation,
    Summary,
    classify,
    summarize,
)

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

# Two invented services, so no real one is named (RNF-07); selectors are lower case as the loader
# guarantees.
_SENDERS = {"newsletter": "Example Mailer", "mailbox": "Example Mail"}

_BEGIN = datetime(2026, 10, 1, tzinfo=UTC)
_END = datetime(2026, 10, 1, 23, 59, 59, tzinfo=UTC)


def config(senders: dict[str, str] | None = None) -> Config:
    """
    Build a configuration for ``example.com`` without going through the file loader.

    Args:
        senders (dict[str, str] | None, optional): Selector (lower case) to service name. Default:
            two invented services.

    Returns:
        Config: The configuration.
    """
    return Config("example.com", MappingProxyType(_SENDERS if senders is None else senders))


def signed(selector: str = "newsletter", domain: str = "example.com") -> DkimResult:
    """
    Build one passing DKIM block.

    Args:
        selector (str, optional): The ``s=`` selector. Default: ``newsletter``.
        domain (str, optional): The ``d=`` domain. Default: ``example.com``.

    Returns:
        DkimResult: The block.
    """
    return DkimResult(domain=domain, selector=selector, result="pass")


def record(
    ip: str = "192.0.2.10",
    count: int = 10,
    dkim_evaluated: str = "pass",
    spf_evaluated: str = "pass",
    dkim: tuple[DkimResult, ...] = (),
    spf: tuple[SpfResult, ...] = (),
    reasons: tuple[OverrideReason, ...] = (),
    disposition: str = "none",
) -> Record:
    """
    Build one record of a report.

    Args:
        ip (str, optional): The source address. Default: ``192.0.2.10``.
        count (int, optional): The number of messages. Default: 10.
        dkim_evaluated (str, optional): ``policy_evaluated/dkim``. Default: ``pass``.
        spf_evaluated (str, optional): ``policy_evaluated/spf``. Default: ``pass``.
        dkim (tuple[DkimResult, ...], optional): The DKIM blocks. Default: none.
        spf (tuple[SpfResult, ...], optional): The SPF blocks. Default: none.
        reasons (tuple[OverrideReason, ...], optional): The override reasons. Default: none.
        disposition (str, optional): What the receiver did. Default: ``none``.

    Returns:
        Record: The record.
    """
    return Record(
        source_ip=ip,
        count=count,
        disposition=disposition,
        dkim_evaluated=dkim_evaluated,
        spf_evaluated=spf_evaluated,
        override_reasons=reasons,
        header_from="example.com",
        dkim=dkim,
        spf=spf,
    )


def report(*records: Record, report_id: str = "1") -> Report:
    """
    Build one report of ``example.com`` with the given records.

    Args:
        *records (Record): The rows, in document order.
        report_id (str, optional): The id the reporter gave it. Default: ``1``.

    Returns:
        Report: The report.
    """
    return Report(
        reporter="reporter.example.net",
        report_id=report_id,
        begin=_BEGIN,
        end=_END,
        policy=PolicyPublished(domain="example.com"),
        records=records,
        source_file=f"report-{report_id}.xml",
    )


def summary_of(*records: Record, cfg: Config | None = None) -> Summary:
    """
    Summarize one report that holds exactly these records.

    Args:
        *records (Record): The rows of the report.
        cfg (Config | None, optional): The configuration. Default: the two invented services.

    Returns:
        Summary: The summary.
    """
    return summarize(IngestionResult(reports=(report(*records),)), cfg or config())


# ---------------------------------------------------------------------------
# Vocabulary and shape (RNF-03, RNF-04)
# ---------------------------------------------------------------------------


def test_situation_is_a_string_enum_with_the_three_situations() -> None:
    """The situations are the stable words the table prints and the JSON will carry."""
    assert issubclass(Situation, StrEnum)
    assert [member.value for member in Situation] == ["ok", "fragile", "failing"]


def test_counts_derive_fragile_and_total() -> None:
    """``fragile`` is the two single-mechanism passes and ``total`` is everything."""
    counts = Counts(ok=5, dkim_only=3, spf_only=2, failing=1)

    assert counts.fragile == 5
    assert counts.total == 11


@pytest.mark.parametrize(
    "instance",
    [
        Counts(),
        SenderRow(Outcome.UNKNOWN),
        FailingSource(Outcome.UNKNOWN, "192.0.2.1", 1),
        DayCounts(_BEGIN.date()),
        Period(_BEGIN, _END, _BEGIN.date(), _END.date(), 1, 1),
        Summary("example.com"),
    ],
    ids=["Counts", "SenderRow", "FailingSource", "DayCounts", "Period", "Summary"],
)
def test_every_part_of_the_model_is_frozen(instance: object) -> None:
    """Assigning to a field of the model raises, so a summary cannot change under a reader."""
    # why: ``fields`` wants a dataclass instance and the test passes any part of the model
    first = dataclasses.fields(instance)[0].name  # type: ignore[arg-type]

    with pytest.raises(FrozenInstanceError):
        setattr(instance, first, None)


def test_summary_has_the_fields_of_the_design_and_no_display_text() -> None:
    """The summary is data: its only string is the domain; the rest is numbers or tuples."""
    fields = {field.name: str(field.type) for field in dataclasses.fields(Summary)}

    assert set(fields) == {
        "domain",
        "selectors_configured",
        "reports",
        "reporters",
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
        "days",
        "covered",
        "reporter_activity",
    }
    assert [name for name, kind in fields.items() if kind == "str"] == ["domain"]


def test_every_collection_of_a_summary_is_a_tuple() -> None:
    """No list and no dict is exposed (RNF-04)."""
    summary = summary_of(record(dkim_evaluated="fail", spf_evaluated="fail"))

    for name in (
        "earlier_p",
        "senders",
        "failing",
        "skipped",
        "skipped_by_reason",
        "days",
        "covered",
        "reporter_activity",
    ):
        assert isinstance(getattr(summary, name), tuple)
    assert isinstance(summary.senders[0].selectors, tuple)
    assert isinstance(summary.failing[0].dkim, tuple)
    assert isinstance(summary.failing[0].override_reasons, tuple)


# ---------------------------------------------------------------------------
# Classification (RF-01)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("dkim", "spf", "expected"),
    [
        ("pass", "pass", Situation.OK),
        ("pass", "fail", Situation.FRAGILE),
        ("fail", "pass", Situation.FRAGILE),
        ("pass", "", Situation.FRAGILE),
        ("fail", "fail", Situation.FAILING),
        ("", "", Situation.FAILING),
        ("error", "softfail", Situation.FAILING),
    ],
    ids=["both", "dkim-only", "spf-only", "dkim-only-spf-missing", "neither", "empty", "other"],
)
def test_a_record_is_ok_fragile_or_failing(dkim: str, spf: str, expected: Situation) -> None:
    """Both is ``ok``, one is ``fragile``, none (or a missing result) is ``failing``."""
    assert classify(record(dkim_evaluated=dkim, spf_evaluated=spf)) is expected


@pytest.mark.parametrize("value", ["PASS", " pass ", "Pass"])
def test_pass_ignores_case_and_surrounding_spaces(value: str) -> None:
    """Receivers differ in how they write the result."""
    assert classify(record(dkim_evaluated=value, spf_evaluated=value)) is Situation.OK


def test_disposition_and_override_reasons_do_not_change_the_situation() -> None:
    """Under ``p=none`` everything is delivered, which says nothing about authentication."""
    plain = record(dkim_evaluated="fail", spf_evaluated="fail")
    busy = record(
        dkim_evaluated="fail",
        spf_evaluated="fail",
        disposition="quarantine",
        reasons=(OverrideReason(type="forwarded", comment="trusted"),),
    )

    assert classify(plain) is classify(busy) is Situation.FAILING


# ---------------------------------------------------------------------------
# Rows per sender (RF-02)
# ---------------------------------------------------------------------------


def test_two_selectors_of_one_service_share_a_row() -> None:
    """The row is the service name, whatever the selector that signed."""
    cfg = config({"a": "Example Mailer", "b": "Example Mailer"})

    summary = summary_of(
        record(count=4, dkim=(signed("a"),)), record(count=6, dkim=(signed("b"),)), cfg=cfg
    )

    assert len(summary.senders) == 1
    row = summary.senders[0]
    assert (row.outcome, row.service, row.counts.total) == (Outcome.KNOWN, "Example Mailer", 10)


def test_a_known_service_from_two_addresses_is_one_row() -> None:
    """The address does not split a recognized sender."""
    summary = summary_of(
        record(ip="192.0.2.10", dkim=(signed(),)), record(ip="198.51.100.5", dkim=(signed(),))
    )

    assert [row.service for row in summary.senders] == ["Example Mailer"]
    assert summary.senders[0].source_ip == ""


def test_one_address_under_two_outcomes_is_two_rows_without_a_service() -> None:
    """A foreign signature and no signature from one IP are two different facts."""
    foreign = record(ip="203.0.113.50", dkim=(signed("newsletter", "example.org"),))
    unsigned = record(ip="203.0.113.50")

    summary = summary_of(foreign, unsigned)

    assert {row.outcome for row in summary.senders} == {Outcome.FOREIGN_DOMAIN, Outcome.UNKNOWN}
    assert all(row.service == "" and row.source_ip == "203.0.113.50" for row in summary.senders)


def test_a_row_that_is_not_known_lists_its_selectors_sorted() -> None:
    """The owner sees which configured selectors a stranger borrowed."""
    summary = summary_of(
        record(ip="203.0.113.50", dkim=(signed("newsletter", "example.org"),)),
        record(ip="203.0.113.50", dkim=(signed("mailbox", "example.org"),)),
    )

    assert summary.senders[0].selectors == ("mailbox", "newsletter")


def test_a_known_row_lists_no_selectors() -> None:
    """The selectors are a hint for what is not recognized; a recognized row has a name instead."""
    assert summary_of(record(dkim=(signed(),))).senders[0].selectors == ()


def test_a_record_with_no_messages_adds_nothing_and_makes_no_row() -> None:
    """Zero messages is a valid report row and an empty fact."""
    summary = summary_of(record(count=0, dkim_evaluated="fail", spf_evaluated="fail"))

    assert summary.senders == ()
    assert summary.failing == ()
    assert summary.totals == Counts()


def test_rows_are_ordered_by_total_then_by_label() -> None:
    """The biggest sender first, and equal totals in a fixed order (RNF-05)."""
    summary = summary_of(
        record(ip="203.0.113.9", count=5),
        record(ip="203.0.113.1", count=5),
        record(ip="198.51.100.7", count=50),
        record(ip="192.0.2.4", count=500, dkim=(signed(),)),
    )

    assert [row.service or row.source_ip for row in summary.senders] == [
        "Example Mailer",
        "198.51.100.7",
        "203.0.113.1",
        "203.0.113.9",
    ]


def test_totals_split_by_situation_and_count_the_recognized_messages() -> None:
    """The totals add up the rows, and ``recognized_messages`` is what the owner's map names."""
    summary = summary_of(
        record(count=100, dkim=(signed(),)),
        record(count=30, dkim_evaluated="pass", spf_evaluated="fail", dkim=(signed("mailbox"),)),
        record(ip="203.0.113.7", count=7, dkim_evaluated="fail", spf_evaluated="pass"),
        record(ip="203.0.113.8", count=3, dkim_evaluated="fail", spf_evaluated="fail"),
    )

    assert summary.totals == Counts(ok=100, dkim_only=30, spf_only=7, failing=3)
    assert summary.recognized_messages == 130
    assert sum(row.counts.total for row in summary.senders) == summary.totals.total


def test_a_row_tallies_each_situation_by_message_count() -> None:
    """The counts are messages, not records."""
    summary = summary_of(
        record(count=9, dkim=(signed(),)),
        record(count=2, spf_evaluated="fail", dkim=(signed(),)),
        record(count=1, dkim_evaluated="fail", spf_evaluated="fail", dkim=(signed(),)),
    )

    assert summary.senders[0].counts == Counts(ok=9, dkim_only=2, spf_only=0, failing=1)


def test_the_same_reports_in_any_order_give_an_equal_summary() -> None:
    """Nothing depends on the order of discovery (RNF-05)."""
    reports = (
        report(record(ip="192.0.2.10", dkim=(signed(),)), report_id="1"),
        report(record(ip="203.0.113.7", dkim_evaluated="fail"), report_id="2"),
        report(
            record(ip="198.51.100.9", dkim_evaluated="fail", spf_evaluated="fail"), report_id="3"
        ),
    )

    summaries = {
        summarize(IngestionResult(reports=order), config())
        for order in itertools.permutations(reports)
    }

    assert len(summaries) == 1


# ---------------------------------------------------------------------------
# Failing sources (RF-04, ADR-2)
# ---------------------------------------------------------------------------


def failing_record(**changes: object) -> Record:
    """
    Build a record in the ``failing`` situation.

    Args:
        **changes (object): Fields of ``record`` to override.

    Returns:
        Record: A record whose evaluated results are both ``fail``.
    """
    base: dict[str, object] = {"dkim_evaluated": "fail", "spf_evaluated": "fail"}
    # why: ``record`` takes typed keywords and ``changes`` is a plain mapping of objects
    return record(**{**base, **changes})  # type: ignore[arg-type]


def test_a_failing_source_is_listed_once_per_address_with_its_messages() -> None:
    """Two records from one address are one source."""
    summary = summary_of(
        failing_record(ip="203.0.113.50", count=4), failing_record(ip="203.0.113.50", count=8)
    )

    assert len(summary.failing) == 1
    source = summary.failing[0]
    assert (source.source_ip, source.messages, source.outcome) == (
        "203.0.113.50",
        12,
        Outcome.UNKNOWN,
    )


def test_a_source_with_no_failing_message_is_not_listed() -> None:
    """Fragile and ok traffic is in the rows, not in the failures."""
    summary = summary_of(record(), record(spf_evaluated="fail", ip="203.0.113.7"))

    assert summary.failing == ()


def test_a_known_service_failing_from_two_addresses_gives_two_sources() -> None:
    """The row is the service, the failure is the address it came from."""
    summary = summary_of(
        failing_record(ip="192.0.2.10", count=5, dkim=(signed(),)),
        failing_record(ip="198.51.100.5", count=9, dkim=(signed(),)),
    )

    assert len(summary.senders) == 1
    assert [(s.service, s.source_ip, s.messages) for s in summary.failing] == [
        ("Example Mailer", "198.51.100.5", 9),
        ("Example Mailer", "192.0.2.10", 5),
    ]
    assert all(source.outcome is Outcome.KNOWN for source in summary.failing)


def test_a_passing_signature_that_did_not_count_is_unaligned() -> None:
    """The signature passed, but for another domain: the usual third-party case."""
    summary = summary_of(failing_record(dkim=(signed("other", "example.org"),)))

    assert summary.failing[0].dkim == ("unaligned",)


def test_blocks_that_all_failed_are_a_failed_check() -> None:
    """A check that ran and did not pass is ``fail``."""
    block = DkimResult(domain="example.com", selector="newsletter", result="fail")
    summary = summary_of(failing_record(dkim=(block,), spf=(SpfResult("example.com", "softfail"),)))

    assert (summary.failing[0].dkim, summary.failing[0].spf) == (("fail",), ("fail",))


def test_no_block_is_none() -> None:
    """A mechanism the receiver did not report on is ``none``."""
    assert summary_of(failing_record()).failing[0].dkim == ("none",)
    assert summary_of(failing_record()).failing[0].spf == ("none",)


def test_spf_reasons_are_read_from_the_spf_blocks() -> None:
    """SPF has the same vocabulary as DKIM."""
    summary = summary_of(failing_record(spf=(SpfResult("example.net", "pass"),)))

    assert summary.failing[0].spf == ("unaligned",)


def test_two_records_of_one_source_collect_every_reason_sorted() -> None:
    """One address can fail in two ways; both are shown."""
    # An unconfigured selector keeps all three records the same kind of source (``UNKNOWN``).
    block = DkimResult(domain="example.com", selector="other", result="fail")
    summary = summary_of(
        failing_record(ip="203.0.113.50", dkim=(block,)),
        failing_record(ip="203.0.113.50"),
        failing_record(ip="203.0.113.50", dkim=(signed("x", "example.org"),)),
    )

    assert summary.failing[0].dkim == ("fail", "none", "unaligned")


def test_override_reason_types_are_kept_and_the_comment_is_not() -> None:
    """The type is information; the receiver's free text stays out of the summary."""
    summary = summary_of(
        failing_record(
            reasons=(
                OverrideReason(type="mailing_list", comment="a very long note"),
                OverrideReason(type="forwarded", comment=""),
                OverrideReason(type="forwarded", comment="again"),
                OverrideReason(type="  ", comment="blank"),
            )
        )
    )

    assert summary.failing[0].override_reasons == ("forwarded", "mailing_list")


def test_a_failing_source_that_borrowed_a_selector_keeps_it() -> None:
    """The owner can tell a copied selector from a broken one."""
    summary = summary_of(
        failing_record(ip="203.0.113.50", dkim=(signed("newsletter", "example.org"),))
    )

    source = summary.failing[0]
    assert (source.outcome, source.selectors, source.service) == (
        Outcome.FOREIGN_DOMAIN,
        ("newsletter",),
        "",
    )


def test_failing_sources_are_ordered_by_messages_then_label() -> None:
    """The worst first, and ties in a fixed order (RNF-05)."""
    summary = summary_of(
        failing_record(ip="203.0.113.9", count=5),
        failing_record(ip="203.0.113.1", count=5),
        failing_record(ip="198.51.100.7", count=50),
    )

    assert [source.source_ip for source in summary.failing] == [
        "198.51.100.7",
        "203.0.113.1",
        "203.0.113.9",
    ]


# ---------------------------------------------------------------------------
# Scale (RNF-09)
# ---------------------------------------------------------------------------


def test_many_records_from_few_sources_keep_only_the_sources() -> None:
    """Memory follows the number of sources, not the number of records."""
    records = [failing_record(ip=f"203.0.113.{index % 200}", count=1) for index in range(50_000)]

    summary = summary_of(*records)

    assert len(summary.senders) == 200
    assert len(summary.failing) == 200
    assert summary.totals.failing == 50_000


# ---------------------------------------------------------------------------
# Period (RF-03, ADR-3)
# ---------------------------------------------------------------------------


def at(day: int, hour: int = 0, minute: int = 0, second: int = 0) -> datetime:
    """
    Build a UTC moment in October 2026.

    Args:
        day (int): The day of the month.
        hour (int, optional): The hour. Default: 0.
        minute (int, optional): The minute. Default: 0.
        second (int, optional): The second. Default: 0.

    Returns:
        datetime: The moment, timezone-aware.
    """
    return datetime(2026, 10, day, hour, minute, second, tzinfo=UTC)


def dated(
    begin: datetime,
    end: datetime,
    report_id: str = "1",
    reporter: str = "reporter.example.net",
    p: str = "none",
) -> Report:
    """
    Build an empty report of ``example.com`` for a period.

    Args:
        begin (datetime): Start of the period.
        end (datetime): End of the period.
        report_id (str, optional): The id the reporter gave it. Default: ``1``.
        reporter (str, optional): The reporting organization. Default: ``reporter.example.net``.
        p (str, optional): The published policy. Default: ``none``.

    Returns:
        Report: The report.
    """
    return Report(
        reporter=reporter,
        report_id=report_id,
        begin=begin,
        end=end,
        policy=PolicyPublished(domain="example.com", p=p),
        records=(),
        source_file=f"report-{report_id}.xml",
    )


def summary_of_reports(*reports: Report) -> Summary:
    """
    Summarize these reports.

    Args:
        *reports (Report): The reports kept.

    Returns:
        Summary: The summary.
    """
    return summarize(IngestionResult(reports=reports), config())


def test_the_period_runs_from_the_earliest_begin_to_the_latest_end() -> None:
    """Whatever the order of the reports."""
    summary = summary_of_reports(
        dated(at(5), at(5, 23, 59, 59), "2"), dated(at(1), at(1, 23, 59, 59), "1")
    )

    period = summary.period
    assert period is not None
    assert (period.begin, period.end) == (at(1), at(5, 23, 59, 59))
    assert (period.first_day, period.last_day) == (date(2026, 10, 1), date(2026, 10, 5))
    assert (period.days_spanned, period.days_with_reports) == (5, 2)


@pytest.mark.parametrize("end", [at(2), at(1, 23, 59, 59)], ids=["next midnight", "23:59:59"])
def test_a_report_of_one_day_touches_one_day_however_the_reporter_ends_it(end: datetime) -> None:
    """The end is exclusive, so midnight to midnight is one day, not two (ADR-3)."""
    period = summary_of_reports(dated(at(1), end)).period

    assert period is not None
    assert (period.days_spanned, period.days_with_reports) == (1, 1)
    assert period.last_day == date(2026, 10, 1)


def test_a_report_that_crosses_midnight_touches_two_days() -> None:
    """Each day a report touches counts."""
    period = summary_of_reports(dated(at(1, 12), at(2, 12))).period

    assert period is not None
    assert (period.days_spanned, period.days_with_reports) == (2, 2)


def test_a_gap_day_lowers_the_days_with_reports() -> None:
    """The verdict needs to know that a day is missing."""
    period = summary_of_reports(
        dated(at(1), at(2), "1"), dated(at(3), at(4), "2"), dated(at(5), at(6), "3")
    ).period

    assert period is not None
    assert (period.days_spanned, period.days_with_reports) == (5, 3)


def test_overlapping_reports_do_not_count_a_day_twice() -> None:
    """Two reporters covering the same days are still those days."""
    period = summary_of_reports(
        dated(at(1), at(4), "1"), dated(at(2), at(3), "2"), dated(at(3), at(5), "3")
    ).period

    assert period is not None
    assert (period.days_spanned, period.days_with_reports) == (4, 4)


def test_the_last_day_is_the_last_one_touched_not_the_day_of_a_midnight_end() -> None:
    """The latest ``end`` is a midnight; the day it names is not part of the period."""
    period = summary_of_reports(dated(at(1), at(2), "1"), dated(at(2), at(4), "2")).period

    assert period is not None
    assert period.end == at(4)
    assert period.last_day == date(2026, 10, 3)


def test_a_zero_length_period_spans_its_day_but_covers_nothing() -> None:
    """The day is named, since the report exists, but no time of it is covered."""
    period = summary_of_reports(dated(at(7, 8), at(7, 8))).period

    assert period is not None
    assert (period.first_day, period.last_day) == (date(2026, 10, 7), date(2026, 10, 7))
    assert (period.days_spanned, period.days_with_reports) == (1, 0)


def test_a_missing_report_leaves_its_day_uncovered_when_reports_do_not_start_at_midnight() -> None:
    """Reports from 14:00 to 14:00 with the middle one missing: the day it covered is a hole."""
    period = summary_of_reports(
        dated(at(1, 14), at(2, 14), "1"), dated(at(3, 14), at(4, 14), "2")
    ).period

    assert period is not None
    assert period.days_spanned == 4
    # 1st: 10 h, 2nd: 14 h, 3rd: 10 h, 4th: 14 h; only the 2nd and the 4th reach twelve hours
    assert period.days_with_reports == 2


def test_two_short_periods_on_one_day_add_up_to_cover_it() -> None:
    """Six hours twice is half a day, whichever reports they came from."""
    summary = summary_of_reports(
        dated(at(5, 0), at(5, 6), "1"), dated(at(5, 12), at(5, 18), "2", "other.example.org")
    )

    assert summary.covered == ((date(2026, 10, 5), date(2026, 10, 5)),)


def test_the_days_between_the_ends_of_a_long_period_are_covered_whole() -> None:
    """A period of five days from 18:00: the first day has 6 h and is out, the next four are in."""
    summary = summary_of_reports(dated(at(1, 18), at(6, 18)))

    assert summary.covered == ((date(2026, 10, 2), date(2026, 10, 6)),)
    assert summary.period is not None
    assert (summary.period.days_spanned, summary.period.days_with_reports) == (6, 5)


def test_reporter_activity_sums_messages_and_keeps_the_last_end() -> None:
    """The reporter with most messages comes first; ties are broken by name."""
    summary = summary_of_reports(
        with_messages(at(1), at(2), "1", ("pass", "pass", 3)),
        with_messages(at(9), at(10), "2", ("pass", "pass", 4)),
        dated(at(5), at(6), "3", "b.example.org"),
    )

    assert [(a.name, a.messages, a.last_end) for a in summary.reporter_activity] == [
        ("reporter.example.net", 7, at(10)),
        ("b.example.org", 0, at(6)),
    ]


def test_a_period_of_five_hundred_years_is_summarized_at_once() -> None:
    """No structure grows with the length of a period (RNF-09)."""
    begin = at(1)
    end = begin.replace(year=2526)

    period = summary_of_reports(dated(begin, end, "1"), dated(at(1), at(2), "2")).period

    assert period is not None
    assert period.days_spanned == (end - begin).days
    assert period.days_with_reports == period.days_spanned


# ---------------------------------------------------------------------------
# Days (spec 008, RF-04, ADR-3)
# ---------------------------------------------------------------------------


def with_messages(
    begin: datetime, end: datetime, report_id: str, *counts: tuple[str, str, int]
) -> Report:
    """
    Build a report of ``example.com`` for a period with one record per ``(dkim, spf, count)``.

    Args:
        begin (datetime): Start of the period.
        end (datetime): End of the period.
        report_id (str): The id the reporter gave it.
        *counts (tuple[str, str, int]): The evaluated DKIM and SPF results and the messages of each
            record.

    Returns:
        Report: The report.
    """
    records = tuple(record(dkim_evaluated=d, spf_evaluated=s, count=n) for d, s, n in counts)
    return dataclasses.replace(dated(begin, end, report_id), records=records)


def add_up(days: tuple[DayCounts, ...]) -> Counts:
    """
    Add the counts of every day.

    Args:
        days (tuple[DayCounts, ...]): The days of a summary.

    Returns:
        Counts: The four counts added across the days.
    """
    return Counts(
        ok=sum(day.counts.ok for day in days),
        dkim_only=sum(day.counts.dkim_only for day in days),
        spf_only=sum(day.counts.spf_only for day in days),
        failing=sum(day.counts.failing for day in days),
    )


def test_a_month_of_daily_reports_gives_one_entry_per_day_that_adds_up_to_the_totals() -> None:
    """The invariant of the design: the days are the totals and the reports, cut by day."""
    reports = tuple(
        with_messages(
            at(day),
            at(day + 1),
            str(day),
            ("pass", "pass", 10 + day),
            ("pass", "fail", 2),
            ("fail", "pass", 1),
            ("fail", "fail", day % 3),
        )
        for day in range(1, 31)
    )

    summary = summary_of_reports(*reports)

    assert [day.day for day in summary.days] == [date(2026, 10, day) for day in range(1, 31)]
    assert add_up(summary.days) == summary.totals
    assert sum(day.reports for day in summary.days) == summary.reports == 30
    assert summary.days[0] == DayCounts(
        date(2026, 10, 1), 1, Counts(ok=11, dkim_only=2, spf_only=1, failing=1)
    )


def test_the_days_do_not_depend_on_the_order_of_the_reports() -> None:
    """Sorted by day, like every other collection of the summary (RNF-05)."""
    reports = (
        with_messages(at(3), at(4), "3", ("pass", "pass", 3)),
        with_messages(at(1), at(2), "1", ("pass", "pass", 1)),
        with_messages(at(2), at(3), "2", ("fail", "fail", 2)),
    )

    results = {summary_of_reports(*order).days for order in itertools.permutations(reports)}

    assert len(results) == 1
    (days,) = results
    assert [day.day.day for day in days] == [1, 2, 3]


@pytest.mark.parametrize("end", [at(2), at(1, 23, 59, 59)], ids=["next midnight", "23:59:59"])
def test_a_report_from_midnight_to_midnight_is_one_day(end: datetime) -> None:
    """The end is exclusive: the next midnight does not make a second entry."""
    summary = summary_of_reports(with_messages(at(1), end, "1", ("pass", "pass", 5)))

    assert summary.days == (DayCounts(date(2026, 10, 1), 1, Counts(ok=5)),)
    assert summary.covered == ((date(2026, 10, 1), date(2026, 10, 1)),)


def test_a_report_that_crosses_midnight_counts_all_its_messages_on_the_first_day() -> None:
    """ADR-3: the day a period begins; the second day is only covered."""
    summary = summary_of_reports(
        with_messages(at(1, 12), at(2, 12), "1", ("pass", "pass", 5), ("fail", "fail", 2))
    )

    assert summary.days == (DayCounts(date(2026, 10, 1), 1, Counts(ok=5, failing=2)),)
    assert summary.covered == ((date(2026, 10, 1), date(2026, 10, 2)),)


def test_a_report_of_zero_length_counts_its_messages_on_the_day_it_begins() -> None:
    """Its messages are kept; it covers no time."""
    summary = summary_of_reports(with_messages(at(7, 8), at(7, 8), "1", ("fail", "fail", 4)))

    assert summary.days == (DayCounts(date(2026, 10, 7), 1, Counts(failing=4)),)
    assert summary.covered == ()


def test_two_reports_that_begin_on_one_day_are_one_entry() -> None:
    """Two reporters on the same day: two reports, their messages added."""
    summary = summary_of_reports(
        with_messages(at(4), at(5), "1", ("pass", "pass", 6)),
        with_messages(at(4), at(5), "2", ("pass", "fail", 3), ("pass", "pass", 1)),
    )

    assert summary.days == (DayCounts(date(2026, 10, 4), 2, Counts(ok=7, dkim_only=3)),)


def test_a_report_of_three_days_is_one_entry_and_one_interval_of_three_days() -> None:
    """The other two days are in ``covered`` and carry no counts."""
    summary = summary_of_reports(with_messages(at(1), at(4), "1", ("pass", "pass", 9)))

    assert len(summary.days) == 1
    assert summary.days[0].day == date(2026, 10, 1)
    assert summary.covered == ((date(2026, 10, 1), date(2026, 10, 3)),)


def test_covered_merges_overlaps_and_keeps_the_gaps() -> None:
    """Overlapping or consecutive intervals are one; a missing day splits them."""
    summary = summary_of_reports(
        dated(at(1), at(3), "1"),
        dated(at(2), at(4), "2"),
        dated(at(4), at(5), "3"),
        dated(at(8), at(9), "4"),
        dated(at(10), at(12), "5"),
    )

    assert summary.covered == (
        (date(2026, 10, 1), date(2026, 10, 4)),
        (date(2026, 10, 8), date(2026, 10, 8)),
        (date(2026, 10, 10), date(2026, 10, 11)),
    )


def test_the_length_of_covered_is_the_days_with_reports_of_the_period() -> None:
    """Rule 2 and the timeline read the same list, so they cannot disagree (ADR-3)."""
    summary = summary_of_reports(
        dated(at(1), at(3), "1"), dated(at(2), at(4), "2"), dated(at(8), at(9), "3")
    )

    assert summary.period is not None
    assert sum((last - first).days + 1 for first, last in summary.covered) == (
        summary.period.days_with_reports
    )


def test_a_period_of_centuries_is_one_entry_and_one_interval() -> None:
    """The size follows the reports, never the period (004 RNF-09)."""
    begin = at(1)
    summary = summary_of_reports(
        with_messages(begin, begin.replace(year=2526), "1", ("pass", "pass", 1))
    )

    assert len(summary.days) == 1
    assert len(summary.covered) == 1


def test_without_reports_the_days_and_the_covered_intervals_are_empty() -> None:
    """Nothing to draw."""
    summary = summarize(IngestionResult(), config())

    assert summary.days == ()
    assert summary.covered == ()


def test_a_summary_built_the_old_way_has_no_days() -> None:
    """Both fields are defaulted, so no existing caller has to change."""
    summary = Summary("example.com")

    assert summary.days == ()
    assert summary.covered == ()


def test_a_report_with_no_messages_still_counts_on_its_day() -> None:
    """A report with nothing in it was received on that day."""
    summary = summary_of_reports(with_messages(at(2), at(3), "1", ("pass", "pass", 0)))

    assert summary.days == (DayCounts(date(2026, 10, 2), 1, Counts()),)


# ---------------------------------------------------------------------------
# Policy, reports and reporters (RF-03)
# ---------------------------------------------------------------------------


def test_one_policy_gives_all_its_fields() -> None:
    """The policy of the only report is the policy, with ``sp``, ``np`` and ``pct``."""
    published = PolicyPublished(
        domain="example.com", p="quarantine", sp="reject", np="reject", pct=50
    )
    only = dataclasses.replace(dated(at(1), at(2)), policy=published)

    summary = summary_of_reports(only)

    assert summary.policy == published
    assert summary.earlier_p == ()


def test_a_changed_policy_lists_the_earlier_values_oldest_first_without_repeats() -> None:
    """The latest report wins; the others that differ are the history."""
    reports = (
        dated(at(1), at(2), "1", p="none"),
        dated(at(2), at(3), "2", p="quarantine"),
        dated(at(3), at(4), "3", p="none"),
        dated(at(4), at(5), "4", p="reject"),
        dated(at(5), at(6), "5", p="reject"),
    )

    for order in itertools.permutations(reports):
        summary = summary_of_reports(*order)
        assert summary.policy is not None
        assert summary.policy.p == "reject"
        assert summary.earlier_p == ("none", "quarantine")


def test_a_policy_that_never_changed_has_no_earlier_values() -> None:
    """Two reports with the same ``p`` are not a change."""
    summary = summary_of_reports(dated(at(1), at(2), "1"), dated(at(2), at(3), "2"))

    assert summary.earlier_p == ()


def test_the_reports_and_reporters_are_counted() -> None:
    """Two reporters, one of them twice, are two; an absent reporter (``?``) is one."""
    summary = summary_of_reports(
        dated(at(1), at(2), "1", reporter="a.example.net"),
        dated(at(2), at(3), "2", reporter="a.example.net"),
        dated(at(3), at(4), "3", reporter="b.example.net"),
        dated(at(4), at(5), "4", reporter="?"),
        dated(at(5), at(6), "5", reporter="?"),
    )

    assert (summary.reports, summary.reporters) == (5, 3)


def test_the_selectors_configured_are_counted() -> None:
    """The header says how many selectors the map holds."""
    summary = summarize(IngestionResult(), config({"a": "A", "b": "B", "c": "C"}))

    assert summary.selectors_configured == 3


def test_no_reports_gives_zero_totals_and_no_period_or_policy() -> None:
    """Whether that is an error is the command's decision (RF-10)."""
    summary = summarize(IngestionResult(), config())

    assert (summary.reports, summary.reporters) == (0, 0)
    assert (summary.period, summary.policy, summary.earlier_p) == (None, None, ())
    assert summary.totals == Counts()
    assert (summary.senders, summary.failing) == ((), ())


# ---------------------------------------------------------------------------
# What was left out (RF-05)
# ---------------------------------------------------------------------------


def skipped(name: str, reason: Reason = Reason.NOT_A_REPORT) -> SkippedFile:
    """
    Build a refused file.

    Args:
        name (str): The file name.
        reason (Reason, optional): Why it was refused. Default: ``NOT_A_REPORT``.

    Returns:
        SkippedFile: The refusal.
    """
    return SkippedFile(Path(name), reason, "")


def test_duplicates_and_other_domains_are_copied_also_at_zero() -> None:
    """A line saying nothing was left out is information."""
    empty = summarize(IngestionResult(), config())
    assert (empty.duplicates, empty.other_domain) == (0, 0)

    summary = summarize(IngestionResult(duplicates=3, other_domain=2), config())

    assert (summary.duplicates, summary.other_domain) == (3, 2)


def test_skipped_files_are_ordered_by_path_whatever_the_input_order() -> None:
    """Discovery order must not reach the output (RNF-05)."""
    files = (skipped("b.xml"), skipped("a.xml"), skipped("c.xml"))

    for order in itertools.permutations(files):
        summary = summarize(IngestionResult(skipped=order), config())
        assert [str(file.path) for file in summary.skipped] == ["a.xml", "b.xml", "c.xml"]


def test_skipped_files_are_counted_per_reason_most_frequent_first() -> None:
    """Ties are broken by the reason's value."""
    summary = summarize(
        IngestionResult(
            skipped=(
                skipped("1.xml", Reason.UNREADABLE),
                skipped("2.xml", Reason.NOT_A_REPORT),
                skipped("3.xml", Reason.MALFORMED_XML),
                skipped("4.xml", Reason.NOT_A_REPORT),
                skipped("5.xml", Reason.MALFORMED_XML),
                skipped("6.xml", Reason.NOT_A_REPORT),
            )
        ),
        config(),
    )

    assert summary.skipped_by_reason == (
        (Reason.NOT_A_REPORT, 3),
        (Reason.MALFORMED_XML, 2),
        (Reason.UNREADABLE, 1),
    )


def test_nothing_skipped_has_no_reasons() -> None:
    """An empty tuple, not a missing field."""
    assert summarize(IngestionResult(), config()).skipped_by_reason == ()
