"""
Tests of the ``verdict`` command: the three answers and their exit codes, the refusals it shares
with ``summary``, and the proof that ``summary`` did not change.

Isolation: the command runs through ``main(argv)`` with ``capsys``. Reports are synthetic files in
``tmp_path`` built by the ``conftest.py`` factories from invented domains (``example.com``,
``example.net``) and the documentation address ranges (RNF-06). Every test runs from an empty
folder, so a ``mailvigil.toml`` of the working directory can never leak in, and nothing outside
``tmp_path`` is read or written.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from mailvigil.cli import main
from mailvigil.verdict import MIN_DAYS_SPANNED, MIN_MESSAGES

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

# Seconds in a day; the synthetic reports are one per day.
_DAY = 86400

# The first second of the synthetic window.
_START = 1790000000

# The days a "long" window spans: exactly the minimum the first rule asks for.
_LONG = MIN_DAYS_SPANNED

# Messages per daily report that put the whole window over the volume rule with room to spare.
_PER_DAY = -(-MIN_MESSAGES // _LONG) + 10

_ReportXml = Callable[..., bytes]
_RecordXml = Callable[..., str]


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


def write_config(path: Path) -> Path:
    """
    Write a configuration file that names the selector of the synthetic reports.

    Args:
        path (Path): Where to write the file.

    Returns:
        Path: The file written.
    """
    path.write_text(
        'domain = "example.com"\n\n[senders]\ns1 = "Example Mail"\n',
        encoding="utf-8",
    )
    return path


def write_window(
    folder: Path,
    make_report_xml: _ReportXml,
    make_record_xml: _RecordXml,
    *,
    days: int,
    count: int = _PER_DAY,
    failing: bool = False,
) -> Path:
    """
    Write one daily report of ``example.com`` for each day of a window.

    Args:
        folder (Path): The folder to create and fill.
        make_report_xml (_ReportXml): The report factory of ``conftest.py``.
        make_record_xml (_RecordXml): The record factory of ``conftest.py``.
        days (int): How many consecutive days to cover, one report each.
        count (int, optional): The messages in each report. Default: enough for the volume rule.
        failing (bool, optional): ``True`` makes every message fail the DMARC evaluation while the
            ``s1`` signature itself passes, so the configuration of ``write_config`` recognizes the
            sender (a recognized selector counts only when its signature passes).

    Returns:
        Path: The folder.
    """
    folder.mkdir()
    result = "fail" if failing else "pass"
    record = make_record_xml(
        count=count,
        dkim_evaluated=result,
        spf_evaluated=result,
        dkim=(("example.com", "s1", "pass"),),
        spf=(("example.com", result),),
    )
    for day in range(days):
        begin = _START + day * _DAY
        end = begin + _DAY - 1
        name = f"example.net!example.com!{begin}!{end}.xml"
        report = make_report_xml(report_id=f"r{day}", begin=begin, end=end, records=[record])
        (folder / name).write_bytes(report)
    return folder


# ---------------------------------------------------------------------------
# The three answers and their codes (RF-06, ADR-6)
# ---------------------------------------------------------------------------


def test_a_long_clean_busy_set_is_ready_and_returns_zero(
    tmp_path: Path,
    make_report_xml: _ReportXml,
    make_record_xml: _RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A window of the minimum length, clean and busy, prints the verdict and returns 0."""
    folder = write_window(tmp_path / "reports", make_report_xml, make_record_xml, days=_LONG)
    config = write_config(tmp_path / "config.toml")

    code = main(["verdict", str(folder), "--config", str(config)])

    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.startswith("MailVigil verdict for example.com: READY")
    assert captured.err == ""


def test_a_clean_set_that_is_short_is_too_early_and_returns_three(
    tmp_path: Path,
    make_report_xml: _ReportXml,
    make_record_xml: _RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Two days of clean mail is not enough data: the answer is too early, code 3."""
    folder = write_window(tmp_path / "reports", make_report_xml, make_record_xml, days=2)
    config = write_config(tmp_path / "config.toml")

    code = main(["verdict", str(folder), "--config", str(config)])

    captured = capsys.readouterr()
    assert code == 3
    assert "TOO EARLY" in captured.out.upper()
    assert captured.err == ""


def test_a_recognized_failure_is_not_ready_returns_four_and_names_the_source(
    tmp_path: Path,
    make_report_xml: _ReportXml,
    make_record_xml: _RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A recognized service that fails decides the answer, even on a long window."""
    folder = write_window(
        tmp_path / "reports", make_report_xml, make_record_xml, days=_LONG, failing=True
    )
    config = write_config(tmp_path / "config.toml")

    code = main(["verdict", str(folder), "--config", str(config)])

    captured = capsys.readouterr()
    assert code == 4
    assert "NOT READY" in captured.out.upper()
    assert "Example Mail" in captured.out
    assert "192.0.2.10" in captured.out
    assert captured.err == ""


def test_not_ready_wins_over_too_early_in_the_exit_code(
    tmp_path: Path,
    make_report_xml: _ReportXml,
    make_record_xml: _RecordXml,
) -> None:
    """A recognized failure on a short window is still code 4 (ADR-2)."""
    folder = write_window(
        tmp_path / "reports", make_report_xml, make_record_xml, days=2, failing=True
    )
    config = write_config(tmp_path / "config.toml")

    assert main(["verdict", str(folder), "--config", str(config)]) == 4


def test_the_domain_flag_alone_runs_with_an_empty_selector_map(
    tmp_path: Path,
    make_report_xml: _ReportXml,
    make_record_xml: _RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Without a file the failing source is not recognized, so it is judged by rule 5."""
    folder = write_window(
        tmp_path / "reports", make_report_xml, make_record_xml, days=_LONG, failing=True
    )

    code = main(["verdict", str(folder), "--domain", "example.com"])

    captured = capsys.readouterr()
    assert code == 4
    assert captured.err == ""
    assert "192.0.2.10" in captured.out


# ---------------------------------------------------------------------------
# The refusals shared with ``summary`` (RF-06, 004 RF-10)
# ---------------------------------------------------------------------------


def _refusal_arguments(tmp_path: Path, case: str) -> list[str]:
    """
    Build the arguments of a run that ``summary`` and ``verdict`` must both refuse.

    Args:
        tmp_path (Path): The test's own folder.
        case (str): One of ``config``, ``conflict``, ``no-domain`` and ``no-report``.

    Returns:
        list[str]: The arguments after the command name.
    """
    empty = tmp_path / "empty"
    empty.mkdir(exist_ok=True)
    if case == "config":
        broken = tmp_path / "broken.toml"
        broken.write_text("domain = ", encoding="utf-8")
        return [str(empty), "--config", str(broken)]
    if case == "conflict":
        config = write_config(tmp_path / "config.toml")
        return [str(empty), "--config", str(config), "--domain", "example.org"]
    if case == "no-domain":
        return [str(empty)]
    return [str(empty), "--domain", "example.com"]


@pytest.mark.parametrize("case", ["config", "conflict", "no-domain", "no-report"])
def test_a_refusal_prints_the_line_of_summary_and_returns_one(
    case: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The same arguments give the same standard-error line, an empty stdout and code 1."""
    arguments = _refusal_arguments(tmp_path, case)

    summary_code = main(["summary", *arguments])
    summary_captured = capsys.readouterr()
    verdict_code = main(["verdict", *arguments])
    verdict_captured = capsys.readouterr()

    assert summary_code == verdict_code == 1
    assert verdict_captured.err == summary_captured.err
    assert verdict_captured.err.strip() != ""
    assert verdict_captured.out == ""


def test_no_path_is_a_usage_error_before_any_file_is_read(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """``verdict`` without a path exits with 2, and neither ``ingest`` nor the loader ran."""

    def forbidden(*args: object, **kwargs: object) -> None:
        """Fail the test if a file is read."""
        raise AssertionError("a file was read before the usage error")

    monkeypatch.setattr("mailvigil.cli.ingest", forbidden)
    monkeypatch.setattr("mailvigil.cli.load_config", forbidden)

    with pytest.raises(SystemExit) as exit_info:
        main(["verdict", "--domain", "example.com"])

    captured = capsys.readouterr()
    assert exit_info.value.code == 2
    assert "usage:" in captured.err
    assert captured.out == ""


# ---------------------------------------------------------------------------
# What did not change (RF-06)
# ---------------------------------------------------------------------------


def test_summary_still_returns_zero_for_a_failing_set(
    tmp_path: Path,
    make_report_xml: _ReportXml,
    make_record_xml: _RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The set that ``verdict`` calls not ready is still code 0 for ``summary``."""
    folder = write_window(
        tmp_path / "reports", make_report_xml, make_record_xml, days=_LONG, failing=True
    )
    config = write_config(tmp_path / "config.toml")

    code = main(["summary", str(folder), "--config", str(config)])

    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.startswith("MailVigil summary for example.com\n")


def test_the_help_lists_both_commands(capsys: pytest.CaptureFixture[str]) -> None:
    """``--help`` names ``summary`` and ``verdict``."""
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])

    out = capsys.readouterr().out
    assert exit_info.value.code == 0
    assert "summary" in out
    assert "verdict" in out


def test_the_verdict_help_shows_the_three_shared_arguments(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``verdict --help`` shows the paths, ``--config`` and ``--domain``."""
    with pytest.raises(SystemExit):
        main(["verdict", "--help"])

    out = capsys.readouterr().out
    assert "PATH" in out
    assert "--config" in out
    assert "--domain" in out
