"""
Tests of the vocabulary of ``fetch``: the reasons, the refusal, the outcome and the constants
(spec 009, stage 1: RF-08, ADR-1, ADR-7).

Isolation: nothing touches the disk, the network or an environment variable. The one child
interpreter checks what importing the two modules pulls in, because the offline commands must stay
free of ``imaplib`` (RF-09). Text in the refusals is invented.
"""

from __future__ import annotations

import dataclasses
import subprocess
import sys

import pytest

from mailvigil.fetch import model
from mailvigil.fetch.errors import FetchReason, FetchRefused
from mailvigil.fetch.model import FetchOutcome, SearchResult
from mailvigil.reports import mail

# ---------------------------------------------------------------------------
# Reasons
# ---------------------------------------------------------------------------

# The keys of the catalog: a rename breaks the sentences, so the strings are pinned here.
_REASONS = {
    "HOST_UNREACHABLE": "host_unreachable",
    "TIMEOUT": "timeout",
    "DEADLINE_EXCEEDED": "deadline_exceeded",
    "CERTIFICATE_INVALID": "certificate_invalid",
    "TLS_FAILED": "tls_failed",
    "LOGIN_FAILED": "login_failed",
    "PASSWORD_UNUSABLE": "password_unusable",
    "PASSWORD_FILE": "password_file",
    "FOLDER_NOT_FOUND": "folder_not_found",
    "PROTOCOL_ERROR": "protocol_error",
    "TOO_MANY_MATCHES": "too_many_matches",
    "WRITE_FAILED": "write_failed",
}


def test_the_twelve_reasons_have_the_exact_keys() -> None:
    assert {member.name: member.value for member in FetchReason} == _REASONS


# ---------------------------------------------------------------------------
# The refusal
# ---------------------------------------------------------------------------


def test_a_refusal_carries_the_reason_and_has_no_detail_or_outcome_by_default() -> None:
    error = FetchRefused(FetchReason.TIMEOUT)
    assert error.reason is FetchReason.TIMEOUT
    assert error.detail == ""
    assert error.outcome is None


def test_a_refusal_carries_a_partial_outcome() -> None:
    partial = FetchOutcome(matched=3, saved=1, already=0, too_large=0, skipped=0, left=2)
    error = FetchRefused(FetchReason.WRITE_FAILED, "disk full", partial)
    assert error.outcome is partial


def test_the_detail_is_cleaned_of_control_and_bidirectional_characters() -> None:
    hostile = "NO\r\n* BYE \x1b[31mfake\x1b[0m \u202eevil\u202c done"
    detail = FetchRefused(FetchReason.PROTOCOL_ERROR, hostile).detail
    assert "\r" not in detail
    assert "\n" not in detail
    assert "\x1b" not in detail
    assert "\u202e" not in detail
    assert "\u202c" not in detail
    assert "fake" in detail


def test_the_detail_is_cut_at_200_characters() -> None:
    assert len(FetchRefused(FetchReason.PROTOCOL_ERROR, "x" * 300).detail) == 200


def test_the_text_of_a_refusal_is_the_reason_then_the_detail() -> None:
    assert str(FetchRefused(FetchReason.TIMEOUT)) == "timeout"
    assert str(FetchRefused(FetchReason.TIMEOUT, "slow")) == "timeout: slow"


# ---------------------------------------------------------------------------
# The outcome
# ---------------------------------------------------------------------------


def _outcome() -> FetchOutcome:
    """Build an outcome with six different numbers, so a swapped field is seen."""
    return FetchOutcome(matched=21, saved=6, already=5, too_large=4, skipped=3, left=2)


def test_the_outcome_holds_its_six_numbers() -> None:
    outcome = _outcome()
    assert [field.name for field in dataclasses.fields(outcome)] == [
        "matched",
        "saved",
        "already",
        "too_large",
        "skipped",
        "left",
    ]
    assert (
        outcome.matched,
        outcome.saved,
        outcome.already,
        outcome.too_large,
        outcome.skipped,
        outcome.left,
    ) == (21, 6, 5, 4, 3, 2)


def test_the_outcome_is_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        _outcome().saved = 0  # type: ignore[misc]  # the point of the test


def test_the_outcome_is_slotted() -> None:
    assert not hasattr(_outcome(), "__dict__")


def test_the_search_result_is_frozen_and_holds_the_uids_and_the_dropped_tokens() -> None:
    result = SearchResult(uids=(9, 4), dropped=2)
    assert (result.uids, result.dropped) == ((9, 4), 2)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.dropped = 0  # type: ignore[misc]  # the point of the test


# ---------------------------------------------------------------------------
# The constants
# ---------------------------------------------------------------------------


def test_the_constants_have_the_values_of_the_design_table() -> None:
    assert model.SOCKET_TIMEOUT == 30
    assert model.DEADLINE_SECONDS == 1800
    assert model.DEFAULT_LIMIT == 500
    assert model.MAX_LIMIT == 10_000
    assert model.SIZE_BATCH == 100
    assert model.LINE_LIMIT == 1_000_000
    assert model.LITERAL_OTHER == 64 * 1024
    assert model.UID_MAX == 2**32 - 1


def test_the_default_limit_fits_in_the_maximum() -> None:
    assert 1 <= model.DEFAULT_LIMIT <= model.MAX_LIMIT


def test_the_message_cap_is_the_object_of_the_mail_reader() -> None:
    """A message that ``fetch`` saves is always one the ingestion would accept."""
    assert model.MAX_MESSAGE_BYTES is mail.MAX_MESSAGE_BYTES


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------


def test_importing_the_vocabulary_does_not_import_imaplib() -> None:
    """Importing the vocabulary loads no IMAP code, so the offline commands stay offline (RF-09)."""
    code = (
        "import sys, mailvigil.fetch.errors, mailvigil.fetch.model; "
        "bad = [m for m in ('imaplib', 'mailvigil.fetch.imap') if m in sys.modules]; "
        "sys.exit(len(bad))"
    )
    assert subprocess.run([sys.executable, "-I", "-c", code], check=False).returncode == 0
