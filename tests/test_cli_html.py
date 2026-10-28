"""
Tests of ``verdict --html``: one page on standard output, the exit code of the answer, and the
refusals that stay what they were (spec 008, RF-01, RF-08, ADR-6).

Isolation: the command runs through ``main(argv)`` with ``capsys``. Reports are synthetic files in
``tmp_path`` built by the ``conftest.py`` factories from invented domains (``example.com``,
``example.net``) and the documentation address ranges (RNF-06). Every test runs from an empty
folder, so a ``mailvigil.toml`` of the working directory can never leak in.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.cli_helpers import LONG, RecordXml, ReportXml, write_config, write_window
from tests.html_helpers import Page

from mailvigil.cli import EXIT_NOT_READY, EXIT_OK, EXIT_REFUSED, EXIT_TOO_EARLY, EXIT_USAGE, main


@pytest.fixture(autouse=True)
def empty_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """
    Run every test from an empty folder, away from any ``mailvigil.toml``.

    Args:
        tmp_path (Path): The test's own folder.
        monkeypatch (pytest.MonkeyPatch): Used to change the working directory.

    Returns:
        Path: The empty working directory.
    """
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    return cwd


# ---------------------------------------------------------------------------
# One page, the exit code of the answer (RF-01)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("days", "failing", "code"),
    [(LONG, False, EXIT_OK), (3, False, EXIT_TOO_EARLY), (LONG, True, EXIT_NOT_READY)],
    ids=["ready", "too-early", "not-ready"],
)
def test_the_page_is_printed_and_the_exit_code_is_the_answers(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
    days: int,
    failing: bool,
    code: int,
) -> None:
    folder = write_window(
        tmp_path / "reports", make_report_xml, make_record_xml, days=days, failing=failing
    )
    config = write_config(tmp_path / "config.toml")

    result = main(["verdict", str(folder), "--config", str(config), "--html"])

    captured = capsys.readouterr()
    assert result == code
    assert captured.err == ""
    assert captured.out.startswith("<!doctype html>")
    assert captured.out.endswith("</html>\n") and not captured.out.endswith("\n\n")
    assert Page(captured.out).count("h1") == 1


def test_the_page_is_in_the_language_asked_for(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    folder = write_window(tmp_path / "reports", make_report_xml, make_record_xml, days=3)
    config = write_config(tmp_path / "config.toml")

    main(["verdict", str(folder), "--config", str(config), "--html", "--lang", "pt-BR"])

    out = capsys.readouterr().out
    assert '<html lang="pt-BR">' in out
    assert out.isascii()


def test_the_same_run_twice_prints_the_same_bytes(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    folder = write_window(tmp_path / "reports", make_report_xml, make_record_xml, days=LONG)
    config = write_config(tmp_path / "config.toml")
    argv = ["verdict", str(folder), "--config", str(config), "--html"]

    main(argv)
    first = capsys.readouterr().out
    main(argv)

    assert capsys.readouterr().out == first


def test_the_page_names_neither_the_folder_nor_the_configuration(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    folder = write_window(tmp_path / "reports", make_report_xml, make_record_xml, days=LONG)
    config = write_config(tmp_path / "config.toml")

    main(["verdict", str(folder), "--config", str(config), "--html"])

    out = capsys.readouterr().out
    assert str(tmp_path) not in out and "config.toml" not in out and ".xml" not in out


# ---------------------------------------------------------------------------
# Usage errors and refusals (RF-01, ADR-6)
# ---------------------------------------------------------------------------


def test_html_with_json_is_a_usage_error_before_any_work(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as stop:
        main(["verdict", str(tmp_path / "missing"), "--domain", "example.com", "--html", "--json"])

    captured = capsys.readouterr()
    assert stop.value.code == EXIT_USAGE
    assert captured.out == ""
    assert "--html" in captured.err and "--json" in captured.err


def test_summary_has_no_html_option(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stop:
        main(["summary", str(tmp_path), "--domain", "example.com", "--html"])

    assert stop.value.code == EXIT_USAGE
    assert capsys.readouterr().out == ""


def test_a_refusal_writes_nothing_to_standard_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    empty = tmp_path / "reports"
    empty.mkdir()

    result = main(["verdict", str(empty), "--domain", "example.com", "--html"])

    captured = capsys.readouterr()
    assert result == EXIT_REFUSED
    assert captured.out == ""
    assert captured.err


def test_a_bad_domain_writes_nothing_to_standard_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = main(["verdict", str(tmp_path), "--domain", "not a domain", "--html"])

    captured = capsys.readouterr()
    assert result == EXIT_REFUSED
    assert captured.out == ""


def test_help_names_the_page_and_says_to_redirect_it(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["verdict", "--help"])

    help_text = " ".join(capsys.readouterr().out.split())
    assert "--html" in help_text
    assert "HTML" in help_text
    assert "redirect" in help_text
    # argparse may wrap the line at the hyphen of ``Out-File``, so the check skips that word.
    assert "PowerShell 5.1" in help_text and "Encoding ascii" in help_text
