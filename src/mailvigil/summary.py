"""
The summary: the traffic of one domain added up per sender and per situation.

``summarize`` turns an ``IngestionResult`` and a ``Config`` into a frozen ``Summary``: totals per
situation (``ok``, ``fragile``, ``failing``), one row per sender, one entry per failing source, and
what was left out. It holds the complete data and nothing to print: no label, no percentage, no
limit (ADR-1, RNF-03). The text is ``render.py``'s, and the verdict (spec 005) reads this module
without rendering anything. It does no I/O, prints nothing and never raises on report content,
which is already sanitized.
"""

from __future__ import annotations

from bisect import bisect_left
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum

from mailvigil.config import Config
from mailvigil.reports import IngestionResult, PolicyPublished, Reason, Record, Report, SkippedFile
from mailvigil.senders import Outcome, identify_sender
from mailvigil.text import is_within_domain, normalize_domain

#: A UTC day counts as having a report when the reports cover at least this much of it: half a day,
#: so one missing report of 24 hours leaves a day uncovered whatever hour the reports start at.
MIN_COVERED_SECONDS = 12 * 3600

# ---------------------------------------------------------------------------
# Vocabulary and model
# ---------------------------------------------------------------------------


class Situation(StrEnum):
    """
    What a record's authentication amounts to, as the receiver evaluated it.

    Attributes:
        OK (str): DKIM and SPF both passed.
        FRAGILE (str): Exactly one of them passed: DMARC passes, with one safety net less.
        FAILING (str): Neither passed: DMARC fails, and ``p=reject`` would block it.
    """

    OK = "ok"
    FRAGILE = "fragile"
    FAILING = "failing"


@dataclass(frozen=True, slots=True)
class Counts:
    """
    Messages per situation.

    Attributes:
        ok (int): Messages where DKIM and SPF both passed. Default: 0.
        dkim_only (int): Fragile messages where only DKIM passed. Default: 0.
        spf_only (int): Fragile messages where only SPF passed (the more fragile: forwarding breaks
            SPF). Default: 0.
        failing (int): Messages where neither passed. Default: 0.
    """

    ok: int = 0
    dkim_only: int = 0
    spf_only: int = 0
    failing: int = 0

    @property
    def fragile(self) -> int:
        """
        Messages where exactly one mechanism passed.

        Returns:
            int: ``dkim_only`` plus ``spf_only``.
        """
        return self.dkim_only + self.spf_only

    @property
    def total(self) -> int:
        """
        All the messages counted.

        Returns:
            int: ``ok``, ``fragile`` and ``failing`` together.
        """
        return self.ok + self.fragile + self.failing


@dataclass(frozen=True, slots=True)
class SenderRow:
    """
    One row of the senders table.

    Attributes:
        outcome (Outcome): What identification said (003): ``KNOWN``, ``FOREIGN_DOMAIN``,
            ``FAILING_SIGNATURE`` or ``UNKNOWN``.
        service (str): The service name when ``KNOWN``, otherwise empty. Default: empty.
        source_ip (str): The address when not ``KNOWN``, otherwise empty. Default: empty.
        selectors (tuple[str, ...]): The configured selectors seen on a row that is not ``KNOWN``,
            sorted. Default: none.
        counts (Counts): The messages of the row per situation. Default: all zero.
        spf_domains (tuple[str, ...]): The SPF domains that passed under the owner's domain on a
            row that is not ``KNOWN``, sorted: the ones that would go into ``[spf]`` (ADR-8).
            Default: none.
    """

    outcome: Outcome
    service: str = ""
    source_ip: str = ""
    selectors: tuple[str, ...] = ()
    counts: Counts = Counts()
    spf_domains: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FailingSource:
    """
    One address whose messages failed, under one sender.

    Attributes:
        outcome (Outcome): What identification said about the records of this source.
        source_ip (str): The address the failing messages came from.
        messages (int): The failing messages, at least one.
        service (str): The service name when ``KNOWN``, otherwise empty. Default: empty.
        selectors (tuple[str, ...]): The configured selectors seen on this source when it is not
            ``KNOWN``, sorted. Default: none.
        dkim (tuple[str, ...]): Why DKIM did not count, sorted: ``fail`` (a check ran and failed),
            ``unaligned`` (it passed for another domain) or ``none`` (nothing reported). Default:
            none.
        spf (tuple[str, ...]): The same vocabulary for SPF. Default: none.
        override_reasons (tuple[str, ...]): The receiver's override types, sorted and unique,
            without their free-text comments. Default: none.
        spf_domains (tuple[str, ...]): The SPF domains that passed under the owner's domain on this
            source when it is not ``KNOWN``, sorted. Default: none.
    """

    outcome: Outcome
    source_ip: str
    messages: int
    service: str = ""
    selectors: tuple[str, ...] = ()
    dkim: tuple[str, ...] = ()
    spf: tuple[str, ...] = ()
    override_reasons: tuple[str, ...] = ()
    spf_domains: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Period:
    """
    The time the reports cover.

    Attributes:
        begin (datetime): The earliest ``begin``, UTC.
        end (datetime): The latest ``end``, UTC.
        first_day (date): The UTC day ``begin`` falls on.
        last_day (date): The last UTC day any report touches (the end of a period is exclusive).
        days_spanned (int): ``first_day`` to ``last_day``, inclusive.
        days_with_reports (int): The days in that span that at least one report touches.
    """

    begin: datetime
    end: datetime
    first_day: date
    last_day: date
    days_spanned: int
    days_with_reports: int


@dataclass(frozen=True, slots=True)
class DayCounts:
    """
    The messages of the reports that begin on one UTC day (spec 008, ADR-3).

    Attributes:
        day (date): The UTC day the periods of these reports begin on.
        reports (int): How many reports begin that day. Default: 0.
        counts (Counts): Their messages per situation. Default: all zero.
    """

    day: date
    reports: int = 0
    counts: Counts = Counts()


@dataclass(frozen=True, slots=True)
class ReporterActivity:
    """
    What one reporting organization sent, so a reporter that went quiet can be noticed.

    Attributes:
        name (str): The organization, as the report gave it (already cleaned).
        messages (int): The messages in all its reports.
        last_end (datetime): The latest ``end`` among its reports, UTC.
    """

    name: str
    messages: int
    last_end: datetime


@dataclass(frozen=True, slots=True)
class WithoutReporter:
    """
    The five measures of the rules as they would be without one organization's reports (spec 011).

    Attributes:
        name (str): The organization, as the reports gave it (already cleaned).
        messages (int): Its own messages, so the note can give its share.
        days_spanned (int): The days the other reports span; 0 when there are none.
        days_with_reports (int): The days the other reports cover (``MIN_COVERED_SECONDS``).
        total (int): The messages of the other reports.
        recognized_failing (int): Their failing messages under a recognized sender.
        unrecognized_failing (int): Their other failing messages.
    """

    name: str
    messages: int
    days_spanned: int
    days_with_reports: int
    total: int
    recognized_failing: int
    unrecognized_failing: int


@dataclass(frozen=True, slots=True)
class Summary:
    """
    Everything the reports of one domain say, added up.

    Attributes:
        domain (str): The domain the reports are about.
        selectors_configured (int): How many selectors the configuration maps. Default: 0.
        spf_domains_configured (int): How many SPF domains the configuration maps. Default: 0.
        ip_ranges_configured (int): How many address ranges the configuration maps. Default: 0.
        reports (int): The reports kept. Default: 0.
        reporters (int): The distinct reporting organizations, as given. Default: 0.
        period (Period | None): The time covered; ``None`` only without reports. Default: ``None``.
        policy (PolicyPublished | None): The latest report's policy; ``None`` only without reports.
            Default: ``None``.
        earlier_p (tuple[str, ...]): Other ``p`` values seen in the period, oldest first; not empty
            means the policy changed. Default: none.
        totals (Counts): All the messages per situation. Default: all zero.
        recognized_messages (int): The messages of ``KNOWN`` records. Default: 0.
        senders (tuple[SenderRow, ...]): Every row, the biggest first. Default: none.
        failing (tuple[FailingSource, ...]): Every failing source, the worst first. Default: none.
        skipped (tuple[SkippedFile, ...]): The refused files, ordered by path. Default: none.
        skipped_by_reason (tuple[tuple[Reason, int], ...]): The refusals counted per reason, the
            most frequent first. Default: none.
        duplicates (int): Reports dropped as already seen. Default: 0.
        other_domain (int): Reports dropped for belonging to another domain. Default: 0.
        passed_over (int): Files a folder search did not read for a name that is not the
            providers', although the suffix is a report's. Default: 0.
        days (tuple[DayCounts, ...]): The messages per UTC day a report begins on, sorted by day,
            only the days on which a report begins; internal, the ``--json`` documents do not carry
            it. Default: none.
        covered (tuple[tuple[date, date], ...]): The merged ``[first, last]`` intervals of the days
            some report covers for at least ``MIN_COVERED_SECONDS``, the list
            ``period.days_with_reports`` is counted from. Default: none.
        reporter_activity (tuple[ReporterActivity, ...]): One entry per reporting organization, the
            one with most messages first. Default: none.
        without_reporter (tuple[WithoutReporter, ...]): One entry per reporting organization, in
            the order of ``reporter_activity``: what the rules of the verdict would measure without
            its reports (spec 011); internal, the ``--json`` documents do not carry it. Default:
            none.
    """

    domain: str
    selectors_configured: int = 0
    spf_domains_configured: int = 0
    ip_ranges_configured: int = 0
    reports: int = 0
    reporters: int = 0
    period: Period | None = None
    policy: PolicyPublished | None = None
    earlier_p: tuple[str, ...] = ()
    totals: Counts = Counts()
    recognized_messages: int = 0
    senders: tuple[SenderRow, ...] = ()
    failing: tuple[FailingSource, ...] = ()
    skipped: tuple[SkippedFile, ...] = ()
    skipped_by_reason: tuple[tuple[Reason, int], ...] = ()
    duplicates: int = 0
    other_domain: int = 0
    passed_over: int = 0
    days: tuple[DayCounts, ...] = ()
    covered: tuple[tuple[date, date], ...] = ()
    reporter_activity: tuple[ReporterActivity, ...] = ()
    without_reporter: tuple[WithoutReporter, ...] = ()


# ---------------------------------------------------------------------------
# Classification (RF-01)
# ---------------------------------------------------------------------------


def _passes(value: str) -> bool:
    """
    Tell whether a result string means ``pass``.

    Args:
        value (str): A result as the receiver wrote it.

    Returns:
        bool: True for ``pass`` in any case with any surrounding spaces; empty and anything else is
            not a pass, which is the safe reading of a missing result.
    """
    return value.strip().lower() == "pass"


def _mechanisms(record: Record) -> tuple[bool, bool]:
    """
    Read the two evaluated results of a record.

    Args:
        record (Record): The row of the report.

    Returns:
        tuple[bool, bool]: Whether DKIM passed and whether SPF passed, as evaluated for DMARC.
    """
    return _passes(record.dkim_evaluated), _passes(record.spf_evaluated)


def classify(record: Record) -> Situation:
    """
    Say how well a record authenticated.

    Only the two evaluated results decide: the disposition and the override reasons do not (under
    ``p=none`` everything is delivered, which says nothing about authentication).

    Args:
        record (Record): The row of the report.

    Returns:
        Situation: ``OK`` when both passed, ``FRAGILE`` when one did, ``FAILING`` when neither did.
    """
    dkim_ok, spf_ok = _mechanisms(record)
    if dkim_ok and spf_ok:
        return Situation.OK
    if dkim_ok or spf_ok:
        return Situation.FRAGILE
    return Situation.FAILING


# ---------------------------------------------------------------------------
# Accumulators (private, frozen into the model at the end)
# ---------------------------------------------------------------------------


class _Tally:
    """Messages per situation while the records are being added up."""

    __slots__ = ("dkim_only", "failing", "ok", "spf_only")

    def __init__(self) -> None:
        """Start with nothing counted."""
        self.ok = 0
        self.dkim_only = 0
        self.spf_only = 0
        self.failing = 0

    def add(self, dkim_ok: bool, spf_ok: bool, count: int) -> None:
        """
        Count the messages of one record under its situation.

        Args:
            dkim_ok (bool): Whether DKIM passed as evaluated.
            spf_ok (bool): Whether SPF passed as evaluated.
            count (int): The messages of the record.
        """
        if dkim_ok and spf_ok:
            self.ok += count
        elif dkim_ok:
            self.dkim_only += count
        elif spf_ok:
            self.spf_only += count
        else:
            self.failing += count

    def freeze(self) -> Counts:
        """
        Build the immutable counts.

        Returns:
            Counts: What was added.
        """
        return Counts(self.ok, self.dkim_only, self.spf_only, self.failing)


class _Row:
    """One sender row while it is being added up."""

    __slots__ = ("outcome", "selectors", "service", "source_ip", "spf_domains", "tally")

    def __init__(self, outcome: Outcome, service: str, source_ip: str) -> None:
        """
        Start an empty row.

        Args:
            outcome (Outcome): What identification said.
            service (str): The service name when ``KNOWN``, else empty.
            source_ip (str): The address when not ``KNOWN``, else empty.
        """
        self.outcome = outcome
        self.service = service
        self.source_ip = source_ip
        self.selectors: set[str] = set()
        self.spf_domains: set[str] = set()
        self.tally = _Tally()


class _Source:
    """One failing source while it is being added up."""

    __slots__ = ("dkim", "messages", "override_reasons", "row", "selectors", "spf", "spf_domains")

    def __init__(self, row: _Row) -> None:
        """
        Start an empty source.

        Args:
            row (_Row): The row it belongs to, for the outcome and the service name.
        """
        self.row = row
        self.messages = 0
        self.selectors: set[str] = set()
        self.spf_domains: set[str] = set()
        self.dkim: set[str] = set()
        self.spf: set[str] = set()
        self.override_reasons: set[str] = set()


class _Reporters:
    """What each reporting organization sent while the reports are being added up (spec 011)."""

    __slots__ = ("failing", "first_begin", "known_failing", "last_day", "messages")

    def __init__(self) -> None:
        """Start with no organization."""
        self.messages: Counter[str] = Counter()
        self.known_failing: Counter[str] = Counter()
        self.failing: Counter[str] = Counter()
        self.first_begin: dict[str, datetime] = {}
        self.last_day: dict[str, date] = {}

    def add_report(self, report: Report) -> None:
        """
        Widen the bounds of the organization of one report.

        Args:
            report (Report): The report.
        """
        name = report.reporter
        last = _days_touched(report)[1]
        self.first_begin[name] = min(report.begin, self.first_begin.get(name, report.begin))
        self.last_day[name] = max(last, self.last_day.get(name, last))

    def add_record(self, name: str, count: int, known: bool, failing: bool) -> None:
        """
        Count the messages of one record for its organization.

        Args:
            name (str): The organization of the report.
            count (int): The messages of the record, more than zero.
            known (bool): Whether the record came from a recognized sender.
            failing (bool): Whether neither DKIM nor SPF passed.
        """
        self.messages[name] += count
        if failing:
            self.failing[name] += count
            if known:
                self.known_failing[name] += count


def _owner_spf_domains(record: Record, domain: str) -> set[str]:
    """
    Collect the SPF domains that passed under the owner's domain: the ones ``[spf]`` could name.

    Args:
        record (Record): The row of the report.
        domain (str): The configured domain.

    Returns:
        set[str]: The normalized domains; empty when no SPF block qualifies.
    """
    return {
        normalize_domain(block.domain)
        for block in record.spf
        if block.result.strip().lower() == "pass" and is_within_domain(block.domain, domain)
    }


def _reason(results: Iterable[str]) -> str:
    """
    Say why a mechanism did not count for a failing record (ADR-2).

    Args:
        results (Iterable[str]): The results of the raw ``auth_results`` blocks of the mechanism.

    Returns:
        str: ``unaligned`` when a block passed (for a domain other than the ``From`` domain),
            ``fail`` when there are blocks and none passed, ``none`` when there are no blocks.
    """
    seen = False
    for result in results:
        if _passes(result):
            return "unaligned"
        seen = True
    return "fail" if seen else "none"


# ---------------------------------------------------------------------------
# Period, policy and reporters (RF-03)
# ---------------------------------------------------------------------------


def _days_touched(report: Report) -> tuple[date, date]:
    """
    Find the first and the last UTC day a report touches (ADR-3).

    Args:
        report (Report): The report.

    Returns:
        tuple[date, date]: The day ``begin`` falls on and the day of ``end`` minus one microsecond.
            The end of a period is exclusive, so a report from midnight to the next midnight touches
            one day, as one ending at 23:59:59 does. A report of zero length counts for the day of
            ``begin``.
    """
    first = report.begin.date()
    if report.end <= report.begin:
        return first, first
    return first, (report.end - timedelta(microseconds=1)).date()


def _merged(reports: Iterable[Report]) -> list[tuple[datetime, datetime]]:
    """
    Merge the periods of the reports in time, so that overlaps are not added twice.

    Args:
        reports (Iterable[Report]): The reports.

    Returns:
        list[tuple[datetime, datetime]]: The ``[begin, end)`` spans, ordered, none touching the
            next; a report of zero length covers nothing and gives no span.
    """
    spans = sorted((report.begin, report.end) for report in reports if report.end > report.begin)
    merged: list[tuple[datetime, datetime]] = []
    for begin, end in spans:
        if merged and begin <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((begin, end))
    return merged


def _on_days(
    begin: datetime, end: datetime
) -> tuple[tuple[tuple[date, int], ...], tuple[date, date] | None]:
    """
    Split a span of time by UTC day: the seconds on its end days and the whole days between.

    Only the first and the last day of a span can be partly covered; the days between are covered
    whole, so they are one range and not a loop over the length of the span (RNF-09). The coverage
    of the run and the time one organization covers alone are both split here, so they cannot
    disagree about a day (spec 011, ADR-3).

    Args:
        begin (datetime): Start of the span, UTC.
        end (datetime): End of the span, exclusive, after ``begin``.

    Returns:
        tuple[tuple[tuple[date, int], ...], tuple[date, date] | None]: The ``(day, seconds)`` of
            the first and the last day (one pair when the span stays in one day), and the
            ``[first, last]`` range of the whole days between them, ``None`` when there is none.
    """
    first = begin.date()
    last = (end - timedelta(microseconds=1)).date()
    if first == last:
        return ((first, int((end - begin).total_seconds())),), None
    next_midnight = datetime.combine(first + timedelta(days=1), time.min, tzinfo=UTC)
    last_midnight = datetime.combine(last, time.min, tzinfo=UTC)
    ends = (
        (first, int((next_midnight - begin).total_seconds())),
        (last, int((end - last_midnight).total_seconds())),
    )
    if (last - first).days > 1:
        return ends, (first + timedelta(days=1), last - timedelta(days=1))
    return ends, None


def _day_seconds(
    merged: list[tuple[datetime, datetime]],
) -> tuple[Counter[date], list[tuple[date, date]]]:
    """
    Read the seconds the merged spans cover on each day they cover only in part.

    Args:
        merged (list[tuple[datetime, datetime]]): The spans from ``_merged``.

    Returns:
        tuple[Counter[date], list[tuple[date, date]]]: The seconds per end day of a span, added
            when several spans share a day, and the ranges of the days covered whole.
    """
    seconds: Counter[date] = Counter()
    whole: list[tuple[date, date]] = []
    for begin, end in merged:
        ends, inner = _on_days(begin, end)
        for day, covered in ends:
            seconds[day] += covered
        if inner is not None:
            whole.append(inner)
    return seconds, whole


def _intervals(
    seconds: Counter[date], whole: list[tuple[date, date]]
) -> tuple[tuple[date, date], ...]:
    """
    Join the days covered enough into ``[first, last]`` intervals.

    Args:
        seconds (Counter[date]): The seconds per day covered in part, from ``_day_seconds``.
        whole (list[tuple[date, date]]): The ranges of the days covered whole.

    Returns:
        tuple[tuple[date, date], ...]: The intervals, ordered, with at least one day between two
            of them. Days that follow each other are one interval, so a gap is exactly a hole.
    """
    ranges = [*whole]
    ranges.extend((day, day) for day, covered in seconds.items() if covered >= MIN_COVERED_SECONDS)
    intervals: list[tuple[date, date]] = []
    for first, last in sorted(ranges):
        if intervals and (first - intervals[-1][1]).days <= 1:
            intervals[-1] = (intervals[-1][0], max(intervals[-1][1], last))
        else:
            intervals.append((first, last))
    return tuple(intervals)


def _covered(
    merged: list[tuple[datetime, datetime]],
) -> tuple[tuple[tuple[date, date], ...], Counter[date]]:
    """
    Find the UTC days the reports cover, as ``[first, last]`` intervals.

    A day counts only when the periods of the reports, merged so that overlaps are not added twice,
    cover at least ``MIN_COVERED_SECONDS`` of it. Touching a day is not covering it: with reports
    that do not start at midnight, a report that never arrived would otherwise leave both
    neighbouring days looking complete.

    The days are kept as intervals, never as a set of days (RNF-09); only the days some report
    touches are visited, so the work follows the reports, not the distance between them. Rule 2 of
    the verdict and the timeline of the HTML report both read this list, so they cannot disagree
    about which days have a report (spec 008, ADR-3).

    Args:
        merged (list[tuple[datetime, datetime]]): The merged periods of the reports, from
            ``_merged``.

    Returns:
        tuple[tuple[tuple[date, date], ...], Counter[date]]: The intervals, ordered, with at least
            one day between two of them (empty without reports or when no day is covered enough),
            and the seconds of the days covered in part, which the time one organization covers
            alone is taken from (spec 011, ADR-3), so the two cannot disagree about a day.
    """
    seconds, whole = _day_seconds(merged)
    return _intervals(seconds, whole), seconds


def _period(reports: tuple[Report, ...], covered: tuple[tuple[date, date], ...]) -> Period | None:
    """
    Build the period the reports cover.

    Args:
        reports (tuple[Report, ...]): The reports kept.
        covered (tuple[tuple[date, date], ...]): The days covered enough, from ``_covered``.

    Returns:
        Period | None: The period, or ``None`` without reports. It runs from the day the earliest
            report begins to the last day any report touches, whether or not those days are
            covered enough.
    """
    if not reports:
        return None
    first_day = min(report.begin for report in reports).date()
    last_day = max(_days_touched(report)[1] for report in reports)
    return Period(
        begin=min(report.begin for report in reports),
        end=max(report.end for report in reports),
        first_day=first_day,
        last_day=last_day,
        days_spanned=(last_day - first_day).days + 1,
        days_with_reports=sum((last - first).days + 1 for first, last in covered),
    )


def _activity(reports: tuple[Report, ...]) -> tuple[ReporterActivity, ...]:
    """
    Sum the messages and find the last end of each reporting organization.

    Args:
        reports (tuple[Report, ...]): The reports kept.

    Returns:
        tuple[ReporterActivity, ...]: One per organization, most messages first, then by name.
    """
    messages: Counter[str] = Counter()
    last_end: dict[str, datetime] = {}
    for report in reports:
        messages[report.reporter] += sum(max(record.count, 0) for record in report.records)
        last_end[report.reporter] = max(report.end, last_end.get(report.reporter, report.end))
    return tuple(
        ReporterActivity(name, messages[name], last_end[name])
        for name in sorted(messages, key=lambda name: (-messages[name], name))
    )


# ---------------------------------------------------------------------------
# Without each organization (spec 011, ADR-2, ADR-3)
# ---------------------------------------------------------------------------


def _exclusive(reports: tuple[Report, ...]) -> dict[str, list[tuple[datetime, datetime]]]:
    """
    Find the stretches of time where exactly one organization has a report open (ADR-3).

    One sweep over the start and the end of every period, with a count of the reports each
    organization has open: two events per report, so the work follows the reports and not the
    distance between them. A report of zero length covers nothing and gives no event.

    Args:
        reports (tuple[Report, ...]): The reports kept.

    Returns:
        dict[str, list[tuple[datetime, datetime]]]: Per organization that covers some time alone,
            its ``[begin, end)`` stretches, ordered and never overlapping.
    """
    events = sorted(
        (
            event
            for report in reports
            if report.end > report.begin
            for event in ((report.begin, 1, report.reporter), (report.end, -1, report.reporter))
        ),
        key=lambda event: event[0],
    )
    open_reports: Counter[str] = Counter()
    active: set[str] = set()
    stretches: dict[str, list[tuple[datetime, datetime]]] = {}
    previous: datetime | None = None
    index = 0
    while index < len(events):
        moment = events[index][0]
        # why: the time since the last event belongs to whoever was open before this one
        if previous is not None and len(active) == 1:
            (only,) = active
            stretches.setdefault(only, []).append((previous, moment))
        # Every event at one moment is applied before the next stretch is measured, so a report
        # that ends where another begins leaves no gap and no stretch of zero length.
        while index < len(events) and events[index][0] == moment:
            _moment, delta, name = events[index]
            open_reports[name] += delta
            if open_reports[name]:
                active.add(name)
            else:
                active.discard(name)
            index += 1
        previous = moment
    return stretches


def _lost_days(
    stretches: list[tuple[datetime, datetime]],
    spans: tuple[list[date], list[date]],
    seconds: Counter[date],
) -> int:
    """
    Count the covered days a run would lose without the time one organization covers alone.

    A whole day inside a stretch is lost (no one else covers any of it). A day where a stretch
    begins or ends keeps the seconds the merged periods give it today minus the seconds covered
    alone, and is lost when it was covered enough and the rest is not.

    Args:
        stretches (list[tuple[datetime, datetime]]): The time the organization covers alone.
        spans (tuple[list[date], list[date]]): The first and the last day of each merged period
            of every report, in the order of ``_merged``.
        seconds (Counter[date]): The seconds of the days the merged periods cover in part.

    Returns:
        int: The days to take from ``days_with_reports``.
    """
    firsts, lasts = spans
    lost = 0
    alone: Counter[date] = Counter()
    for begin, end in stretches:
        ends, inner = _on_days(begin, end)
        for day, covered in ends:
            alone[day] += covered
        if inner is not None:
            lost += (inner[1] - inner[0]).days + 1
    for day, covered in alone.items():
        # why: a day strictly between the end days of a merged period is covered whole today,
        # and the merged periods never overlap, so the last one beginning before it is the one
        index = bisect_left(firsts, day) - 1
        today = 24 * 3600 if index >= 0 and day < lasts[index] else seconds[day]
        if today >= MIN_COVERED_SECONDS > today - covered:
            lost += 1
    return lost


def _without_reporter(
    reports: tuple[Report, ...],
    activity: tuple[ReporterActivity, ...],
    tallies: _Reporters,
    totals: Counts,
    coverage: tuple[Period | None, list[tuple[datetime, datetime]], Counter[date]],
) -> tuple[WithoutReporter, ...]:
    """
    Measure the run without each organization from its tallies and one sweep (ADR-2, ADR-3).

    Removing reports can only remove covered time, and the time it removes is exactly the time no
    other organization covered. The bounds of the period without an organization are the first of
    the others in two lists sorted once. The work is a sort and a sweep over the reports, never a
    summary per organization.

    Args:
        reports (tuple[Report, ...]): The reports kept.
        activity (tuple[ReporterActivity, ...]): The organizations, in the order of the result.
        tallies (_Reporters): What each organization sent, from the loop of ``summarize``.
        totals (Counts): All the messages of the run per situation.
        coverage (tuple[Period | None, list[tuple[datetime, datetime]], Counter[date]]): The
            period of the run (``None`` only without reports), its merged periods and the seconds
            of the days they cover in part, as ``summarize`` computed them for the run.

    Returns:
        tuple[WithoutReporter, ...]: One entry per organization, in the order of ``activity``.
    """
    period, merged, seconds = coverage
    if period is None:
        return ()
    spans = (
        [begin.date() for begin, _end in merged],
        [(end - timedelta(microseconds=1)).date() for _begin, end in merged],
    )
    stretches = _exclusive(reports)
    # why: the bound of the others is the first of each list that is not the organization itself,
    # so two lists sorted once serve every organization
    by_begin = sorted(tallies.first_begin, key=lambda name: (tallies.first_begin[name], name))[:2]
    by_last = sorted(tallies.last_day, key=lambda name: (-tallies.last_day[name].toordinal(), name))
    by_last = by_last[:2]
    known_failing = sum(tallies.known_failing.values())

    entries = []
    for entry in activity:
        name = entry.name
        first_other = next((other for other in by_begin if other != name), None)
        last_other = next((other for other in by_last if other != name), None)
        if first_other is None or last_other is None:
            days, with_reports = 0, 0
        else:
            days = (tallies.last_day[last_other] - tallies.first_begin[first_other].date()).days + 1
            lost = _lost_days(stretches.get(name, []), spans, seconds)
            with_reports = period.days_with_reports - lost
        known = known_failing - tallies.known_failing[name]
        entries.append(
            WithoutReporter(
                name=name,
                messages=tallies.messages[name],
                days_spanned=days,
                days_with_reports=with_reports,
                total=totals.total - tallies.messages[name],
                recognized_failing=known,
                unrecognized_failing=totals.failing - tallies.failing[name] - known,
            )
        )
    return tuple(entries)


def _policy(reports: tuple[Report, ...]) -> tuple[PolicyPublished | None, tuple[str, ...]]:
    """
    Pick the latest published policy and the other ``p`` values seen before it.

    Args:
        reports (tuple[Report, ...]): The reports kept.

    Returns:
        tuple[PolicyPublished | None, tuple[str, ...]]: The policy of the latest report (``None``
            without reports) and the distinct ``p`` values of the others that differ from the latest
            one, oldest first. The order does not depend on the order of the input.
    """
    if not reports:
        return None, ()
    ordered = sorted(
        reports, key=lambda report: (report.end, report.begin, report.reporter, report.report_id)
    )
    latest = ordered[-1].policy
    earlier: list[str] = []
    for report in ordered[:-1]:
        if report.policy.p != latest.p and report.policy.p not in earlier:
            earlier.append(report.policy.p)
    return latest, tuple(earlier)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def summarize(result: IngestionResult, config: Config) -> Summary:
    """
    Add up the reports of one domain.

    One pass over the records, with memory proportional to the number of distinct sources (RNF-09).
    A record with no messages adds nothing. The rows and the failing sources are sorted so that the
    same reports in any order give an equal summary (RNF-05).

    Args:
        result (IngestionResult): What ``ingest`` kept.
        config (Config): The configuration: the domain and the selector map.

    Returns:
        Summary: The complete data; limiting and printing it belong to the renderer.
    """
    rows: dict[tuple[Outcome, str, str], _Row] = {}
    sources: dict[tuple[Outcome, str, str, str], _Source] = {}
    totals = _Tally()
    recognized = 0
    day_reports: Counter[date] = Counter()
    day_tallies: dict[date, _Tally] = {}
    reporters = _Reporters()

    for report in result.reports:
        reporters.add_report(report)
        # 0. The messages of a report go to the day its period begins (spec 008, ADR-3).
        begin_day = report.begin.date()
        day_reports[begin_day] += 1
        day_tally = day_tallies.setdefault(begin_day, _Tally())
        for record in report.records:
            if record.count <= 0:
                continue
            dkim_ok, spf_ok = _mechanisms(record)
            identification = identify_sender(record, config)
            known = identification.outcome is Outcome.KNOWN

            # 1. A recognized sender is one row by name; the rest are one row per address.
            service = identification.service if known else ""
            row_ip = "" if known else record.source_ip
            key = (identification.outcome, service, row_ip)
            row = rows.get(key)
            if row is None:
                row = rows[key] = _Row(identification.outcome, service, row_ip)
            row.tally.add(dkim_ok, spf_ok, record.count)
            totals.add(dkim_ok, spf_ok, record.count)
            day_tally.add(dkim_ok, spf_ok, record.count)
            reporters.add_record(report.reporter, record.count, known, not (dkim_ok or spf_ok))
            spf_domains = set() if known else _owner_spf_domains(record, config.domain)
            if known:
                recognized += record.count
            else:
                if identification.selector:
                    row.selectors.add(identification.selector)
                row.spf_domains.update(spf_domains)

            # 2. A failing record also counts for the address it came from.
            if dkim_ok or spf_ok:
                continue
            source_key = (*key, record.source_ip)
            source = sources.get(source_key)
            if source is None:
                source = sources[source_key] = _Source(row)
            source.messages += record.count
            if not known and identification.selector:
                source.selectors.add(identification.selector)
            source.spf_domains.update(spf_domains)
            source.dkim.add(_reason(block.result for block in record.dkim))
            source.spf.add(_reason(block.result for block in record.spf))
            source.override_reasons.update(
                reason.type.strip() for reason in record.override_reasons if reason.type.strip()
            )

    senders = tuple(
        sorted(
            (
                SenderRow(
                    row.outcome,
                    row.service,
                    row.source_ip,
                    tuple(sorted(row.selectors)),
                    row.tally.freeze(),
                    tuple(sorted(row.spf_domains)),
                )
                for row in rows.values()
            ),
            key=lambda row: (-row.counts.total, row.service or row.source_ip, row.outcome.value),
        )
    )
    failing = tuple(
        sorted(
            (
                FailingSource(
                    source.row.outcome,
                    ip,
                    source.messages,
                    source.row.service,
                    tuple(sorted(source.selectors)),
                    tuple(sorted(source.dkim)),
                    tuple(sorted(source.spf)),
                    tuple(sorted(source.override_reasons)),
                    tuple(sorted(source.spf_domains)),
                )
                for (_outcome, _service, _row_ip, ip), source in sources.items()
            ),
            key=lambda source: (
                -source.messages,
                source.service or source.source_ip,
                source.source_ip,
                source.outcome.value,
            ),
        )
    )

    policy, earlier_p = _policy(result.reports)
    reasons = Counter(file.reason for file in result.skipped)
    merged = _merged(result.reports)
    covered, seconds = _covered(merged)
    period = _period(result.reports, covered)
    activity = _activity(result.reports)
    total_counts = totals.freeze()

    return Summary(
        domain=config.domain,
        selectors_configured=len(config.senders),
        spf_domains_configured=len(config.spf),
        ip_ranges_configured=len(config.ranges),
        reports=len(result.reports),
        reporters=len({report.reporter for report in result.reports}),
        period=period,
        policy=policy,
        earlier_p=earlier_p,
        totals=total_counts,
        recognized_messages=recognized,
        senders=senders,
        failing=failing,
        skipped=tuple(sorted(result.skipped, key=lambda file: str(file.path))),
        skipped_by_reason=tuple(
            sorted(reasons.items(), key=lambda item: (-item[1], item[0].value))
        ),
        duplicates=result.duplicates,
        other_domain=result.other_domain,
        passed_over=result.passed_over,
        days=tuple(
            DayCounts(day, day_reports[day], day_tallies[day].freeze())
            for day in sorted(day_tallies)
        ),
        covered=covered,
        reporter_activity=activity,
        without_reporter=_without_reporter(
            result.reports, activity, reporters, total_counts, (period, merged, seconds)
        ),
    )
