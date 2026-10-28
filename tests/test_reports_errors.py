"""
Tests of the refusal vocabulary: ``Reason`` and ``ReportRefused``.

Pure value checks: no file, no parser, so no isolation is needed.
"""

from __future__ import annotations

from enum import StrEnum

from mailvigil.reports.errors import Reason, ReportRefused


def test_reason_is_a_string_enum_with_the_sixteen_members() -> None:
    """``Reason`` has exactly the sixteen refusals of the designs, each a string."""
    assert issubclass(Reason, StrEnum)
    assert len(Reason) == 16


def test_the_four_message_reasons_have_their_final_keys() -> None:
    """Spec 007 adds four keys; they are the contract of ``--json``, so they are pinned."""
    assert Reason.MESSAGE_TOO_LARGE == "message_too_large"
    assert Reason.MESSAGE_TOO_COMPLEX == "message_too_complex"
    assert Reason.NO_REPORT_ATTACHMENT == "no_report_attachment"
    assert Reason.MALFORMED_MESSAGE == "malformed_message"


def test_reason_values_are_unique_lower_snake_strings() -> None:
    """Values are the stable keys later specs translate, so they must never collide."""
    values = [member.value for member in Reason]

    assert len(set(values)) == len(values)
    assert all(value == value.lower() and " " not in value for value in values)
    assert Reason.FORBIDDEN_DECLARATION == "forbidden_declaration"


def test_report_refused_keeps_reason_and_detail() -> None:
    """The exception exposes the machine-readable reason and the English detail."""
    error = ReportRefused(Reason.MALFORMED_XML, "line 3, column 7")

    assert error.reason is Reason.MALFORMED_XML
    assert error.detail == "line 3, column 7"


def test_report_refused_message_mentions_reason_and_detail() -> None:
    """``str(error)`` carries both, so an unhandled refusal is still readable in a log."""
    message = str(ReportRefused(Reason.INVALID_FIELD, "count"))

    assert "invalid_field" in message
    assert "count" in message


def test_report_refused_is_an_exception() -> None:
    """It can be raised and caught as an ordinary ``Exception``."""
    assert issubclass(ReportRefused, Exception)
