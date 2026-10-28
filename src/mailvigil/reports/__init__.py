"""Reading DMARC aggregate reports safely into a typed record model."""

from mailvigil.reports.discovery import discover
from mailvigil.reports.errors import Reason, ReportRefused
from mailvigil.reports.ingest import ingest
from mailvigil.reports.model import (
    DkimResult,
    IngestionResult,
    OverrideReason,
    PolicyPublished,
    Record,
    Report,
    SkippedFile,
    SpfResult,
)
from mailvigil.reports.parser import MAX_TEXT, parse_report
from mailvigil.reports.reader import MAX_BYTES, read_xml

__all__ = [
    "MAX_BYTES",
    "MAX_TEXT",
    "DkimResult",
    "IngestionResult",
    "OverrideReason",
    "PolicyPublished",
    "Reason",
    "Record",
    "Report",
    "ReportRefused",
    "SkippedFile",
    "SpfResult",
    "discover",
    "ingest",
    "parse_report",
    "read_xml",
]
