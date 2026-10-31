"""
The values behind the examples of ``docs/json-schema.md`` (spec 006, RF-03).

The page shows the real output for these values, and ``test_json_schema_doc.py`` rebuilds it
from here and compares it field by field. Everything is invented: ``example.com``, the service
``Example Mailer`` and the documentation addresses (RNF-06).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from tests.test_render_json import make_summary

from mailvigil.fetch.model import FetchOutcome
from mailvigil.reports import Reason, SkippedFile
from mailvigil.senders import Outcome
from mailvigil.summary import Counts, FailingSource, SenderRow, Summary
from mailvigil.verdict import Verdict, judge

#: The configuration file shown in the summary example.
CONFIG_SOURCE = "mailvigil.toml"


def example_summary() -> Summary:
    """
    Build the summary of the example: 29 days, one recognized sender and three that are not.

    Returns:
        Summary: The summary.
    """
    senders = (
        SenderRow(Outcome.KNOWN, service="Example Mailer", counts=Counts(ok=6300)),
        SenderRow(Outcome.KNOWN, service="Example Mail", counts=Counts(dkim_only=950)),
        SenderRow(Outcome.UNKNOWN, source_ip="203.0.113.5", counts=Counts(failing=40)),
        SenderRow(
            Outcome.FAILING_SIGNATURE,
            source_ip="198.51.100.99",
            selectors=("s1",),
            counts=Counts(dkim_only=25),
        ),
        SenderRow(Outcome.UNKNOWN, source_ip="2001:db8::7", counts=Counts(failing=8)),
    )
    failing = (
        FailingSource(
            Outcome.UNKNOWN,
            "203.0.113.5",
            40,
            dkim=("fail",),
            spf=("fail",),
            override_reasons=("forwarded",),
        ),
        FailingSource(Outcome.UNKNOWN, "2001:db8::7", 8, dkim=("none",), spf=("none",)),
    )
    skipped = (SkippedFile(Path("reports") / "broken.xml", Reason.MALFORMED_XML, "not XML"),)
    return make_summary(
        days=29,
        ok=6300,
        dkim_only=975,
        senders=senders,
        failing=failing,
        sp="reject",
        skipped=skipped,
        duplicates=1,
    )


def example_verdict() -> Verdict:
    """
    Build the verdict of the example: not ready, because of one unrecognized source.

    Returns:
        Verdict: The verdict.
    """
    failing = (
        FailingSource(
            Outcome.UNKNOWN,
            "203.0.113.5",
            56,
            dkim=("fail",),
            spf=("fail",),
            override_reasons=("forwarded",),
        ),
    )
    return judge(
        make_summary(days=29, ok=6000, dkim_only=950, failing=failing, sp="reject", other_domain=2)
    )


def example_fetch() -> FetchOutcome:
    """
    Build the outcome of the example: nine saved, two already on disk and one left for later.

    Returns:
        FetchOutcome: The six numbers.
    """
    return FetchOutcome(matched=12, saved=9, already=2, too_large=0, skipped=0, left=1)


def example_summaries() -> tuple[Summary, Summary]:
    """
    Build the summaries of the several-domains example: a short run and a domain without reports.

    Returns:
        tuple[Summary, Summary]: ``example.com`` with three days of reports, and ``example.net``
            with none.
    """
    return (
        make_summary(days=3, ok=120),
        dataclasses.replace(make_summary(days=0), domain="example.net"),
    )


def example_verdicts() -> tuple[Verdict, Verdict]:
    """
    Build the verdicts of the several-domains example: one not ready and one too early.

    Returns:
        tuple[Verdict, Verdict]: ``example.com`` (the verdict of the example above) and
            ``example.net``, which has no reports; the worst answer is ``not_ready``.
    """
    empty = dataclasses.replace(make_summary(days=0), domain="example.net")
    return example_verdict(), judge(empty)
