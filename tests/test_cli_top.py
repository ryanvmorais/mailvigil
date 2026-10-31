"""
Tests of ``--top N`` on the two commands: where it is accepted, what it trims, and that the answer
and the exit code do not depend on it (spec 006 ADR-8, spec 008 ADR-12, issue #71).

Isolation: the commands run through ``main(argv)`` with ``capsys``. The reports are synthetic files
in ``tmp_path`` built by the ``conftest.py`` factories, one report with many failing sources from
the documentation range ``198.51.100.0/24`` (RNF-06). Every test runs from an empty folder, so a
``mailvigil.toml`` of the working directory can never leak in.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.cli_helpers import RecordXml, ReportXml, write_config

from mailvigil.cli import EXIT_USAGE, main

# The window of the report written below: a day of the synthetic calendar.
_BEGIN = 1790000000
_END = 1790086399

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


@pytest.fixture
def reports(tmp_path: Path, make_report_xml: ReportXml, make_record_xml: RecordXml) -> Path:
    """
    Write one report of six failing sources, each from its own address.

    Args:
        tmp_path (Path): The test's own folder.
        make_report_xml (ReportXml): The report factory of ``conftest.py``.
        make_record_xml (RecordXml): The record factory of ``conftest.py``.

    Returns:
        Path: The folder that holds the report.
    """
    folder = tmp_path / "reports"
    folder.mkdir()
    records = [
        make_record_xml(
            ip=f"198.51.100.{number}",
            count=number,
            dkim_evaluated="fail",
            spf_evaluated="fail",
            dkim=(("example.net", "x", "fail"),),
            spf=(("example.net", "fail"),),
        )
        for number in range(1, 7)
    ]
    report = make_report_xml(report_id="r1", begin=_BEGIN, end=_END, records=records)
    (folder / f"example.net!example.com!{_BEGIN}!{_END}.xml").write_bytes(report)
    return folder


@pytest.fixture
def config(tmp_path: Path) -> Path:
    """
    Write the configuration of the synthetic reports.

    Args:
        tmp_path (Path): The test's own folder.

    Returns:
        Path: The file.
    """
    return write_config(tmp_path / "config.toml")


# ---------------------------------------------------------------------------
# Where --top is accepted
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["summary"], "argument --top: requires --json"),
        (["verdict"], "argument --top: requires --json or --html"),
    ],
)
def test_top_needs_a_format_that_has_a_list_to_trim(
    argv: list[str],
    message: str,
    reports: Path,
    config: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as stop:
        main([*argv, str(reports), "--config", str(config), "--top", "3"])

    assert stop.value.code == EXIT_USAGE
    captured = capsys.readouterr()
    assert message in captured.err
    assert captured.out == ""


def test_top_is_not_an_option_of_the_html_page_of_summary(
    reports: Path, config: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``summary`` has no ``--html``, so argparse refuses the pair before any work."""
    with pytest.raises(SystemExit) as stop:
        main(["summary", str(reports), "--config", str(config), "--html", "--top", "3"])

    assert stop.value.code == EXIT_USAGE
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("value", ["0", "-2", "many", "1.5", ""])
def test_top_takes_a_whole_number_of_one_or_more(
    value: str, reports: Path, config: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as stop:
        main(["summary", str(reports), "--config", str(config), "--json", "--top", value])

    assert stop.value.code == EXIT_USAGE
    captured = capsys.readouterr()
    assert "--top" in captured.err
    assert captured.out == ""


# ---------------------------------------------------------------------------
# What it trims
# ---------------------------------------------------------------------------


def test_summary_json_with_top_keeps_the_first_n_and_says_what_it_left_out(
    reports: Path, config: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["summary", str(reports), "--config", str(config), "--json", "--top", "2"])

    document = json.loads(capsys.readouterr().out)
    assert code == 0
    assert len(document["senders"]) == 2
    assert len(document["failing"]) == 2
    assert document["top"] == {"limit": 2, "left_out": {"senders": 4, "failing": 4}}
    assert document["totals"]["failing"] == 21


def test_summary_json_without_top_has_every_entry_and_no_top_key(
    reports: Path, config: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["summary", str(reports), "--config", str(config), "--json"])

    document = json.loads(capsys.readouterr().out)
    assert len(document["failing"]) == 6
    assert "top" not in document


def test_verdict_json_with_top_trims_the_two_failing_lists(
    reports: Path, config: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["verdict", str(reports), "--config", str(config), "--json", "--top", "1"])

    document = json.loads(capsys.readouterr().out)
    kept = len(document["recognized_failing"]) + len(document["unrecognized_failing"])
    assert kept == 1
    assert document["top"]["limit"] == 1
    assert sum(document["top"]["left_out"].values()) == 5


def test_verdict_html_with_top_cuts_the_senders_table_and_says_so(
    reports: Path, config: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["verdict", str(reports), "--config", str(config), "--html", "--top", "2"])

    page = capsys.readouterr().out
    assert "Not listed here: 4 other senders" in page


def test_verdict_html_without_top_lists_a_short_table_whole(
    reports: Path, config: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["verdict", str(reports), "--config", str(config), "--html"])

    assert "Not listed here" not in capsys.readouterr().out


def test_the_page_speaks_the_language_of_lang_when_it_cuts(
    reports: Path, config: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(
        [
            "verdict",
            str(reports),
            "--config",
            str(config),
            "--html",
            "--top",
            "2",
            "--lang",
            "pt-BR",
        ]
    )

    assert "Fora desta lista: 4 outros remetentes" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# The answer does not depend on the cut
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("flag", ["--json", "--html"])
def test_the_exit_code_is_the_same_with_and_without_top(
    flag: str, reports: Path, config: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    whole = main(["verdict", str(reports), "--config", str(config), flag])
    capsys.readouterr()
    cut = main(["verdict", str(reports), "--config", str(config), flag, "--top", "1"])

    assert cut == whole
