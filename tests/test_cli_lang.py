"""
Tests of ``--lang`` on the two commands: the Portuguese text, the English default, a usage error for
any other code, and the guarantee that neither the language nor ``--json`` changes an exit code
(spec 006, RF-04, RF-05, RF-06, ADR-5, ADR-6).

Isolation: the commands run through ``main(argv)`` with ``capsys``. Reports are synthetic files in
``tmp_path`` built by the ``conftest.py`` factories from invented domains (``example.com``,
``example.net``) and the documentation address ranges (RNF-06). Every test runs from an empty
folder, so a ``mailvigil.toml`` of the working directory can never leak in.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable
from pathlib import Path

import pytest
from tests.cli_helpers import LONG, RecordXml, ReportXml, write_config, write_window

from mailvigil.cli import _LANGUAGE_CODES, build_parser, main
from mailvigil.messages import LANGUAGES

_Run = Callable[[Path], list[str]]

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


def _window(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    days: int,
    failing: bool = False,
) -> list[str]:
    """
    Write a window of reports and a configuration, and return the arguments that read them.

    Args:
        tmp_path (Path): The test's own folder.
        make_report_xml (ReportXml): The report factory of ``conftest.py``.
        make_record_xml (RecordXml): The record factory of ``conftest.py``.
        days (int): How many days the window spans.
        failing (bool, optional): Whether every message fails DMARC. Default: ``False``.

    Returns:
        list[str]: The arguments after the command name.
    """
    folder = write_window(
        tmp_path / "reports", make_report_xml, make_record_xml, days=days, failing=failing
    )
    config = write_config(tmp_path / "config.toml")
    return [str(folder), "--config", str(config)]


def _config_file(tmp_path: Path, text: str) -> list[str]:
    """
    Write a configuration file with the given text and return the arguments that read it.

    Args:
        tmp_path (Path): The test's own folder.
        text (str): The content of the file.

    Returns:
        list[str]: The arguments after the command name.
    """
    config = tmp_path / "bad.toml"
    config.write_text(text, encoding="utf-8")
    return [str(tmp_path), "--config", str(config)]


# ---------------------------------------------------------------------------
# The text (RF-06)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("code", ["pt-BR", "pt-br", "PT-BR", "Pt-bR"])
def test_summary_in_portuguese_for_any_case_of_the_code(
    code: str,
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = _window(tmp_path, make_report_xml, make_record_xml, days=3)

    status = main(["summary", *args, "--lang", code])

    captured = capsys.readouterr()
    assert status == 0
    assert captured.err == ""
    assert captured.out.startswith("Resumo do MailVigil para example.com\n")
    assert "Fora destes numeros" in captured.out
    assert captured.out.isascii()


@pytest.mark.parametrize("code", ["pt-BR", "pt-br"])
def test_verdict_in_portuguese_for_any_case_of_the_code(
    code: str,
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = _window(tmp_path, make_report_xml, make_record_xml, days=LONG)

    status = main(["verdict", *args, "--lang", code])

    captured = capsys.readouterr()
    assert status == 0
    assert captured.err == ""
    first = captured.out.split("\n")[0]
    assert first == "Veredito do MailVigil para example.com: PRONTO para p=reject"
    assert captured.out.isascii()


@pytest.mark.parametrize("command", ["summary", "verdict"])
@pytest.mark.parametrize("code", ["en", "EN", "En"])
def test_lang_en_prints_what_no_lang_prints(
    command: str,
    code: str,
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = _window(tmp_path, make_report_xml, make_record_xml, days=3)

    main([command, *args])
    plain = capsys.readouterr()
    main([command, *args, "--lang", code])
    explicit = capsys.readouterr()

    assert plain.out == explicit.out
    assert plain.err == explicit.err == ""
    assert plain.out.startswith("MailVigil ")


@pytest.mark.parametrize("command", ["summary", "verdict"])
def test_the_language_is_not_taken_from_the_environment(
    command: str,
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same command prints the same text on every machine (open question 2)."""
    args = _window(tmp_path, make_report_xml, make_record_xml, days=3)
    for name in ("LANG", "LC_ALL", "LC_MESSAGES", "LANGUAGE"):
        monkeypatch.setenv(name, "pt_BR.UTF-8")

    main([command, *args])

    assert capsys.readouterr().out.startswith("MailVigil ")


def test_the_option_can_come_before_the_paths(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = _window(tmp_path, make_report_xml, make_record_xml, days=3)

    status = main(["summary", "--lang", "pt-BR", *args])

    assert status == 0
    assert capsys.readouterr().out.startswith("Resumo do MailVigil")


# ---------------------------------------------------------------------------
# Other codes are a usage error (RF-07)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("command", ["summary", "verdict"])
@pytest.mark.parametrize("code", ["fr", "pt", "pt_BR", "portuguese", "english", "en-US", ""])
def test_any_other_code_is_a_usage_error(
    command: str, code: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as raised:
        main([command, str(tmp_path), "--domain", "example.com", "--lang", code])

    captured = capsys.readouterr()
    assert raised.value.code == 2
    assert captured.out == ""
    assert "--lang" in captured.err
    assert "pt-BR" in captured.err


def test_the_codes_the_help_lists_are_the_ones_the_catalog_has() -> None:
    assert {code.lower() for code in _LANGUAGE_CODES} == set(LANGUAGES)


def test_help_stays_in_english_and_documents_the_option(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["summary", "--lang", "pt-BR", "--help"])

    out = capsys.readouterr().out
    assert raised.value.code == 0
    assert "--lang" in out
    assert "{en,pt-BR}" in out
    assert "Sum up DMARC aggregate reports" in out


def test_lang_is_not_accepted_without_a_command() -> None:
    with pytest.raises(SystemExit) as raised:
        main(["--lang", "pt-BR"])

    assert raised.value.code == 2


def test_the_default_language_is_english() -> None:
    args = build_parser().parse_args(["summary", "reports", "--domain", "example.com"])
    assert args.lang is LANGUAGES["en"]


# ---------------------------------------------------------------------------
# --lang with --json (ADR-6)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("command", ["summary", "verdict"])
def test_lang_with_json_prints_the_same_document(
    command: str,
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The data has no language: the document is byte-equal with and without ``--lang``."""
    args = _window(tmp_path, make_report_xml, make_record_xml, days=3)

    main([command, *args, "--json"])
    plain = capsys.readouterr().out
    main([command, *args, "--json", "--lang", "pt-BR"])
    portuguese = capsys.readouterr()

    assert portuguese.out == plain
    assert portuguese.err == ""


# ---------------------------------------------------------------------------
# One exit code, whatever the format and the language (RF-04)
# ---------------------------------------------------------------------------


def _ready(tmp_path: Path, xml: ReportXml, record: RecordXml) -> list[str]:
    return ["verdict", *_window(tmp_path, xml, record, days=LONG)]


def _too_early(tmp_path: Path, xml: ReportXml, record: RecordXml) -> list[str]:
    return ["verdict", *_window(tmp_path, xml, record, days=2)]


def _not_ready(tmp_path: Path, xml: ReportXml, record: RecordXml) -> list[str]:
    return ["verdict", *_window(tmp_path, xml, record, days=LONG, failing=True)]


def _summary(tmp_path: Path, xml: ReportXml, record: RecordXml) -> list[str]:
    return ["summary", *_window(tmp_path, xml, record, days=3)]


def _refused(tmp_path: Path, xml: ReportXml, record: RecordXml) -> list[str]:
    return ["verdict", *_config_file(tmp_path, "domain = [")]


@pytest.mark.parametrize(
    ("case", "expected"),
    [(_summary, 0), (_ready, 0), (_too_early, 3), (_not_ready, 4), (_refused, 1)],
)
def test_every_combination_of_format_and_language_returns_the_same_code(
    case: Callable[[Path, ReportXml, RecordXml], list[str]],
    expected: int,
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
) -> None:
    args = case(tmp_path, make_report_xml, make_record_xml)
    options = [["--json"], ["--lang", "en"], ["--lang", "pt-BR"]]
    codes = {
        main([*args, *itertools.chain.from_iterable(chosen)])
        for size in range(len(options) + 1)
        for chosen in itertools.combinations(options, size)
    }
    assert codes == {expected}


# ---------------------------------------------------------------------------
# A refusal in Portuguese (RF-05, ADR-5)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("command", ["summary", "verdict"])
def test_a_missing_domain_is_a_portuguese_line_on_standard_error(
    command: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    status = main([command, str(tmp_path), "--lang", "pt-BR"])

    captured = capsys.readouterr()
    assert status == 1
    assert captured.out == ""
    assert captured.err == (
        "mailvigil: informe --domain ou --config (ou coloque um mailvigil.toml nesta pasta)\n"
    )


def test_an_invalid_domain_is_the_phrase_and_the_option(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    status = main(["summary", str(tmp_path), "--domain", "not a domain", "--lang", "pt-BR"])

    captured = capsys.readouterr()
    assert status == 1
    assert captured.out == ""
    assert captured.err == "mailvigil: dominio invalido [--domain]\n"


def test_a_domain_that_does_not_match_the_file_names_both(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = write_config(tmp_path / "config.toml")

    status = main(
        [
            "summary",
            str(tmp_path),
            "--config",
            str(config),
            "--domain",
            "example.net",
            "--lang",
            "pt-BR",
        ]
    )

    captured = capsys.readouterr()
    assert status == 1
    assert captured.out == ""
    assert captured.err == (
        f"mailvigil: --domain example.net nao corresponde ao dominio example.com de {config}\n"
    )


@pytest.mark.parametrize(
    ("text", "tail"),
    [
        ('[senders]\ns1 = "X"\n', "falta o dominio [domain]"),
        ('domain = "example.com"\nsenders = 3\n', "tipo de valor errado [senders]"),
        (
            'domain = "example.com"\n[senders]\n"bad selector" = "X"\n',
            "seletor invalido [bad selector]",
        ),
        ('domain = "example.com"\n[senders]\ns1 = "X"\nS1 = "Y"\n', "seletor repetido [s1]"),
        ('domain = "example.com"\n[senders]\ns1 = ""\n', "nome de servico invalido [s1]"),
    ],
)
def test_a_refused_configuration_is_the_phrase_of_its_reason_and_no_english_detail(
    text: str, tail: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = _config_file(tmp_path, text)

    status = main(["summary", *args, "--lang", "pt-BR"])

    captured = capsys.readouterr()
    assert status == 1
    assert captured.out == ""
    line = captured.err.rstrip("\n")
    assert line.startswith(f"mailvigil: {args[2]}: ")
    assert line.endswith(tail)
    assert captured.err.isascii()


def test_a_malformed_file_keeps_the_parsers_detail_after_the_phrase(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = _config_file(tmp_path, "domain = [")

    main(["summary", *args, "--lang", "pt-BR"])

    line = capsys.readouterr().err
    assert f"mailvigil: {args[2]}: TOML mal formado" in line
    assert line.count("\n") == 1


def test_an_unknown_key_keeps_the_suggestion_after_the_phrase(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = _config_file(tmp_path, 'domain = "example.com"\nsender = 1\n')

    main(["summary", *args, "--lang", "pt-BR"])

    line = capsys.readouterr().err
    assert f"mailvigil: {args[2]}: chave desconhecida [sender]: " in line
    assert "senders" in line


@pytest.mark.parametrize("command", ["summary", "verdict"])
def test_no_report_kept_is_the_portuguese_explanation(
    command: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()

    status = main([command, str(empty), "--domain", "example.com", "--lang", "pt-BR"])

    captured = capsys.readouterr()
    assert status == 1
    assert captured.out == ""
    assert captured.err.startswith("Nenhum relatorio DMARC de example.com foi mantido.\n")
    assert "arquivos ignorados" in captured.err


@pytest.mark.parametrize("command", ["summary", "verdict"])
def test_a_refusal_under_json_and_pt_br_is_portuguese_with_nothing_on_standard_output(
    command: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--lang`` still picks the language of the line on standard error (ADR-6)."""
    status = main([command, str(tmp_path), "--json", "--lang", "pt-BR"])

    captured = capsys.readouterr()
    assert status == 1
    assert captured.out == ""
    assert captured.err.startswith("mailvigil: informe --domain")


def test_the_english_refusal_is_unchanged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["summary", str(tmp_path), "--lang", "en"])

    assert capsys.readouterr().err == (
        "mailvigil: pass --domain or --config (or put a mailvigil.toml in this folder)\n"
    )
