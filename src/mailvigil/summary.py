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

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from mailvigil.config import Config
from mailvigil.reports import IngestionResult, PolicyPublished, Reason, Record, SkippedFile
from mailvigil.senders import Outcome, identify_sender

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
    """

    outcome: Outcome
    service: str = ""
    source_ip: str = ""
    selectors: tuple[str, ...] = ()
    counts: Counts = Counts()


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
    """

    outcome: Outcome
    source_ip: str
    messages: int
    service: str = ""
    selectors: tuple[str, ...] = ()
    dkim: tuple[str, ...] = ()
    spf: tuple[str, ...] = ()
    override_reasons: tuple[str, ...] = ()


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
class Summary:
    """
    Everything the reports of one domain say, added up.

    Attributes:
        domain (str): The domain the reports are about.
        selectors_configured (int): How many selectors the configuration maps. Default: 0.
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
    """

    domain: str
    selectors_configured: int = 0
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

    __slots__ = ("outcome", "selectors", "service", "source_ip", "tally")

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
        self.tally = _Tally()


class _Source:
    """One failing source while it is being added up."""

    __slots__ = ("dkim", "messages", "override_reasons", "row", "selectors", "spf")

    def __init__(self, row: _Row) -> None:
        """
        Start an empty source.

        Args:
            row (_Row): The row it belongs to, for the outcome and the service name.
        """
        self.row = row
        self.messages = 0
        self.selectors: set[str] = set()
        self.dkim: set[str] = set()
        self.spf: set[str] = set()
        self.override_reasons: set[str] = set()


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

    for report in result.reports:
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
            if known:
                recognized += record.count
            elif identification.selector:
                row.selectors.add(identification.selector)

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

    return Summary(
        domain=config.domain,
        selectors_configured=len(config.senders),
        totals=totals.freeze(),
        recognized_messages=recognized,
        senders=senders,
        failing=failing,
    )
