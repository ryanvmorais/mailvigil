"""
Tests of the exit-code contract: one test per row of the table, with and without ``--json``, and
the proof that the table in the README is the one in the code (spec 006, RF-04).

Isolation: the commands run through ``main(argv)``. Reports are synthetic files in ``tmp_path``
built by the ``conftest.py`` factories from invented domains (``example.com``, ``example.net``) and
the documentation address ranges (RNF-06). Every test runs from an empty folder. The README is the
only file read from the repository.
"""

from __future__ import annotations

import io
import re
from collections.abc import Callable
from pathlib import Path

import pytest
from tests.cli_helpers import LONG, RecordXml, ReportXml, write_config, write_window

from mailvigil import cli
from mailvigil.cli import main

_README = Path(__file__).resolve().parent.parent / "README.md"


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
# One case per row of the table
# ---------------------------------------------------------------------------

#: Builds the arguments (after ``--json`` is left out) that make a case, from the test folder and
#: the report factories.
_Case = Callable[[Path, ReportXml, RecordXml], list[str]]


def _summary_printed(tmp_path: Path, report: ReportXml, record: RecordXml) -> list[str]:
    """
    Arguments of a ``summary`` that prints.

    Args:
        tmp_path (Path): The test's own folder.
        report (ReportXml): The report factory.
        record (RecordXml): The record factory.

    Returns:
        list[str]: The arguments, command included.
    """
    folder = write_window(tmp_path / "reports", report, record, days=3)
    return ["summary", str(folder), "--config", str(write_config(tmp_path / "c.toml"))]


def _verdict(days: int, *, failing: bool = False, policy: str = "none") -> _Case:
    """
    Make the case of a ``verdict`` over a synthetic window.

    Args:
        days (int): The days the window spans.
        failing (bool, optional): Whether every message fails. Default: ``False``.
        policy (str, optional): The published ``p``. Default: ``none``.

    Returns:
        _Case: The function that builds the arguments.
    """

    def build(tmp_path: Path, report: ReportXml, record: RecordXml) -> list[str]:
        """Write the window and name the command, the folder and the configuration."""
        folder = write_window(
            tmp_path / "reports", report, record, days=days, failing=failing, policy=policy
        )
        return ["verdict", str(folder), "--config", str(write_config(tmp_path / "c.toml"))]

    return build


def _refused_config(tmp_path: Path, report: ReportXml, record: RecordXml) -> list[str]:
    """
    Arguments with a configuration file that is not valid TOML.

    Args:
        tmp_path (Path): The test's own folder.
        report (ReportXml): Unused.
        record (RecordXml): Unused.

    Returns:
        list[str]: The arguments, command included.
    """
    config = tmp_path / "bad.toml"
    config.write_text("domain = [", encoding="utf-8")
    return ["summary", str(tmp_path), "--config", str(config)]


def _no_report_kept(tmp_path: Path, report: ReportXml, record: RecordXml) -> list[str]:
    """
    Arguments naming a folder with no report in it.

    Args:
        tmp_path (Path): The test's own folder.
        report (ReportXml): Unused.
        record (RecordXml): Unused.

    Returns:
        list[str]: The arguments, command included.
    """
    empty = tmp_path / "empty"
    empty.mkdir()
    return ["verdict", str(empty), "--domain", "example.com"]


_CASES: list[tuple[str, int, _Case]] = [
    ("summary printed", 0, _summary_printed),
    ("verdict ready", 0, _verdict(LONG)),
    ("configuration refused", 1, _refused_config),
    ("no report kept", 1, _no_report_kept),
    ("verdict too early", 3, _verdict(2)),
    ("verdict not ready", 4, _verdict(LONG, failing=True)),
    ("too early and failing is not ready", 4, _verdict(2, failing=True)),
    ("enforcing, failing: blocking real mail", 4, _verdict(LONG, failing=True, policy="reject")),
    ("enforcing, clean: no problem seen", 0, _verdict(LONG, policy="reject")),
]


@pytest.mark.parametrize(("name", "code", "case"), _CASES, ids=[c[0] for c in _CASES])
@pytest.mark.parametrize("json_flag", [[], ["--json"]], ids=["text", "json"])
def test_each_row_of_the_table_returns_its_code_with_and_without_json(
    name: str,
    code: int,
    case: _Case,
    json_flag: list[str],
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
) -> None:
    """The input that makes the case gives the code, and `--json` cannot change it."""
    arguments = case(tmp_path, make_report_xml, make_record_xml)

    assert main([*arguments, *json_flag]) == code, name


@pytest.mark.parametrize(
    "output",
    [["summary"], ["summary", "--json"], ["verdict"], ["verdict", "--json"], ["verdict", "--html"]],
    ids=" ".join,
)
def test_an_enormous_count_is_a_refused_report_not_a_traceback(
    output: list[str],
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
) -> None:
    """
    A count of thousands of digits is refused at the parser, so no output ever sums it.

    The only report kept would be the one with the enormous count, so the run ends as "no report
    kept" (1), the code of a refusal, and not as an uncaught ``ValueError``.
    """
    reports = tmp_path / "reports"
    reports.mkdir()
    record = make_record_xml(count="9" * 4000)
    (reports / "example.net!example.com!1790000000!1790086399.xml").write_bytes(
        make_report_xml(records=[record])
    )
    config = write_config(tmp_path / "mailvigil.toml")

    code = main([*output, str(reports), "--config", str(config)])

    assert code == 1


def test_an_unknown_option_is_a_usage_error_with_code_two(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Argparse ends the process with 2 and prints on standard error only."""
    with pytest.raises(SystemExit) as raised:
        main(["verdict", "--no-such-option"])

    assert raised.value.code == 2
    assert capsys.readouterr().out == ""


def test_the_bare_command_is_a_usage_error_with_code_two() -> None:
    """Without a command the help goes to standard error and the code is 2."""
    assert main([]) == 2


# ---------------------------------------------------------------------------
# A bug, Ctrl+C and a closed pipe never escape as a traceback (RF-04, amendment of 2026-10-29)
# ---------------------------------------------------------------------------

# Stands for report text in an exception message: it must never reach standard error.
_SECRET = "text from a report"


def _raise(error: BaseException) -> Callable[..., object]:
    """
    Make a stand-in for a command that raises.

    Args:
        error (BaseException): What the command raises.

    Returns:
        Callable[..., object]: A function that accepts any arguments and raises ``error``.
    """

    def run(*_args: object, **_kwargs: object) -> object:
        """Raise the error."""
        raise error

    return run


def test_a_bug_ends_with_code_seventy_and_one_line_without_the_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An unexpected exception is not a refusal: the code is 70 and no traceback is printed."""
    monkeypatch.setattr(cli, "_run_summary", _raise(ValueError(_SECRET)))

    code = main(["summary", ".", "--domain", "example.com"])

    captured = capsys.readouterr()
    assert code == 70
    assert captured.out == ""
    assert captured.err.startswith(
        "mailvigil: internal error (ValueError at test_cli_exit_codes.py:"
    )
    assert "report it at https://github.com/ryanvmorais/mailvigil/issues" in captured.err
    assert "Traceback" not in captured.err
    assert _SECRET not in captured.err


def test_a_bug_without_a_traceback_still_gets_its_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An exception that was never raised has no frames, and the line leaves out the place."""
    assert cli._internal_error_line(RuntimeError("x")).startswith(
        "mailvigil: internal error (RuntimeError). "
    )
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("command", ["summary", "verdict"])
def test_ctrl_c_ends_with_one_hundred_thirty_and_no_output(
    command: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The usual code of an interrupt, without a traceback or a word."""
    monkeypatch.setattr(cli, f"_run_{command}", _raise(KeyboardInterrupt()))

    code = main([command, ".", "--domain", "example.com"])

    captured = capsys.readouterr()
    assert code == 130
    assert (captured.out, captured.err) == ("", "")


def test_a_closed_pipe_ends_quietly_with_one_hundred_forty_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``mailvigil verdict | head`` cuts the output: no error line, and the code says so."""
    monkeypatch.setattr(cli, "_run_verdict", _raise(BrokenPipeError()))

    code = main(["verdict", ".", "--domain", "example.com"])

    captured = capsys.readouterr()
    assert code == 141
    assert (captured.out, captured.err) == ("", "")


def test_the_closed_pipe_points_standard_output_at_the_null_device(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The stream is replaced, so the flush at exit cannot print a second error."""
    target = (tmp_path / "stdout.txt").open("w", encoding="utf-8")
    monkeypatch.setattr(cli.sys, "stdout", target)
    with target:
        cli._silence_stdout()
        target.write("lost")
        target.flush()

    assert (tmp_path / "stdout.txt").read_text(encoding="utf-8") == ""


def test_a_stream_without_a_file_descriptor_is_left_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``io.StringIO`` has no ``fileno``: silencing it must not raise."""
    monkeypatch.setattr(cli.sys, "stdout", io.StringIO())

    cli._silence_stdout()


def test_a_usage_error_is_still_a_system_exit_with_code_two() -> None:
    """The handler is around the command, not around argparse."""
    with pytest.raises(SystemExit) as raised:
        main(["verdict", ".", "--json", "--html", "--domain", "example.com"])

    assert raised.value.code == 2


# ---------------------------------------------------------------------------
# The table is in one place, and the README says the same (RF-04)
# ---------------------------------------------------------------------------


def test_the_constants_in_the_code_are_the_table() -> None:
    """The eight codes are the ones of the contract; changing one is a breaking change."""
    assert (cli.EXIT_OK, cli.EXIT_REFUSED, cli.EXIT_USAGE) == (0, 1, 2)
    assert (cli.EXIT_TOO_EARLY, cli.EXIT_NOT_READY) == (3, 4)
    assert (cli.EXIT_INTERNAL, cli.EXIT_INTERRUPTED, cli.EXIT_PIPE_CLOSED) == (70, 130, 141)


def test_the_readme_table_lists_exactly_the_codes_of_the_constants() -> None:
    """The README's exit-code table is read and compared with ``cli.py``."""
    text = _README.read_text(encoding="utf-8")
    section = re.search(r"^### Exit codes\n(.*?)(?=^#{1,3} |\Z)", text, re.DOTALL | re.MULTILINE)
    assert section is not None, "README.md needs a '### Exit codes' section"
    rows = re.findall(r"^\| `(\d+)` \|", section.group(1), re.MULTILINE)

    assert [int(row) for row in rows] == [
        cli.EXIT_OK,
        cli.EXIT_REFUSED,
        cli.EXIT_USAGE,
        cli.EXIT_TOO_EARLY,
        cli.EXIT_NOT_READY,
        cli.EXIT_INTERNAL,
        cli.EXIT_INTERRUPTED,
        cli.EXIT_PIPE_CLOSED,
    ]


def test_no_provisional_codes_are_left_in_the_help_or_the_readme(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The codes are a contract now, so nothing calls them provisional."""
    with pytest.raises(SystemExit):
        main(["verdict", "--help"])

    assert "provisional" not in capsys.readouterr().out.lower()
    assert "provisional" not in _README.read_text(encoding="utf-8").lower()
