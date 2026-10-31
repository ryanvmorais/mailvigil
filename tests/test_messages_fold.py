"""
Tests of the accented Portuguese catalog, its ASCII twin and the rule that picks one (spec 006
ADR-9).

Isolation: nothing touches the disk or the network and no command runs. The streams are fakes with
an ``encoding`` and an ``isatty``, and the platform is a parameter of the test, so the result never
depends on the machine that runs it. The catalog is walked through its dataclass fields, as
``test_messages.py`` does, so a field added to the model is covered without a line here.
"""

from __future__ import annotations

import sys
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass

import pytest
from tests.test_messages import _walk

from mailvigil.messages import ENGLISH, PORTUGUESE, PORTUGUESE_ASCII, fold_ascii
from mailvigil.messages.fold import _on_windows, accents_allowed, catalog_for_streams, fold_text

# The letters Portuguese adds to ASCII, and nothing else (ADR-9): no typographic quote or dash.
_ALLOWED_LETTERS = frozenset("áàâãéêíóôõúüçÁÀÂÃÉÊÍÓÔÕÚÜÇ")

# ---------------------------------------------------------------------------
# The catalog
# ---------------------------------------------------------------------------


def test_the_portuguese_catalog_has_accents_in_nfc_and_no_other_symbol() -> None:
    for path, template, _is_plural in _walk(PORTUGUESE):
        assert unicodedata.is_normalized("NFC", template), path
        stray = {char for char in template if not char.isascii()} - _ALLOWED_LETTERS
        assert not stray, (path, stray)


def test_the_catalog_really_carries_accents() -> None:
    texts = " ".join(template for _path, template, _is_plural in _walk(PORTUGUESE))
    assert {"á", "à", "ã", "é", "ê", "í", "ó", "õ", "ú", "ç"} <= set(texts)


def test_the_folded_catalog_is_the_accented_one_without_accents() -> None:
    accented = [template for _path, template, _is_plural in _walk(PORTUGUESE)]
    folded = [template for _path, template, _is_plural in _walk(PORTUGUESE_ASCII)]
    assert [fold_text(template) for template in accented] == folded


def test_folding_changes_no_width_and_no_placeholder() -> None:
    """One character for one, so no table, column or line moves."""
    pairs = zip(_walk(PORTUGUESE), _walk(PORTUGUESE_ASCII), strict=True)
    for (path, accented, _plural), (_path, folded, _same) in pairs:
        assert len(accented) == len(folded), path
        assert accented.count("{") == folded.count("{"), path


def test_folding_keeps_the_mappings_and_the_sets_of_the_catalog() -> None:
    assert PORTUGUESE_ASCII.refusals.config_detail == PORTUGUESE.refusals.config_detail
    assert PORTUGUESE_ASCII.verdict.words.keys() == PORTUGUESE.verdict.words.keys()
    assert PORTUGUESE_ASCII.html.lang == "pt-BR"


def test_a_catalog_without_accents_folds_to_itself() -> None:
    assert fold_ascii(ENGLISH) == ENGLISH
    assert fold_ascii(PORTUGUESE_ASCII) == PORTUGUESE_ASCII


@pytest.mark.parametrize(
    ("text", "folded"),
    [("não é domínio", "nao e dominio"), ("ÇÃO Êxito", "CAO Exito"), ("plain", "plain")],
)
def test_fold_text_removes_the_accents_and_nothing_else(text: str, folded: str) -> None:
    assert fold_text(text) == folded


# ---------------------------------------------------------------------------
# The rule
# ---------------------------------------------------------------------------


# What the ``platform`` fixture hands a test: say ``True`` for Windows, ``False`` for the rest.
Platform = Callable[[bool], None]


@dataclass
class FakeStream:
    """
    A stream with the two properties the rule reads.

    Attributes:
        encoding (str | None): The encoding the stream reports.
        tty (bool): What ``isatty`` answers. Default: ``False``.
    """

    encoding: str | None
    tty: bool = False

    def isatty(self) -> bool:
        return self.tty


@pytest.fixture
def platform(monkeypatch: pytest.MonkeyPatch) -> Platform:
    """Say what the program runs on: ``platform(True)`` is Windows."""

    def say(windows: bool) -> None:
        monkeypatch.setattr("mailvigil.messages.fold._on_windows", lambda: windows)

    return say


@pytest.mark.parametrize("encoding", ["utf-8", "UTF-8", "utf8", "UTF8"])
def test_utf8_streams_get_the_accents_off_windows(platform: Platform, encoding: str) -> None:
    platform(False)
    assert accents_allowed([FakeStream(encoding), FakeStream(encoding)])


def test_on_windows_only_a_console_gets_the_accents(platform: Platform) -> None:
    platform(True)
    assert accents_allowed([FakeStream("utf-8", tty=True), FakeStream("utf-8", tty=True)])
    # Python 3.15 and PYTHONUTF8=1 make a pipe UTF-8; ``more`` and ``type`` still read the OEM page.
    assert not accents_allowed([FakeStream("utf-8"), FakeStream("utf-8")])
    assert not accents_allowed([FakeStream("utf-8", tty=True), FakeStream("utf-8")])


@pytest.mark.parametrize("encoding", ["cp1252", "cp437", "cp850", "ascii", "latin-1", "utf-16"])
def test_another_encoding_never_gets_the_accents(platform: Platform, encoding: str) -> None:
    for windows in (False, True):
        platform(windows)
        assert not accents_allowed([FakeStream(encoding, tty=True)])


@pytest.mark.parametrize("encoding", [None, "", "no-such-codec"])
def test_a_stream_with_no_known_encoding_gets_no_accents(
    platform: Platform, encoding: str | None
) -> None:
    platform(False)
    assert not accents_allowed([FakeStream(encoding)])


def test_one_stream_that_cannot_carry_them_decides_for_both(platform: Platform) -> None:
    """A refusal goes to standard error and the text to standard output, with one catalog."""
    platform(False)
    assert not accents_allowed([FakeStream("utf-8"), FakeStream("cp1252")])


def test_a_stream_that_cannot_say_if_it_is_a_console_is_not_one(platform: Platform) -> None:
    class Closed(FakeStream):
        def isatty(self) -> bool:
            raise ValueError("I/O operation on closed file")

    platform(True)
    assert not accents_allowed([Closed("utf-8")])


def test_the_catalog_follows_the_rule_and_english_is_never_touched(platform: Platform) -> None:
    platform(False)
    utf8, legacy = FakeStream("utf-8"), FakeStream("cp1252")
    assert catalog_for_streams(PORTUGUESE, [utf8, utf8]) is PORTUGUESE
    assert catalog_for_streams(PORTUGUESE, [utf8, legacy]) is PORTUGUESE_ASCII
    assert catalog_for_streams(ENGLISH, [legacy]) is ENGLISH


def test_the_real_platform_check_reads_the_interpreter() -> None:
    """Every other test replaces it; this one keeps the real body honest."""
    assert _on_windows() is (sys.platform == "win32")
