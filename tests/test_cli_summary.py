"""
Tests of the ``summary`` command: usage, where the configuration and the domain come from, the exit
codes and the encoding of the output.

Isolation: the command runs through ``main(argv)`` with ``capsys``. Reports are synthetic files in
``tmp_path`` built by the ``conftest.py`` factories from invented domains (``example.com``,
``example.org``) and the documentation address ranges (RNF-07). Every test runs from an empty
folder, so a ``mailvigil.toml`` of the working directory can never leak in (RF-08), and nothing
outside ``tmp_path`` is read or written (RNF-02).
"""

from __future__ import annotations

import io
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TextIO, cast

import pytest

from mailvigil import __version__
from mailvigil.cli import _write, main

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

# The right-to-left override, built here so the character is not invisible in the source.
_RLO = chr(0x202E)

# The attachment name a folder listing accepts: ``provider!domain!begin!end.ext`` (002).
_ATTACHMENT = "example.net!example.com!1790000000!1790086399.xml"


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
def reports(tmp_path: Path, make_report_xml: Callable[..., bytes]) -> Path:
    """
    Write one synthetic report of ``example.com`` into a folder.

    Args:
        tmp_path (Path): The test's own folder.
        make_report_xml (Callable[..., bytes]): The report factory of ``conftest.py``.

    Returns:
        Path: The folder holding the report.
    """
    folder = tmp_path / "reports"
    folder.mkdir()
    (folder / _ATTACHMENT).write_bytes(make_report_xml())
    return folder


def write_config(path: Path, domain: str = "example.com", service: str = "Example Mail") -> Path:
    """
    Write a configuration file that names the selector of the synthetic report.

    Args:
        path (Path): Where to write the file.
        domain (str, optional): The ``domain`` key. Default: ``example.com``.
        service (str, optional): The name of the ``s1`` selector. Default: ``Example Mail``.

    Returns:
        Path: The file written.
    """
    path.write_text(f'domain = "{domain}"\n\n[senders]\ns1 = "{service}"\n', encoding="utf-8")
    return path


def snapshot(folder: Path) -> list[tuple[str, bytes]]:
    """
    Record every file under a folder with its bytes.

    Args:
        folder (Path): The folder to walk.

    Returns:
        list[tuple[str, bytes]]: Relative path and content, sorted, to compare before and after.
    """
    return sorted(
        (str(path.relative_to(folder)), path.read_bytes())
        for path in folder.rglob("*")
        if path.is_file()
    )


# ---------------------------------------------------------------------------
# Usage (RF-07)
# ---------------------------------------------------------------------------


def test_summary_prints_the_text_and_returns_zero(
    reports: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A run with ``--config`` prints the summary on stdout, returns 0 and keeps stderr empty."""
    config = write_config(tmp_path / "config.toml")

    code = main(["summary", str(reports), "--config", str(config)])

    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.startswith("MailVigil summary for example.com\n")
    assert "Example Mail" in captured.out
    assert captured.err == ""


def test_no_path_is_a_usage_error_before_any_file_is_read(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """``summary`` without a path exits with 2, and neither ``ingest`` nor the loader ran."""

    def forbidden(*args: object, **kwargs: object) -> None:
        """Fail the test if a file is read."""
        raise AssertionError("a file was read before the usage error")

    monkeypatch.setattr("mailvigil.cli.ingest", forbidden)
    monkeypatch.setattr("mailvigil.cli.load_config", forbidden)

    with pytest.raises(SystemExit) as exit_info:
        main(["summary", "--domain", "example.com"])

    captured = capsys.readouterr()
    assert exit_info.value.code == 2
    assert "usage:" in captured.err
    assert captured.out == ""


def test_version_still_prints_the_version(capsys: pytest.CaptureFixture[str]) -> None:
    """``--version`` is untouched by the new subcommand."""
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"mailvigil {__version__}"


def test_no_command_prints_the_help_to_stderr_and_returns_two(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Without a command the help goes to stderr, stdout stays empty and the code is 2."""
    code = main([])

    captured = capsys.readouterr()
    assert code == 2
    assert "usage: mailvigil" in captured.err
    assert "summary" in captured.err
    assert captured.out == ""


# ---------------------------------------------------------------------------
# The configuration and the domain (RF-08)
# ---------------------------------------------------------------------------


def test_config_flag_loads_the_file_and_names_it(
    reports: Path, empty_cwd: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--config`` loads that file; the header names it and counts its selectors."""
    write_config(empty_cwd / "mine.toml")

    # why: a relative path, so the header line is short and is not cut by the 80-column limit
    assert main(["summary", str(reports), "--config", "mine.toml"]) == 0

    out = capsys.readouterr().out
    assert "config    mine.toml (1 selector)" in out


def test_explicit_missing_config_is_refused_without_trying_the_default(
    reports: Path, tmp_path: Path, empty_cwd: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A missing ``--config`` stops the run even when ``mailvigil.toml`` exists in the folder."""
    write_config(empty_cwd / "mailvigil.toml")
    missing = tmp_path / "missing.toml"

    code = main(["summary", str(reports), "--config", str(missing)])

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert "unreadable" in captured.err
    assert "missing.toml" in captured.err


def test_default_file_in_the_current_folder_is_read_and_named(
    reports: Path, empty_cwd: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``mailvigil.toml`` in the working directory is read without being asked, and shown."""
    write_config(empty_cwd / "mailvigil.toml")

    assert main(["summary", str(reports)]) == 0

    out = capsys.readouterr().out
    assert "config    mailvigil.toml (1 selector)" in out
    assert "Example Mail" in out


def test_a_folder_named_like_the_default_file_is_refused(
    reports: Path, empty_cwd: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A folder called ``mailvigil.toml`` is refused as unreadable, not silently ignored."""
    (empty_cwd / "mailvigil.toml").mkdir()

    code = main(["summary", str(reports), "--domain", "example.com"])

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert "unreadable" in captured.err
    assert "mailvigil.toml" in captured.err


def test_no_file_gives_config_none_and_an_empty_map(
    reports: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """With ``--domain`` and no file the header says ``none`` and the sender is unrecognized."""
    assert main(["summary", str(reports), "--domain", "example.com"]) == 0

    out = capsys.readouterr().out
    assert "config    none\n" in out
    assert "no selectors are configured" in out
    assert "Example Mail" not in out


def test_domain_is_normalized(reports: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``--domain`` goes through the same normalization as the file's ``domain``."""
    assert main(["summary", str(reports), "--domain", " Example.COM. "]) == 0

    assert capsys.readouterr().out.startswith("MailVigil summary for example.com\n")


def test_the_same_domain_in_the_flag_and_the_file_passes(
    reports: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A ``--domain`` equal to the file's, after normalization, is accepted."""
    config = write_config(tmp_path / "config.toml")

    code = main(["summary", str(reports), "--config", str(config), "--domain", "EXAMPLE.com"])

    assert code == 0
    assert "Example Mail" in capsys.readouterr().out


def test_a_different_domain_in_the_flag_is_refused_naming_both(
    reports: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A ``--domain`` that disagrees with the file's refuses the run and names both values."""
    config = write_config(tmp_path / "config.toml")

    code = main(["summary", str(reports), "--config", str(config), "--domain", "example.org"])

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    # why: the whole line, not a substring test, so it names both domains and is exactly one line
    assert captured.err == (
        f"mailvigil: --domain example.org does not match the domain example.com of {config}\n"
    )


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ("https://example.com", "invalid_domain"),
        ("localhost", "invalid_domain"),
        ("", "invalid_domain"),
        ("exämple.com", "non_ascii_domain"),
    ],
)
def test_an_invalid_domain_is_refused_with_the_loaders_reason(
    value: str, reason: str, reports: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An invalid ``--domain`` is refused with the reason and the name ``--domain``."""
    code = main(["summary", str(reports), "--domain", value])

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert reason in captured.err
    assert "--domain" in captured.err


def test_neither_source_is_refused_with_the_hint(
    reports: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Without ``--domain``, ``--config`` or ``mailvigil.toml`` the line says what to pass."""
    code = main(["summary", str(reports)])

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert "--domain" in captured.err
    assert "--config" in captured.err


def test_a_refused_configuration_names_its_path_cleaned(
    reports: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The path of a refused file is shown, with a control or bidirectional character removed."""
    # why: the file does not exist (Windows cannot create a name with an escape character), so the
    # refusal is "unreadable"; what matters here is how the path is echoed
    bad = tmp_path / f"bad\x1b[31m{_RLO}.toml"

    code = main(["summary", str(reports), "--config", str(bad)])

    captured = capsys.readouterr()
    assert code == 1
    assert "unreadable" in captured.err
    assert "bad[31m.toml" in captured.err
    assert "\x1b" not in captured.err
    assert _RLO not in captured.err


# ---------------------------------------------------------------------------
# Exit codes (RF-10, RNF-02)
# ---------------------------------------------------------------------------


def test_failing_traffic_still_returns_zero(
    tmp_path: Path, make_report_xml: Callable[..., bytes], make_record_xml: Callable[..., str]
) -> None:
    """Zero means an answer was printed, not that the domain is healthy (Resolved decision 6)."""
    folder = tmp_path / "failing"
    folder.mkdir()
    record = make_record_xml(dkim_evaluated="fail", spf_evaluated="fail", dkim=(), spf=())
    (folder / _ATTACHMENT).write_bytes(make_report_xml(records=[record]))

    assert main(["summary", str(folder), "--domain", "example.com"]) == 0


def test_a_refusal_is_one_line_on_stderr_without_a_traceback(
    reports: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A refusal prints exactly one line to stderr, nothing to stdout, and never a traceback."""
    code = main(["summary", str(reports), "--domain", "not a domain"])

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert len(captured.err.strip().splitlines()) == 1
    assert "Traceback" not in captured.err


def test_a_folder_with_nothing_in_it_prints_what_was_read(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Nothing found: stdout is empty, stderr says so, and the code is 1."""
    empty = tmp_path / "empty"
    empty.mkdir()

    code = main(["summary", str(empty), "--domain", "example.com"])

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert "No DMARC report for example.com was kept." in captured.err
    assert "No report file was found." in captured.err


def test_every_file_refused_prints_the_skipped_counts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Every file refused: the counts per reason reach stderr, stdout stays empty."""
    folder = tmp_path / "junk"
    folder.mkdir()
    (folder / "example.net!example.com!1!2.xml").write_bytes(b"<not-a-report/>")
    (folder / "example.net!example.com!3!4.xml").write_bytes(b"<also-not/>")

    code = main(["summary", str(folder), "--domain", "example.com"])

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert "skipped files" in captured.err
    assert "2" in captured.err


def test_all_reports_of_another_domain_print_the_filtered_count(
    reports: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Reports of another domain are counted on stderr and the run returns 1."""
    code = main(["summary", str(reports), "--domain", "example.org"])

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert "other domains" in captured.err


def test_the_command_writes_nothing_besides_the_inputs(
    reports: Path, tmp_path: Path, empty_cwd: Path
) -> None:
    """Read-only and offline: the folder tree is byte-identical after a run (RNF-02)."""
    config = write_config(tmp_path / "config.toml")
    before = snapshot(tmp_path)

    assert main(["summary", str(reports), "--config", str(config)]) == 0

    assert snapshot(tmp_path) == before
    assert list(empty_cwd.iterdir()) == []


# ---------------------------------------------------------------------------
# Encoding (RNF-08, ADR-4)
# ---------------------------------------------------------------------------


def test_a_name_the_stream_cannot_encode_prints_a_question_mark(
    reports: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On an ASCII stream a service name with other characters prints ``?`` and does not raise."""
    config = write_config(tmp_path / "config.toml", service="Café ★")
    buffer = io.BytesIO()
    stream = io.TextIOWrapper(buffer, encoding="ascii", newline="\n")
    monkeypatch.setattr(sys, "stdout", stream)

    code = main(["summary", str(reports), "--config", str(config)])

    stream.flush()
    assert code == 0
    assert b"Caf? ?" in buffer.getvalue()


def test_a_stream_without_an_encoding_falls_back_to_utf8() -> None:
    """A stream with no ``encoding`` attribute gets the text as it is, newline added."""

    class Bare:
        """A stream that only knows how to ``write``."""

        def __init__(self) -> None:
            """Start with no chunks written."""
            self.chunks: list[str] = []

        def write(self, text: str) -> int:
            """Keep what was written."""
            self.chunks.append(text)
            return len(text)

    bare = Bare()

    _write(cast(TextIO, bare), "Café")

    assert "".join(bare.chunks) == "Café\n"


def test_a_stream_whose_encoding_is_none_falls_back_to_utf8() -> None:
    """An ``encoding`` of ``None`` (a ``StringIO``) is the same as none at all."""
    stream = io.StringIO()

    _write(stream, "Café")

    assert stream.getvalue() == "Café\n"
