"""
Tests of the immutable report model.

The model is plain data, so the tests build instances by hand; no parser and no file are involved.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mailvigil.reports.errors import Reason
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

_MOMENT = datetime(2026, 10, 1, tzinfo=UTC)


def _report() -> Report:
    """
    Build the smallest valid report.

    Returns:
        Report: A report with no records and a policy that only names its domain.
    """
    return Report(
        reporter="Example Mail",
        report_id="r1",
        begin=_MOMENT,
        end=_MOMENT,
        policy=PolicyPublished(domain="example.com"),
        records=(),
        source_file="r1.xml",
    )


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


def test_every_model_type_is_frozen() -> None:
    """Assigning to a field of any model type raises ``FrozenInstanceError``."""
    instances = [
        DkimResult(),
        SpfResult(),
        OverrideReason(),
        Record(),
        PolicyPublished(domain="example.com"),
        _report(),
        SkippedFile(Path("a.zip"), Reason.UNREADABLE, ""),
        IngestionResult(),
    ]

    for instance in instances:
        field = dataclasses.fields(instance)[0].name
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(instance, field, "changed")


def test_every_model_type_uses_slots() -> None:
    """Slots keep a typo in a field name from silently creating an attribute."""
    record = Record()

    with pytest.raises((AttributeError, TypeError)):
        record.colour = "red"  # type: ignore[attr-defined]  # why: proving slots reject it


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


def test_record_defaults_are_empty_and_collections_are_tuples() -> None:
    """A bare ``Record`` has empty strings, ``disposition`` ``none`` and tuple collections."""
    record = Record()

    assert record.source_ip == ""
    assert record.count == 0
    assert record.disposition == "none"
    assert record.dkim_evaluated == ""
    assert record.spf_evaluated == ""
    assert record.header_from == ""
    assert record.override_reasons == ()
    assert record.dkim == ()
    assert record.spf == ()


def test_policy_defaults() -> None:
    """``p`` is ``?`` when absent, ``pct`` is 100 and the other tags are empty strings."""
    policy = PolicyPublished(domain="example.com")

    assert policy.p == "?"
    assert policy.pct == 100
    for name in ("sp", "np", "adkim", "aspf", "testing", "discovery_method"):
        assert getattr(policy, name) == ""


def test_ingestion_result_defaults_are_empty() -> None:
    """An empty result has no reports, no skipped files and zero counts."""
    result = IngestionResult()

    assert result.reports == ()
    assert result.skipped == ()
    assert result.duplicates == 0
    assert result.other_domain == 0


# ---------------------------------------------------------------------------
# Equality
# ---------------------------------------------------------------------------


def test_equal_values_compare_equal() -> None:
    """Frozen dataclasses compare by value, which the RFC 7489 / RFC 9990 test relies on."""
    assert _report() == _report()
    assert DkimResult("example.com", "s1", "pass") == DkimResult("example.com", "s1", "pass")
