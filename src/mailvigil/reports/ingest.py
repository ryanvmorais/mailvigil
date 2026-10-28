"""
Ingestion: the one entry point that turns paths into the reports of a domain.

``ingest`` runs discovery, the reader and the parser over every file, keeps the reports of the
wanted domain, drops the ones already seen, and records every file it had to refuse. A file is a
loose report (``.xml``, ``.gz``, ``.zip``), a mail message (``.eml``) or a mailbox (``.mbox``); the
last two hold zero or more attachments, each of which goes through the same reader and parser as a
loose file (007). A refusal is per file, or per attachment, and never global (RF-09): one corrupt
attachment among two hundred good ones costs one line in ``skipped``, not the run. Whether an empty
result is an error is the caller's call.
"""

from __future__ import annotations

import stat
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from mailvigil.reports.discovery import Source, discover
from mailvigil.reports.errors import Reason, ReportRefused
from mailvigil.reports.mail import iter_mailbox, read_message, read_message_file
from mailvigil.reports.model import IngestionResult, Report, SkippedFile
from mailvigil.reports.parser import parse_report
from mailvigil.reports.reader import read_xml, read_xml_bytes
from mailvigil.text import normalize_domain

# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Document:
    """
    What the loop of ``ingest`` parses: the XML of one report and where it came from.

    Attributes:
        xml (bytes): The report, with any archive already opened.
        source (str): The display origin, which becomes ``Report.source_file``.
        part (str): The message and attachment it came from (``#3 report.zip``), empty for a loose
            file; it goes on the refusal if the parser rejects the XML.
    """

    xml: bytes
    source: str
    part: str


def _part(number: int | None, name: str) -> str:
    """
    Name a piece of a mail file: the message of a mailbox and the attachment, in one place.

    Args:
        number (int | None): The message number in a mailbox, ``None`` for an ``.eml``.
        name (str): The attachment name, empty when it has none.

    Returns:
        str: ``#3 report.zip``, ``#3``, ``report.zip`` or an empty string, whichever apply.
    """
    return " ".join(piece for piece in (f"#{number}" if number else "", name) if piece)


def _from_message(
    source: Source, raw: bytes, number: int | None
) -> Iterator[_Document | SkippedFile]:
    """
    Turn one message into one document per candidate attachment.

    Args:
        source (Source): The ``.eml`` or ``.mbox`` the message is in.
        raw (bytes): The message.
        number (int | None): Its number in a mailbox, ``None`` for an ``.eml``.

    Yields:
        _Document | SkippedFile: A document for each attachment the reader opens, and a refusal for
            each it does not; one refusal for the whole message when it is too large or too
            complex. A message with no candidate says something only when it is an ``.eml`` the
            user named: a folder or a mailbox holds mail of every kind (RF-02).
    """
    try:
        attachments = read_message(raw)
    except ReportRefused as refused:
        yield SkippedFile(source.path, refused.reason, refused.detail, _part(number, ""))
        return
    if not attachments and number is None and source.explicit:
        yield SkippedFile(source.path, Reason.NO_REPORT_ATTACHMENT, "no attachment is a report")
    for attachment in attachments:
        part = _part(number, attachment.name)
        try:
            xml = read_xml_bytes(attachment.data, attachment.kind)
        except ReportRefused as refused:
            yield SkippedFile(source.path, refused.reason, refused.detail, part)
            continue
        yield _Document(xml, f"{source.path.name}: {part}" if part else source.path.name, part)


def _from_mailbox(source: Source) -> Iterator[_Document | SkippedFile]:
    """
    Read a mailbox one message at a time.

    Args:
        source (Source): The ``.mbox``.

    Yields:
        _Document | SkippedFile: What ``_from_message`` yields for each message, with its number; a
            message the splitter refused (too large) as one refusal; or ``UNREADABLE`` once if the
            file cannot be opened or read.
    """
    try:
        if not stat.S_ISREG(source.path.stat().st_mode):
            # Opening a pipe or a device could block the run; discovery leaves these to us.
            raise ReportRefused(Reason.UNREADABLE, "not a regular file")
        with source.path.open("rb") as stream:
            for number, message in iter_mailbox(stream):
                if isinstance(message, ReportRefused):
                    yield SkippedFile(
                        source.path, message.reason, message.detail, _part(number, "")
                    )
                else:
                    yield from _from_message(source, message, number)
    except ReportRefused as refused:
        yield SkippedFile(source.path, refused.reason, refused.detail)
    except OSError as error:
        yield SkippedFile(source.path, Reason.UNREADABLE, type(error).__name__)


def _documents(source: Source) -> Iterator[_Document | SkippedFile]:
    """
    Turn one source into the documents to parse, one message at a time.

    Args:
        source (Source): A file ``discover`` found.

    Yields:
        _Document | SkippedFile: In file order, then message order, then attachment order. A loose
            file gives one document or one refusal, as it always has.
    """
    suffix = source.path.suffix.lower()
    if suffix == ".mbox":
        yield from _from_mailbox(source)
    elif suffix == ".eml":
        try:
            raw = read_message_file(source.path)
        except ReportRefused as refused:
            yield SkippedFile(source.path, refused.reason, refused.detail)
            return
        yield from _from_message(source, raw, None)
    else:
        try:
            xml = read_xml(source.path)
        except ReportRefused as refused:
            yield SkippedFile(source.path, refused.reason, refused.detail)
            return
        yield _Document(xml, source.path.name, "")


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

    sources, discovery_skipped = discover(paths)
    skipped = list(discovery_skipped)
    reports: list[Report] = []
    seen: set[tuple[str, str]] = set()
    duplicates = 0
    other_domain = 0

    for source in sources:
        for item in _documents(source):
            if isinstance(item, SkippedFile):
                skipped.append(item)
                continue
            try:
                report = parse_report(item.xml, source=item.source)
            except ReportRefused as refused:
                skipped.append(SkippedFile(source.path, refused.reason, refused.detail, item.part))
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
