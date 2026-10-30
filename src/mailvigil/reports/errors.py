"""
The vocabulary of refusals: why a file or a document was not turned into a report.

A refusal is a typed exception carrying a machine-readable ``Reason``. The user-facing text is built
from the reason by a later spec (English and Portuguese); the ``detail`` is for logs and debugging.
"""

from __future__ import annotations

from enum import StrEnum


class Reason(StrEnum):
    """
    Why a file was refused.

    The values are the stable keys later specs translate, so they never change once released.

    Attributes:
        UNSUPPORTED_EXTENSION (str): The suffix is not ``.xml``, ``.gz`` or ``.zip``.
        UNREADABLE (str): Missing, no permission, or not a regular file.
        FILE_TOO_LARGE (str): The size on disk is over the cap.
        DECOMPRESSED_TOO_LARGE (str): The content is over the cap once decompressed.
        NOT_AN_ARCHIVE (str): A corrupt or unsupported zip or gzip.
        NO_XML_MEMBER (str): The zip holds no ``.xml`` member.
        MULTIPLE_XML_MEMBERS (str): The zip holds more than one ``.xml`` member.
        FORBIDDEN_DECLARATION (str): The XML has a ``DOCTYPE`` or an ``ENTITY`` declaration.
        MALFORMED_XML (str): The document is not well-formed XML.
        NOT_A_REPORT (str): Wrong root element, foreign namespace or a missing required block.
        UNSUPPORTED_VERSION (str): The report ``version`` is not ``1.0``.
        INVALID_FIELD (str): A count, a period or a ``pct`` that cannot be trusted.
        MESSAGE_TOO_LARGE (str): A mail message over the size cap, on disk or inside a mailbox.
        MESSAGE_TOO_COMPLEX (str): A mail message with too many lines, parts or levels of parts.
        NO_REPORT_ATTACHMENT (str): A mail file the user named that holds no report attachment.
        MALFORMED_MESSAGE (str): The mail parser failed on a message in a way no other reason names.
        XML_TOO_COMPLEX (str): The XML is nested too deep or holds too many elements.
    """

    UNSUPPORTED_EXTENSION = "unsupported_extension"
    UNREADABLE = "unreadable"
    FILE_TOO_LARGE = "file_too_large"
    DECOMPRESSED_TOO_LARGE = "decompressed_too_large"
    NOT_AN_ARCHIVE = "not_an_archive"
    NO_XML_MEMBER = "no_xml_member"
    MULTIPLE_XML_MEMBERS = "multiple_xml_members"
    FORBIDDEN_DECLARATION = "forbidden_declaration"
    MALFORMED_XML = "malformed_xml"
    NOT_A_REPORT = "not_a_report"
    UNSUPPORTED_VERSION = "unsupported_version"
    INVALID_FIELD = "invalid_field"
    MESSAGE_TOO_LARGE = "message_too_large"
    MESSAGE_TOO_COMPLEX = "message_too_complex"
    NO_REPORT_ATTACHMENT = "no_report_attachment"
    MALFORMED_MESSAGE = "malformed_message"
    XML_TOO_COMPLEX = "xml_too_complex"


class ReportRefused(Exception):
    """
    Raised when a file or a document is refused.

    ``ingest`` catches it per file; the lower functions let it propagate so each one can be tested
    for "this input is refused for this reason".

    Attributes:
        reason (Reason): The machine-readable cause.
        detail (str): A short English explanation. It never echoes report content, except the
            parser position of a malformed document.
    """

    def __init__(self, reason: Reason, detail: str = "") -> None:
        """
        Build a refusal.

        Args:
            reason (Reason): The machine-readable cause.
            detail (str, optional): A short English explanation. Default: empty.
        """
        super().__init__(reason, detail)
        self.reason = reason
        self.detail = detail

    def __str__(self) -> str:
        """
        Describe the refusal for a log line.

        Returns:
            str: The reason value, followed by the detail when there is one.
        """
        return f"{self.reason.value}: {self.detail}" if self.detail else self.reason.value
