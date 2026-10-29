"""
Tests of the text of ``fetch``: the outcome of a run and the refusal line (spec 009, RF-08).

Isolation: nothing touches the disk, the network or an environment variable, and no command runs.
Outcomes and refusals are built in the test, with six different numbers so a swapped label is seen.
The output is read back by its lines and cells, never by its exact spacing, which the design does
not fix. The hostile directory names are the attack itself: a control character, a bidirectional
override and a very long name must come out inert and within the column.
"""

from __future__ import annotations

import re

import pytest

from mailvigil.fetch.errors import FetchReason, FetchRefused
from mailvigil.fetch.model import FetchOutcome
from mailvigil.messages import ENGLISH, PORTUGUESE, Messages
from mailvigil.render_fetch import refusal_line, render_fetch

# The two languages every text test runs over.
_BOTH = pytest.mark.parametrize("messages", [ENGLISH, PORTUGUESE], ids=["en", "pt-BR"])

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

# Six different numbers, so a swapped label is seen.
_OUTCOME = FetchOutcome(matched=21, saved=6, already=5, too_large=4, skipped=3, left=2)
# A plain folder name, for the tests that are not about the name.
_DIRECTORY = "reports/inbox"


def _value_of(text: str, label: str) -> str:
    """Read the value that follows a label on its line."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(label):
            return stripped[len(label) :].strip()
    raise AssertionError(f"no line starts with {label!r}:\n{text}")


# ---------------------------------------------------------------------------
# The outcome
# ---------------------------------------------------------------------------


@_BOTH
def test_each_number_follows_its_own_label(messages: Messages) -> None:
    text = render_fetch(_OUTCOME, _DIRECTORY, messages)
    words = messages.fetch
    assert _value_of(text, words.key_matched) == "21"
    assert _value_of(text, words.key_saved) == "6"
    assert _value_of(text, words.key_already) == "5"
    assert _value_of(text, words.key_too_large) == "4"
    assert _value_of(text, words.key_skipped) == "3"
    assert _value_of(text, words.key_left) == "2"


@_BOTH
def test_the_directory_is_named(messages: Messages) -> None:
    text = render_fetch(_OUTCOME, _DIRECTORY, messages)
    assert _value_of(text, messages.fetch.key_directory) == _DIRECTORY


@_BOTH
def test_the_first_line_is_the_title(messages: Messages) -> None:
    assert render_fetch(_OUTCOME, _DIRECTORY, messages).splitlines()[0] == messages.fetch.title


@_BOTH
def test_a_run_that_found_nothing_still_says_so(messages: Messages) -> None:
    empty = FetchOutcome(matched=0, saved=0, already=0, too_large=0, skipped=0, left=0)
    text = render_fetch(empty, _DIRECTORY, messages)
    assert _value_of(text, messages.fetch.key_matched) == "0"
    assert _value_of(text, messages.fetch.key_saved) == "0"


@_BOTH
def test_the_text_is_ascii_and_within_80_columns(messages: Messages) -> None:
    text = render_fetch(_OUTCOME, _DIRECTORY, messages)
    assert text.isascii()
    assert all(len(line) <= 80 for line in text.splitlines())


def test_the_text_is_english_by_default() -> None:
    assert render_fetch(_OUTCOME, _DIRECTORY) == render_fetch(_OUTCOME, _DIRECTORY, ENGLISH)


def test_the_two_languages_do_not_write_the_same_words() -> None:
    assert render_fetch(_OUTCOME, _DIRECTORY, ENGLISH) != render_fetch(
        _OUTCOME, _DIRECTORY, PORTUGUESE
    )


def test_the_text_has_no_trailing_newline() -> None:
    assert not render_fetch(_OUTCOME, _DIRECTORY).endswith("\n")


# ---------------------------------------------------------------------------
# A hostile directory name
# ---------------------------------------------------------------------------

# Names that would forge a line, hide text or overflow the column if echoed raw.
_HOSTILE = [
    pytest.param("out\x1b[31m\r\nfake line\x07", id="control-characters"),
    pytest.param("out\u202eevil\u202c\u2066dir", id="bidirectional-override"),
    pytest.param("a" * 300, id="long-name"),
    pytest.param("c:\\mail\\" + "d" * 200, id="long-windows-path"),
]


@_BOTH
@pytest.mark.parametrize("directory", _HOSTILE)
def test_a_hostile_directory_comes_out_inert_and_within_the_column(
    messages: Messages, directory: str
) -> None:
    text = render_fetch(_OUTCOME, directory, messages)
    assert not re.search(r"[\u202a-\u202e\u2066-\u2069]", text)
    assert not re.search(r"[\x00-\x09\x0b-\x1f\x7f]", text)
    assert all(len(line) <= 80 for line in text.splitlines())
    # The name added no line: the title, the six numbers and the folder, blank lines aside.
    assert len([line for line in text.splitlines() if line.strip()]) == 8


def test_a_long_directory_is_cut_with_dots() -> None:
    text = render_fetch(_OUTCOME, "a" * 300)
    assert _value_of(text, ENGLISH.fetch.key_directory).endswith("...")


# ---------------------------------------------------------------------------
# The refusal line
# ---------------------------------------------------------------------------


@_BOTH
@pytest.mark.parametrize("reason", list(FetchReason))
def test_a_refusal_is_the_prefix_and_the_phrase_of_its_reason(
    messages: Messages, reason: FetchReason
) -> None:
    line = refusal_line(FetchRefused(reason), messages)
    assert line == f"mailvigil: {messages.fetch.reasons[reason]}"


@_BOTH
def test_the_detail_follows_the_phrase(messages: Messages) -> None:
    error = FetchRefused(FetchReason.PROTOCOL_ERROR, "unexpected response")
    line = refusal_line(error, messages)
    assert line == f"mailvigil: {messages.fetch.reasons[FetchReason.PROTOCOL_ERROR]}: " + (
        "unexpected response"
    )


def test_a_refusal_is_english_by_default() -> None:
    error = FetchRefused(FetchReason.TIMEOUT)
    assert refusal_line(error) == refusal_line(error, ENGLISH)


@_BOTH
@pytest.mark.parametrize("reason", [FetchReason.LOGIN_FAILED, FetchReason.HOST_UNREACHABLE])
def test_the_refusals_that_look_like_a_provider_without_imap_say_what_to_do(
    messages: Messages, reason: FetchReason
) -> None:
    line = refusal_line(FetchRefused(reason), messages)
    assert "IMAP" in line
    assert "summary" in line


@_BOTH
def test_a_refusal_before_any_work_has_one_line(messages: Messages) -> None:
    assert "\n" not in refusal_line(FetchRefused(FetchReason.LOGIN_FAILED), messages)


@_BOTH
def test_a_refusal_after_some_work_says_how_many_files_are_valid(messages: Messages) -> None:
    partial = FetchOutcome(matched=9, saved=4, already=0, too_large=0, skipped=0, left=5)
    error = FetchRefused(FetchReason.WRITE_FAILED, outcome=partial)
    first, second = refusal_line(error, messages).split("\n")
    assert first == f"mailvigil: {messages.fetch.reasons[FetchReason.WRITE_FAILED]}"
    assert second == messages.fetch.saved_before_stop.of(4)


@_BOTH
def test_one_saved_file_uses_the_singular(messages: Messages) -> None:
    partial = FetchOutcome(matched=2, saved=1, already=0, too_large=0, skipped=0, left=1)
    error = FetchRefused(FetchReason.TIMEOUT, outcome=partial)
    assert refusal_line(error, messages).endswith(messages.fetch.saved_before_stop.one.format(n=1))


@_BOTH
def test_a_partial_outcome_with_nothing_saved_adds_no_line(messages: Messages) -> None:
    partial = FetchOutcome(matched=3, saved=0, already=3, too_large=0, skipped=0, left=0)
    error = FetchRefused(FetchReason.TIMEOUT, outcome=partial)
    assert "\n" not in refusal_line(error, messages)


@_BOTH
@pytest.mark.parametrize("reason", list(FetchReason))
def test_a_refusal_line_is_ascii_whatever_the_reason(
    messages: Messages, reason: FetchReason
) -> None:
    assert refusal_line(FetchRefused(reason), messages).isascii()


def test_a_hostile_detail_is_already_inert_in_the_line() -> None:
    error = FetchRefused(FetchReason.PROTOCOL_ERROR, "NO\r\n* BYE\x1b[0m \u202eevil")
    line = refusal_line(error)
    assert "\n" not in line
    assert "\x1b" not in line
    assert "\u202e" not in line
