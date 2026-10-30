"""
Tests of ``verdict --html --output FILE``: the page written by the tool itself, in ASCII bytes
whatever the shell (spec 008 amendment of 2026-10-30, RF-01, ADR-11).

Isolation: the command runs through ``main(argv)`` with ``capsys``. Reports are synthetic files in
``tmp_path`` built by the ``conftest.py`` factories from invented domains (``example.com``). Every
test runs from an empty folder, so a ``mailvigil.toml`` of the working directory can never leak in,
and the output files live in ``tmp_path`` too.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from tests.cli_helpers import LONG, RecordXml, ReportXml, write_config, write_window

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


def _argv(folder: Path, config: Path, *extra: str) -> list[str]:
    """
    Build the arguments of a ``verdict --html`` run.

    Args:
        folder (Path): The folder of reports.
        config (Path): The configuration file.
        *extra (str): More arguments, after the common ones.

    Returns:
        list[str]: The arguments, without the program name.
    """
    return ["verdict", str(folder), "--config", str(config), "--html", *extra]


# ---------------------------------------------------------------------------
# The file (RF-01)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("days", "failing", "code"),
    [(LONG, False, EXIT_OK), (3, False, EXIT_TOO_EARLY), (LONG, True, EXIT_NOT_READY)],
    ids=["ready", "too-early", "not-ready"],
)
def test_the_file_holds_the_page_and_the_exit_code_is_the_answers(
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
    target = tmp_path / "report.html"

    result = main(_argv(folder, config, "--output", str(target)))
    written = capsys.readouterr()
    main(_argv(folder, config))
    printed = capsys.readouterr().out

    assert result == code
    assert written.out == "" and written.err == ""
    assert target.read_bytes() == printed.encode("ascii")
    assert target.read_bytes().startswith(b"<!doctype html>")


def test_the_file_is_ascii_with_unix_line_ends_in_the_other_language_too(
    tmp_path: Path, make_report_xml: ReportXml, make_record_xml: RecordXml
) -> None:
    folder = write_window(tmp_path / "reports", make_report_xml, make_record_xml, days=LONG)
    config = write_config(tmp_path / "config.toml")
    target = tmp_path / "relatorio.html"

    main(_argv(folder, config, "--lang", "pt-BR", "--output", str(target)))

    data = target.read_bytes()
    assert data.isascii() and b"\r" not in data
    assert b'<html lang="pt-BR">' in data


def test_a_file_already_there_is_replaced_and_no_temporary_file_stays(
    tmp_path: Path, make_report_xml: ReportXml, make_record_xml: RecordXml
) -> None:
    folder = write_window(tmp_path / "reports", make_report_xml, make_record_xml, days=LONG)
    config = write_config(tmp_path / "config.toml")
    target = tmp_path / "out" / "report.html"
    target.parent.mkdir()
    target.write_text("old page", encoding="ascii")

    main(_argv(folder, config, "--output", str(target)))

    assert target.read_bytes().startswith(b"<!doctype html>")
    assert [entry.name for entry in target.parent.iterdir()] == ["report.html"]


def test_a_relative_name_is_written_in_the_working_folder(
    tmp_path: Path, make_report_xml: ReportXml, make_record_xml: RecordXml, empty_cwd: Path
) -> None:
    folder = write_window(tmp_path / "reports", make_report_xml, make_record_xml, days=LONG)
    config = write_config(tmp_path / "config.toml")

    main(_argv(folder, config, "--output", "report.html"))

    assert (empty_cwd / "report.html").read_bytes().startswith(b"<!doctype html>")


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no permission bits to read")
def test_a_new_file_is_readable_by_others_as_the_file_of_a_redirect_is(
    tmp_path: Path, make_report_xml: ReportXml, make_record_xml: RecordXml
) -> None:
    folder = write_window(tmp_path / "reports", make_report_xml, make_record_xml, days=LONG)
    config = write_config(tmp_path / "config.toml")
    target = tmp_path / "report.html"
    before = os.umask(0o022)
    try:
        main(_argv(folder, config, "--output", str(target)))
    finally:
        os.umask(before)

    assert target.stat().st_mode & 0o777 == 0o644


# ---------------------------------------------------------------------------
# Usage errors (RF-01)
# ---------------------------------------------------------------------------


def test_output_without_html_is_a_usage_error_before_any_work(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "report.html"

    with pytest.raises(SystemExit) as stop:
        main(["verdict", str(tmp_path), "--domain", "example.com", "--output", str(target)])

    captured = capsys.readouterr()
    assert stop.value.code == EXIT_USAGE
    assert captured.out == "" and not target.exists()
    assert "--output" in captured.err and "--html" in captured.err


def test_output_with_json_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "report.html"

    with pytest.raises(SystemExit) as stop:
        main(
            ["verdict", str(tmp_path), "--domain", "example.com", "--json", "--output", str(target)]
        )

    assert stop.value.code == EXIT_USAGE
    assert not target.exists()
    assert "--output" in capsys.readouterr().err


def test_summary_has_no_output_option(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stop:
        main(["summary", str(tmp_path), "--domain", "example.com", "--output", "x.html"])

    assert stop.value.code == EXIT_USAGE
    assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# Refusals (RF-01)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("lang", "phrase"),
    [("en", "could not write"), ("pt-BR", "nao foi possivel gravar")],
)
def test_a_missing_folder_is_refused_with_one_line_and_is_not_created(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
    lang: str,
    phrase: str,
) -> None:
    folder = write_window(tmp_path / "reports", make_report_xml, make_record_xml, days=LONG)
    config = write_config(tmp_path / "config.toml")
    target = tmp_path / "nowhere" / "report.html"

    result = main(_argv(folder, config, "--lang", lang, "--output", str(target)))

    captured = capsys.readouterr()
    assert result == EXIT_REFUSED
    assert captured.out == ""
    assert captured.err.startswith("mailvigil: ") and phrase in captured.err
    assert captured.err.count("\n") == 1
    assert not target.parent.exists()


def test_a_folder_as_the_file_is_refused_and_leaves_nothing_behind(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    folder = write_window(tmp_path / "reports", make_report_xml, make_record_xml, days=LONG)
    config = write_config(tmp_path / "config.toml")
    target = tmp_path / "taken"
    target.mkdir()

    result = main(_argv(folder, config, "--output", str(target)))

    assert result == EXIT_REFUSED
    assert capsys.readouterr().out == ""
    assert list(target.iterdir()) == []
    assert [entry.name for entry in tmp_path.iterdir() if entry.suffix == ".tmp"] == []


def test_a_refusal_before_an_answer_neither_creates_nor_touches_the_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    empty = tmp_path / "reports"
    empty.mkdir()
    created = tmp_path / "new.html"
    kept = tmp_path / "kept.html"
    kept.write_text("old page", encoding="ascii")

    first = main(
        ["verdict", str(empty), "--domain", "example.com", "--html", "--output", str(created)]
    )
    second = main(
        ["verdict", str(empty), "--domain", "example.com", "--html", "--output", str(kept)]
    )

    assert (first, second) == (EXIT_REFUSED, EXIT_REFUSED)
    assert capsys.readouterr().out == ""
    assert not created.exists()
    assert kept.read_text(encoding="ascii") == "old page"


def test_help_names_the_option(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["verdict", "--help"])

    help_text = " ".join(capsys.readouterr().out.split())
    assert "--output FILE" in help_text
    assert "requires --html" in help_text
