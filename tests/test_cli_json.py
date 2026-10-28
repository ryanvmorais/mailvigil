"""
Tests of ``--json`` on the two commands: one document on standard output, nothing on standard
error, and a refusal that stays exactly what it was (spec 006, RF-01 and RF-05).

Isolation: the commands run through ``main(argv)`` with ``capsys``. Reports are synthetic files in
``tmp_path`` built by the ``conftest.py`` factories from invented domains (``example.com``,
``example.net``) and the documentation address ranges (RNF-06). Every test runs from an empty
folder, so a ``mailvigil.toml`` of the working directory can never leak in.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.cli_helpers import LONG, RecordXml, ReportXml, write_config, write_window

from mailvigil.cli import main

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


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
# One document (RF-01)
# ---------------------------------------------------------------------------


def test_summary_json_prints_one_document_and_a_newline(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Standard output is the document and one newline; standard error is empty."""
    folder = write_window(tmp_path / "reports", make_report_xml, make_record_xml, days=3)
    config = write_config(tmp_path / "config.toml")

    code = main(["summary", str(folder), "--config", str(config), "--json"])

    captured = capsys.readouterr()
    assert code == 0
    assert captured.err == ""
    assert captured.out.endswith("}\n")
    assert not captured.out.endswith("\n\n")
    document = json.loads(captured.out)
    assert document["command"] == "summary"
    assert document["schema_version"] == 1
    assert document["domain"] == "example.com"
    assert document["config"]["source"] == str(config)
    assert document["reports"]["count"] == 3


def test_verdict_json_prints_one_document_and_a_newline(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A ready verdict is one document, code 0, and nothing on standard error."""
    folder = write_window(tmp_path / "reports", make_report_xml, make_record_xml, days=LONG)
    config = write_config(tmp_path / "config.toml")

    code = main(["verdict", str(folder), "--config", str(config), "--json"])

    captured = capsys.readouterr()
    assert code == 0
    assert captured.err == ""
    assert captured.out.endswith("}\n")
    document = json.loads(captured.out)
    assert document["command"] == "verdict"
    assert document["answer"] == "ready"
    assert document["deciding"] is None


def test_the_json_document_has_no_text_of_the_human_output(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No heading and no sentence precedes or follows the document."""
    folder = write_window(tmp_path / "reports", make_report_xml, make_record_xml, days=3)
    config = write_config(tmp_path / "config.toml")

    main(["summary", str(folder), "--config", str(config), "--json"])

    out = capsys.readouterr().out
    assert out.startswith("{")
    assert "MailVigil summary" not in out


def test_the_same_run_twice_prints_the_same_bytes(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Nothing about the run (clock, order) reaches the document (RF-01)."""
    folder = write_window(tmp_path / "reports", make_report_xml, make_record_xml, days=3)
    config = write_config(tmp_path / "config.toml")
    outputs = []
    for command in ("summary", "verdict", "summary", "verdict"):
        main([command, str(folder), "--config", str(config), "--json"])
        outputs.append(capsys.readouterr().out)

    assert outputs[0] == outputs[2]
    assert outputs[1] == outputs[3]


# ---------------------------------------------------------------------------
# A verdict that is not yes still prints in full (RF-05)
# ---------------------------------------------------------------------------


def test_a_too_early_verdict_prints_the_document_and_returns_three(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A non-zero code means "the answer is not yes", not "there is no output"."""
    folder = write_window(tmp_path / "reports", make_report_xml, make_record_xml, days=2)
    config = write_config(tmp_path / "config.toml")

    code = main(["verdict", str(folder), "--config", str(config), "--json"])

    captured = capsys.readouterr()
    assert code == 3
    assert captured.err == ""
    document = json.loads(captured.out)
    assert document["answer"] == "too_early"
    assert document["deciding"] == "period_covered"


def test_a_not_ready_verdict_prints_the_document_and_returns_four(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A recognized failure is named in the document, with its address and service."""
    folder = write_window(
        tmp_path / "reports", make_report_xml, make_record_xml, days=LONG, failing=True
    )
    config = write_config(tmp_path / "config.toml")

    code = main(["verdict", str(folder), "--config", str(config), "--json"])

    captured = capsys.readouterr()
    assert code == 4
    assert captured.err == ""
    document = json.loads(captured.out)
    assert document["answer"] == "not_ready"
    assert document["recognized_failing"][0]["service"] == "Example Mail"
    assert document["recognized_failing"][0]["source_ip"] == "192.0.2.10"


# ---------------------------------------------------------------------------
# A refusal stays a refusal (RF-05)
# ---------------------------------------------------------------------------


def _bad_config(tmp_path: Path) -> list[str]:
    """
    Arguments with a configuration file that is not valid TOML.

    Args:
        tmp_path (Path): The test's own folder.

    Returns:
        list[str]: The arguments after the command name.
    """
    config = tmp_path / "bad.toml"
    config.write_text("domain = [", encoding="utf-8")
    return [str(tmp_path), "--config", str(config)]


def _no_domain(tmp_path: Path) -> list[str]:
    """
    Arguments with neither ``--domain`` nor a configuration file.

    Args:
        tmp_path (Path): The test's own folder.

    Returns:
        list[str]: The arguments after the command name.
    """
    return [str(tmp_path)]


def _no_report(tmp_path: Path) -> list[str]:
    """
    Arguments naming a folder with no report in it.

    Args:
        tmp_path (Path): The test's own folder.

    Returns:
        list[str]: The arguments after the command name.
    """
    empty = tmp_path / "empty"
    empty.mkdir()
    return [str(empty), "--domain", "example.com"]


@pytest.mark.parametrize("command", ["summary", "verdict"])
@pytest.mark.parametrize("arguments", [_bad_config, _no_domain, _no_report])
def test_a_refusal_with_json_is_the_same_line_on_standard_error_and_nothing_on_standard_output(
    command: str,
    arguments: object,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`--json` never puts a half-valid document on standard output; the code stays 1."""
    assert callable(arguments)
    args = arguments(tmp_path)

    plain_code = main([command, *args])
    plain = capsys.readouterr()
    json_code = main([command, *args, "--json"])
    with_json = capsys.readouterr()

    assert plain_code == json_code == 1
    assert plain.out == with_json.out == ""
    assert with_json.err == plain.err
    assert with_json.err != ""


def test_json_is_not_accepted_without_a_command(capsys: pytest.CaptureFixture[str]) -> None:
    """`--version` and the bare command have no JSON form."""
    with pytest.raises(SystemExit) as raised:
        main(["--json"])

    assert raised.value.code == 2
    assert "--json" in capsys.readouterr().err
