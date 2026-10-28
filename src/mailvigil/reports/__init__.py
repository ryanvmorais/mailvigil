"""Reading DMARC aggregate reports safely into a typed record model."""

from mailvigil.reports.discovery import discover
from mailvigil.reports.errors import Reason, ReportRefused
from mailvigil.reports.ingest import ingest
from mailvigil.reports.mail import (
    MAX_DEPTH,
    MAX_LINES,
    MAX_MESSAGE_BYTES,
    MAX_PARTS,
    Attachment,
    iter_mailbox,
    read_message,
    read_message_file,
)
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
from mailvigil.reports.parser import parse_report
from mailvigil.reports.reader import MAX_BYTES, read_xml, read_xml_bytes
from mailvigil.text import MAX_TEXT

__all__ = [
    "MAX_BYTES",
    "MAX_DEPTH",
    "MAX_LINES",
    "MAX_MESSAGE_BYTES",
    "MAX_PARTS",
    "MAX_TEXT",
    "Attachment",
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
    "iter_mailbox",
    "parse_report",
    "read_message",
    "read_message_file",
    "read_xml",
    "read_xml_bytes",
]
