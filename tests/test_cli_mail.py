"""
Tests of mail files on the two commands: an ``.eml`` and an ``.mbox`` give the same answer as the
same reports as loose files, and the new refusals reach the text, the JSON and the Portuguese
(spec 007, RF-08).

Isolation: the commands run through ``main(argv)`` with ``capsys``. Reports are synthetic files in
``tmp_path`` built by the ``conftest.py`` factories from invented domains (``example.com``,
``example.net``) and the documentation address ranges (RNF-06); the messages that carry them are
built by ``mail_helpers.py``. Every test runs from an empty folder, so a ``mailvigil.toml`` of the
working directory can never leak in.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.cli_helpers import LONG, RecordXml, ReportXml, write_config, write_window
from tests.mail_helpers import build_eml, build_mbox

from mailvigil.cli import build_parser, main

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


def _as_mail(window: Path, target: Path) -> tuple[Path, Path]:
    """
    Write the reports of a window again as a folder of ``.eml`` and as one ``.mbox``.

    Args:
        window (Path): A folder of loose reports, as ``write_window`` leaves it.
        target (Path): A folder to create for the mail files.

    Returns:
        tuple[Path, Path]: The folder of messages, one per report, and the mailbox with all of them.
    """
    target.mkdir()
    messages = {
        report.name: build_eml((report.name, "xml", report.read_bytes()))
        for report in sorted(window.iterdir())
    }
    folder = target / "messages"
    folder.mkdir()
    for name, message in messages.items():
        (folder / f"{name}.eml").write_bytes(message)
    mailbox = target / "inbox.mbox"
    mailbox.write_bytes(build_mbox(*messages.values()))
    return folder, mailbox


# ---------------------------------------------------------------------------
# The same answer as loose files (RF-08)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("command", ["summary", "verdict"])
@pytest.mark.parametrize("extra", [[], ["--json"], ["--lang", "pt-BR"]])
def test_mail_files_give_the_same_text_and_exit_code_as_loose_files(
    command: str,
    extra: list[str],
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    window = write_window(tmp_path / "reports", make_report_xml, make_record_xml, days=LONG)
    folder, mailbox = _as_mail(window, tmp_path / "mail")
    config = str(write_config(tmp_path / "config.toml"))

    outcomes = []
    for path in (window, folder, mailbox):
        code = main([command, str(path), "--config", config, *extra])
        outcomes.append((code, capsys.readouterr()))

    loose, eml, mbox = outcomes
    assert loose[1].out != ""
    assert eml == loose
    assert mbox == loose


# ---------------------------------------------------------------------------
# What is left out is told (RF-08)
# ---------------------------------------------------------------------------


def _bad_attachment_mailbox(tmp_path: Path, make_report_xml: ReportXml) -> Path:
    """
    Write a mailbox whose second message carries an attachment that is not a report.

    Args:
        tmp_path (Path): The test's own folder.
        make_report_xml (ReportXml): The report factory of ``conftest.py``.

    Returns:
        Path: The mailbox.
    """
    path = tmp_path / "inbox.mbox"
    path.write_bytes(
        build_mbox(
            build_eml(("a.xml", "xml", make_report_xml(report_id="a"))),
            build_eml(("broken.xml", "xml", b"<feedback><a></feedback>")),
        )
    )
    return path


def test_json_skipped_entries_have_the_part_and_null_for_a_loose_file(
    tmp_path: Path,
    make_report_xml: ReportXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mailbox = _bad_attachment_mailbox(tmp_path, make_report_xml)
    loose = tmp_path / "notes.txt"
    loose.write_text("not a report")
    config = write_config(tmp_path / "config.toml")

    main(["summary", str(mailbox), str(loose), "--config", str(config), "--json"])

    skipped = json.loads(capsys.readouterr().out)["skipped"]
    entries = {entry["name"]: entry for entry in skipped}
    assert entries["inbox.mbox"]["part"] == "#2 broken.xml"
    assert entries["inbox.mbox"]["reason"] == "malformed_xml"
    assert entries["notes.txt"]["part"] is None


def test_the_text_shows_the_part_of_a_refused_attachment(
    tmp_path: Path,
    make_report_xml: ReportXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mailbox = _bad_attachment_mailbox(tmp_path, make_report_xml)
    config = write_config(tmp_path / "config.toml")

    main(["summary", str(mailbox), "--config", str(config)])

    assert "inbox.mbox #2 broken.xml:" in capsys.readouterr().out


def test_an_eml_with_no_report_is_told_in_english_and_in_portuguese(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plain = tmp_path / "plain.eml"
    plain.write_bytes(build_eml())
    config = str(write_config(tmp_path / "config.toml"))

    main(["summary", str(plain), "--config", config])
    captured = capsys.readouterr()
    english = captured.out + captured.err
    main(["summary", str(plain), "--config", config, "--lang", "pt-BR"])
    captured = capsys.readouterr()
    portuguese = captured.out + captured.err

    assert "plain.eml: no report attached" in english
    assert "plain.eml: nenhum relatorio anexado" in portuguese
    assert portuguese != english
    assert portuguese.isascii()


# ---------------------------------------------------------------------------
# The help (RF-08)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("command", ["summary", "verdict"])
def test_the_help_of_the_path_mentions_mail_files(command: str) -> None:
    subparsers = next(
        action.choices
        for action in build_parser()._actions
        if getattr(action, "choices", None) and command in action.choices
    )
    text = " ".join(subparsers[command].format_help().split())

    assert ".eml" in text
    assert ".mbox" in text
