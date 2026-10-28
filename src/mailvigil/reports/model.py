"""
The immutable record model of a DMARC aggregate report.

The model keeps what the report said, not what it means: the evaluated results stay raw strings, and
turning them into ``ok`` / ``fragile`` / ``failing`` or into a sender name belongs to later specs.
Every type is a frozen dataclass and every collection is a tuple. Text fields are already sanitized
by the parser, so any caller may print them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from mailvigil.reports.errors import Reason

# ---------------------------------------------------------------------------
# One record (a row of the report)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DkimResult:
    """
    One ``auth_results/dkim`` block.

    Attributes:
        domain (str): The ``d=`` domain of the signature.
        selector (str): The ``s=`` selector, the main clue to which service signed.
        result (str): The DKIM verdict as the receiver reported it (``pass``, ``fail``, …).
    """

    domain: str = ""
    selector: str = ""
    result: str = ""


@dataclass(frozen=True, slots=True)
class SpfResult:
    """
    One ``auth_results/spf`` block.

    Attributes:
        domain (str): The domain SPF was checked against.
        result (str): The SPF verdict as the receiver reported it.
    """

    domain: str = ""
    result: str = ""


@dataclass(frozen=True, slots=True)
class OverrideReason:
    """
    One ``policy_evaluated/reason`` block: why the receiver overrode the policy.

    Attributes:
        type (str): The reason type (``forwarded``, ``mailing_list``, …).
        comment (str): The receiver's free-text comment, sanitized.
    """

    type: str = ""
    comment: str = ""


@dataclass(frozen=True, slots=True)
class Record:
    """
    One ``record`` of the report: a group of messages with the same source and results.

    Attributes:
        source_ip (str): Normalized by ``ipaddress`` when valid, otherwise sanitized as given.
        count (int): The number of messages, zero or more.
        disposition (str): What the receiver did with them. Default: ``none``.
        dkim_evaluated (str): ``policy_evaluated/dkim``: ``pass``, ``fail`` or empty.
        spf_evaluated (str): ``policy_evaluated/spf``: ``pass``, ``fail`` or empty.
        override_reasons (tuple[OverrideReason, ...]): The overrides the receiver gave.
        header_from (str): The ``From`` domain of the messages, lower case.
        dkim (tuple[DkimResult, ...]): Every DKIM block, in document order.
        spf (tuple[SpfResult, ...]): Every SPF block, in document order.
    """

    source_ip: str = ""
    count: int = 0
    disposition: str = "none"
    dkim_evaluated: str = ""
    spf_evaluated: str = ""
    override_reasons: tuple[OverrideReason, ...] = ()
    header_from: str = ""
    dkim: tuple[DkimResult, ...] = ()
    spf: tuple[SpfResult, ...] = ()


# ---------------------------------------------------------------------------
# One report
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PolicyPublished:
    """
    The DMARC policy the domain had published when the report was made.

    Attributes:
        domain (str): The domain the policy belongs to, lower case.
        p (str): The policy, ``?`` when the report does not say.
        sp (str): The subdomain policy, empty when absent.
        np (str): The policy for non-existent subdomains (RFC 9990), empty when absent.
        adkim (str): DKIM alignment mode, empty when absent.
        aspf (str): SPF alignment mode, empty when absent.
        testing (str): The testing flag (RFC 9990), empty when absent.
        discovery_method (str): How the policy was found (RFC 9990), empty when absent.
        pct (int): The sampling percentage, 0 to 100. Default: 100, which is also what a report
            without ``pct`` (RFC 9990 dropped it) means.
    """

    domain: str
    p: str = "?"
    sp: str = ""
    np: str = ""
    adkim: str = ""
    aspf: str = ""
    testing: str = ""
    discovery_method: str = ""
    pct: int = 100


@dataclass(frozen=True, slots=True)
class Report:
    """
    A parsed aggregate report.

    Attributes:
        reporter (str): The reporting organization, ``?`` when absent.
        report_id (str): The id the reporter gave this report; unique per reporter only.
        begin (datetime): Start of the period, timezone-aware, UTC.
        end (datetime): End of the period, timezone-aware, UTC, never before ``begin``.
        policy (PolicyPublished): The published policy.
        records (tuple[Record, ...]): The rows, in document order.
        source_file (str): The file name it came from, for display only.
    """

    reporter: str
    report_id: str
    begin: datetime
    end: datetime
    policy: PolicyPublished
    records: tuple[Record, ...]
    source_file: str


# ---------------------------------------------------------------------------
# The outcome of an ingestion
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SkippedFile:
    """
    A file that was refused, and why.

    Attributes:
        path (Path): The file as the caller or the folder listing gave it.
        reason (Reason): The machine-readable cause.
        detail (str): A short English explanation, for logs.
    """

    path: Path
    reason: Reason
    detail: str


@dataclass(frozen=True, slots=True)
class IngestionResult:
    """
    What ``ingest`` found.

    Whether an empty ``reports`` is an error is the caller's decision.

    Attributes:
        reports (tuple[Report, ...]): The reports kept, in discovery order.
        skipped (tuple[SkippedFile, ...]): The refused files, in discovery order.
        duplicates (int): Reports dropped for repeating a reporter and report id already kept.
        other_domain (int): Reports dropped for belonging to a different domain.
    """

    reports: tuple[Report, ...] = ()
    skipped: tuple[SkippedFile, ...] = ()
    duplicates: int = 0
    other_domain: int = 0
