"""
Tests of an internationalized domain on the command line (spec 010, RF-03).

Isolation: the report is synthetic and the domain is invented (``bücher.example``, whose ``xn--``
form is ``xn--bcher-kva.example``); every file lives in ``tmp_path`` and the working directory is an
empty folder so no ``mailvigil.toml`` is found by accident (RNF-06).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from mailvigil.cli import main

_UNICODE = "bücher.example"
_ASCII = "xn--bcher-kva.example"


# ---------------------------------------------------------------------------
# Fixtures
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
def reports(tmp_path: Path, make_report_xml: Callable[..., bytes]) -> Path:
    """
    Write one synthetic report of the ``xn--`` spelling of the domain into a folder.

    Args:
        tmp_path (Path): The test's own folder.
        make_report_xml (Callable[..., bytes]): The report factory of ``conftest.py``.

    Returns:
        Path: The folder holding the report.
    """
    folder = tmp_path / "reports"
    folder.mkdir()
    name = f"example.net!{_ASCII}!1790000000!1790086399.xml"
    (folder / name).write_bytes(make_report_xml(domain=_ASCII))
    return folder


# ---------------------------------------------------------------------------
# The name as written (RF-03)
# ---------------------------------------------------------------------------


def test_domain_written_as_read_finds_the_reports_of_its_xn_spelling(
    reports: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--domain bücher.example`` reads the reports whose domain is the ``xn--`` name (RF-03)."""
    code = main(["summary", str(reports), "--domain", _UNICODE])

    captured = capsys.readouterr()
    assert code == 0
    assert captured.err == ""
    assert _ASCII in captured.out
    assert _UNICODE not in captured.out


def test_domain_in_the_file_is_read_the_same_way(
    reports: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The ``domain`` key of a file takes the name as written and prints the ``xn--`` form."""
    config = tmp_path / "config.toml"
    config.write_text(f'domain = "{_UNICODE}"\n', encoding="utf-8")

    code = main(["summary", str(reports), "--config", str(config)])

    captured = capsys.readouterr()
    assert code == 0
    assert _ASCII in captured.out


def test_the_flag_and_the_file_may_spell_the_same_domain_differently(
    reports: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The written name and its ``xn--`` form are one domain, so they do not disagree."""
    config = tmp_path / "config.toml"
    config.write_text(f'domain = "{_ASCII}"\n', encoding="utf-8")

    code = main(["summary", str(reports), "--config", str(config), "--domain", _UNICODE])

    assert code == 0
    assert capsys.readouterr().err == ""


def test_the_json_domain_field_is_the_xn_form(
    reports: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The document is ASCII like everything else, so its ``domain`` is the ``xn--`` name."""
    code = main(["summary", str(reports), "--domain", _UNICODE, "--json"])

    captured = capsys.readouterr()
    assert code == 0
    assert json.loads(captured.out)["domain"] == _ASCII
    assert captured.out.isascii()


@pytest.mark.parametrize("lang", ["en", "pt-BR"])
def test_a_name_that_changes_is_refused_with_the_line_of_the_language(
    lang: str, reports: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A refused name prints one line that names ``--domain`` and advises the ``xn--`` form."""
    code = main(["summary", str(reports), "--domain", "faß.example", "--lang", lang])

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert len(captured.err.splitlines()) == 1
    assert "--domain" in captured.err
    assert "xn--" in captured.err
    assert captured.err.isascii()
