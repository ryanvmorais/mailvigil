"""
Ingestion: the one entry point that turns paths into the reports of a domain.

``ingest`` runs discovery, the reader and the parser over every file, keeps the reports of the
wanted domain, drops the ones already seen, and records every file it had to refuse. A refusal is
per file and never global (RF-09): one corrupt attachment among two hundred good ones costs one line
in ``skipped``, not the run. Whether an empty result is an error is the caller's call.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from mailvigil.reports.discovery import discover
from mailvigil.reports.errors import ReportRefused
from mailvigil.reports.model import IngestionResult, Report, SkippedFile
from mailvigil.reports.parser import parse_report
from mailvigil.reports.reader import read_xml
from mailvigil.text import normalize_domain

# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


def ingest(paths: Sequence[Path], domain: str) -> IngestionResult:
    """
    Read every report under the given paths that belongs to a domain.

    Args:
        paths (Sequence[Path]): Files and folders, as ``discover`` takes them.
        domain (str): The domain whose reports are wanted. Compared exactly and without regard to
            case, so ``mail.example.com`` is not ``example.com``; surrounding spaces and a trailing
            dot are ignored.

    Returns:
        IngestionResult: The reports kept in discovery order, the files refused with their reasons,
            how many reports were dropped as duplicates and how many belonged to another domain.
            Returned even when nothing was kept.

    Raises:
        ValueError: When ``domain`` is empty. That is a mistake in the caller, not a bad input file.
    """
    wanted = normalize_domain(domain)
    if not wanted:
        raise ValueError("domain must not be empty")

    files, discovery_skipped = discover(paths)
    skipped = list(discovery_skipped)
    reports: list[Report] = []
    seen: set[tuple[str, str]] = set()
    duplicates = 0
    other_domain = 0

    for file in files:
        try:
            report = parse_report(read_xml(file), source=file.name)
        except ReportRefused as refused:
            skipped.append(SkippedFile(file, refused.reason, refused.detail))
            continue

        # The domain filter comes first, so a report of another domain is never a duplicate and
        # never hides a later report of the wanted one.
        if report.policy.domain != wanted:
            other_domain += 1
            continue
        # A report id is only unique per reporting organization (RF-08).
        key = (report.reporter, report.report_id)
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        reports.append(report)

    return IngestionResult(tuple(reports), tuple(skipped), duplicates, other_domain)
