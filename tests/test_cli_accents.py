"""
Tests of which Portuguese text a run prints: with accents on a stream that carries them, folded to
ASCII on a pipe on Windows or on a legacy encoding, and always with accents in the page (spec 006,
ADR-9).

Isolation: the commands run through ``main(argv)`` with ``capsys`` (UTF-8, not a terminal). The
platform and the console check are patched, so the result never depends on the machine;
``conftest.py`` pins Windows with a pipe by default and each test says what it needs instead.
Reports are synthetic files in ``tmp_path`` (RNF-06).
"""

from __future__ import annotations

import html
import io
import sys
from pathlib import Path

import pytest
from tests.cli_helpers import RecordXml, ReportXml, write_config
from tests.test_cli_lang import _window

from mailvigil.cli import main

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

# The same word of the header of ``summary``, as a pipe on Windows prints it and as a console does.
_FOLDED = "periodo"
_ACCENTED = "período"


@pytest.fixture(autouse=True)
def empty_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run from an empty folder, away from any ``mailvigil.toml``."""
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)


@pytest.fixture
def linux(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run as on Linux or macOS: a UTF-8 stream is enough."""
    monkeypatch.setattr("mailvigil.messages.fold._on_windows", lambda: False)


@pytest.fixture
def windows_console(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run as in a Windows terminal: Windows, and both streams are consoles."""
    monkeypatch.setattr("mailvigil.messages.fold._is_console", lambda stream: True)


@pytest.fixture
def reports(tmp_path: Path, make_report_xml: ReportXml, make_record_xml: RecordXml) -> list[str]:
    """The arguments that read a four-week window of synthetic reports."""
    return _window(tmp_path, make_report_xml, make_record_xml, days=28)


# ---------------------------------------------------------------------------
# The text
# ---------------------------------------------------------------------------


def test_summary_has_accents_off_windows(
    linux: None, reports: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["summary", *reports, "--lang", "pt-BR"]) == 0
    out = capsys.readouterr().out
    assert _ACCENTED in out
    assert "Situações" in out


def test_verdict_has_accents_off_windows(
    linux: None, reports: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    main(["verdict", *reports, "--lang", "pt-BR"])
    out = capsys.readouterr().out
    assert "Veredito do MailVigil" in out
    assert "período coberto" in out


def test_a_pipe_on_windows_gets_the_folded_text(
    reports: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    """The conftest default: Windows, and ``capsys`` is a pipe."""
    main(["summary", *reports, "--lang", "pt-BR"])
    out = capsys.readouterr().out
    assert _FOLDED in out
    assert out.isascii()


def test_a_console_on_windows_gets_the_accents(
    windows_console: None, reports: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    main(["summary", *reports, "--lang", "pt-BR"])
    assert _ACCENTED in capsys.readouterr().out


def test_a_legacy_standard_error_folds_the_text_of_standard_output_too(
    linux: None,
    reports: list[str],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One catalog serves the run, so the stream that cannot carry accents decides."""
    legacy = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    monkeypatch.setattr(sys, "stderr", legacy)
    main(["summary", *reports, "--lang", "pt-BR"])
    out = capsys.readouterr().out
    assert _FOLDED in out
    assert out.isascii()


def test_a_refusal_line_follows_the_same_rule(
    linux: None,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    config = write_config(tmp_path / "config.toml")
    args = ["summary", str(empty), "--config", str(config), "--lang", "pt-BR"]
    assert main(args) == 1
    assert "relatório" in capsys.readouterr().err

    monkeypatch.setattr("mailvigil.messages.fold._on_windows", lambda: True)
    assert main(args) == 1
    err = capsys.readouterr().err
    assert "relatorio" in err
    assert err.isascii()


def test_english_and_json_do_not_change(
    linux: None, reports: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    main(["summary", *reports])
    english = capsys.readouterr().out
    main(["summary", *reports, "--lang", "pt-BR", "--json"])
    json_pt = capsys.readouterr().out
    main(["summary", *reports, "--json"])
    json_en = capsys.readouterr().out
    assert english.isascii()
    assert json_pt == json_en


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------


def test_the_page_has_the_accents_even_on_a_pipe_on_windows(
    reports: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    main(["verdict", *reports, "--html", "--lang", "pt-BR"])
    page = capsys.readouterr().out
    assert page.isascii()
    assert "Há evidência suficiente?" in html.unescape(page)


def test_the_page_written_to_a_file_has_the_accents(reports: list[str], tmp_path: Path) -> None:
    target = tmp_path / "page.html"
    main(["verdict", *reports, "--html", "--output", str(target), "--lang", "pt-BR"])
    page = target.read_bytes().decode("ascii")
    assert "Há evidência suficiente?" in html.unescape(page)
