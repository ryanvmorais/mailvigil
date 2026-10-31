"""
Tests of a run over several domains on the command line, in text (spec 010, RF-02, RF-04 to RF-06).

Isolation: the commands run through ``main(argv)`` with ``capsys``. Every report is synthetic, built
by the ``conftest.py`` factories and the helpers of ``cli_helpers.py`` from invented domains
(``example.com``, ``example.net``, ``example.org``) and the documentation address ranges (RNF-06).
Every test runs from an empty folder, so no ``mailvigil.toml`` is found by accident, and the clock
is the one ``conftest.py`` pins. The text of a block is compared with the text of the run of that
one domain over the same reports, which is the promise of ADR-4 and of RNF-01.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from tests.cli_helpers import LONG, RecordXml, ReportXml, write_domains_config, write_window

from mailvigil.cli import main
from mailvigil.config import MAX_DOMAINS
from mailvigil.render import RULE

_COM = "example.com"
_NET = "example.net"
_ORG = "example.org"


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


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    """
    Run the command and read what it printed.

    Args:
        capsys (pytest.CaptureFixture[str]): The capture of the test.
        *argv (str): The arguments, command included.

    Returns:
        tuple[int, str, str]: The exit code, standard output and standard error.
    """
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def windows(
    folder: Path,
    report: ReportXml,
    record: RecordXml,
    days_by_domain: dict[str, int],
    **options: bool,
) -> Path:
    """
    Write one window of daily reports for each domain into the same folder.

    Args:
        folder (Path): The folder to fill.
        report (ReportXml): The report factory.
        record (RecordXml): The record factory.
        days_by_domain (dict[str, int]): The days each domain's window spans.
        **options (bool): ``failing``, passed to every window.

    Returns:
        Path: The folder.
    """
    for domain, days in days_by_domain.items():
        write_window(folder, report, record, days=days, domain=domain, **options)
    return folder


def blocks_of(out: str) -> list[str]:
    """
    Split the text of a run into the text of its domains.

    Args:
        out (str): Standard output of a run.

    Returns:
        list[str]: The blocks, each as a run of that domain alone would print it (with the newline).
    """
    return [block.strip("\n") + "\n" for block in out.split(f"\n\n{RULE}\n\n")]


# ---------------------------------------------------------------------------
# summary: one block per domain (RF-05, ADR-4, ADR-5)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("lang", [[], ["--lang", "pt-BR"]], ids=["english", "portuguese"])
def test_summary_of_three_domains_is_the_text_of_each_set_apart_by_a_rule(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
    lang: list[str],
) -> None:
    """Each block is what a run of that one domain prints, and the exit code is 0 (RF-05)."""
    folder = windows(
        tmp_path / "reports",
        make_report_xml,
        make_record_xml,
        {_COM: LONG, _NET: LONG, _ORG: 2},
    )
    config = str(write_domains_config(tmp_path / "c.toml", [_COM, _NET, _ORG]))

    code, out, err = run(capsys, "summary", str(folder), "--config", config, *lang)

    assert (code, err) == (0, "")
    blocks = blocks_of(out)
    assert len(blocks) == 3
    for block, domain in zip(blocks, [_COM, _NET, _ORG], strict=True):
        alone = run(capsys, "summary", str(folder), "--config", config, "--domain", domain, *lang)
        # The folder holds the other two domains, which the single run drops: the block of the
        # several does not claim to have dropped what another block kept (ADR-4).
        assert block.splitlines()[0] == alone[1].splitlines()[0]
        assert domain in block
    assert out.count(RULE) == 2
    assert all(len(line) <= 80 and line.isascii() for line in out.splitlines())


def test_each_block_equals_the_run_of_its_domain_when_the_folder_holds_no_other(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Over separate folders the block and the single run are the same text (RNF-01)."""
    first = windows(tmp_path / "a", make_report_xml, make_record_xml, {_COM: LONG})
    second = windows(tmp_path / "b", make_report_xml, make_record_xml, {_NET: LONG})
    config = str(write_domains_config(tmp_path / "c.toml", [_COM, _NET]))

    _code, out, _err = run(capsys, "summary", str(first), str(second), "--config", config)

    alone = [
        run(capsys, "summary", str(folder), "--config", config, "--domain", domain)[1]
        for folder, domain in ((first, _COM), (second, _NET))
    ]
    assert blocks_of(out) == alone


def test_a_report_of_a_listed_domain_is_not_other_domain_in_the_block_of_another(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Only a report that belongs to no domain of the run counts as another domain (RF-04)."""
    folder = windows(tmp_path / "reports", make_report_xml, make_record_xml, {_COM: 3, _NET: 3})

    _code, together, _err = run(capsys, "summary", str(folder), "--domain", _COM, "--domain", _NET)
    _code, alone, _err = run(capsys, "summary", str(folder), "--domain", _COM)

    assert re.search(r"other domains +0", together)
    assert re.search(r"other domains +3", alone)


def test_a_refused_file_is_listed_in_every_block(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A file that cannot be read cannot be assigned to a domain, so each block says so (ADR-4)."""
    folder = windows(tmp_path / "reports", make_report_xml, make_record_xml, {_COM: 3, _NET: 3})
    (folder / "example.net!example.com!1!2.xml").write_bytes(b"<feedback>")

    _code, out, _err = run(capsys, "summary", str(folder), "--domain", _COM, "--domain", _NET)

    assert all(re.search(r"skipped files +1", block) for block in blocks_of(out))


# ---------------------------------------------------------------------------
# verdict: the tally and the worst answer (RF-05, RF-06, ADR-6)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("days", "failing", "code", "tally"),
    [
        ({_COM: LONG, _NET: LONG, _ORG: LONG}, [], 0, "3 domains: 3 ready"),
        ({_COM: LONG, _NET: 2, _ORG: LONG}, [], 3, "3 domains: 2 ready, 1 too early"),
        ({_COM: LONG, _NET: LONG, _ORG: LONG}, [_NET], 4, "3 domains: 2 ready, 1 not ready"),
        (
            {_COM: LONG, _NET: 2, _ORG: LONG},
            [_ORG],
            4,
            "3 domains: 1 ready, 1 too early, 1 not ready",
        ),
    ],
    ids=["all ready", "one too early", "one not ready", "not ready beats too early"],
)
def test_verdict_of_three_domains_exits_with_the_worst_answer_and_counts_them(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
    days: dict[str, int],
    failing: list[str],
    code: int,
    tally: str,
) -> None:
    """The code is 4, else 3, else 0, and the last line says why in words (RF-05, RF-06)."""
    folder = tmp_path / "reports"
    for domain, span in days.items():
        write_window(
            folder,
            make_report_xml,
            make_record_xml,
            days=span,
            domain=domain,
            failing=domain in failing,
        )
    config = str(write_domains_config(tmp_path / "c.toml", list(days)))

    got, out, err = run(capsys, "verdict", str(folder), "--config", config)

    assert (got, err) == (code, "")
    blocks = blocks_of(out)
    assert len(blocks) == 4
    assert blocks[-1] == tally + "\n"
    assert [domain in block for block, domain in zip(blocks, days, strict=False)] == [True] * 3


def test_verdict_of_one_domain_has_no_rule_and_no_tally(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A run of one domain prints what it always printed (RNF-01)."""
    folder = windows(tmp_path / "reports", make_report_xml, make_record_xml, {_COM: LONG})

    code, out, _err = run(capsys, "verdict", str(folder), "--domain", _COM)

    assert code == 0
    assert RULE not in out
    assert "domains:" not in out


def test_verdict_in_portuguese_counts_the_domains_in_portuguese(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The new line comes from the messages module like every other sentence (RF-05)."""
    folder = windows(tmp_path / "reports", make_report_xml, make_record_xml, {_COM: LONG, _NET: 2})

    code, out, _err = run(
        capsys, "verdict", str(folder), "--domain", _COM, "--domain", _NET, "--lang", "pt-BR"
    )

    assert code == 3
    assert blocks_of(out)[-1] == "2 dominios: 1 pronto, 1 cedo demais\n"


# ---------------------------------------------------------------------------
# A domain with no report, and a run with none (RF-04, ADR-11)
# ---------------------------------------------------------------------------


def test_a_domain_with_no_reports_among_others_is_too_early_and_the_run_goes_on(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The domain that has no report yet does not block the others (RF-04)."""
    folder = windows(tmp_path / "reports", make_report_xml, make_record_xml, {_COM: LONG})
    config = str(write_domains_config(tmp_path / "c.toml", [_COM, _NET]))

    code, out, err = run(capsys, "verdict", str(folder), "--config", config)

    assert (code, err) == (3, "")
    ready, empty, tally = blocks_of(out)
    assert _COM in ready
    assert f"MailVigil verdict for {_NET}" in empty
    assert "no report was kept for this domain" in empty
    assert tally == "2 domains: 1 ready, 1 too early\n"


def test_a_summary_with_a_domain_that_has_no_reports_says_so(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The block of a domain without reports is a block, not a refusal."""
    folder = windows(tmp_path / "reports", make_report_xml, make_record_xml, {_COM: 3})

    code, out, _err = run(capsys, "summary", str(folder), "--domain", _COM, "--domain", _NET)

    assert code == 0
    assert "no reports" in blocks_of(out)[1]


def test_no_report_for_any_domain_is_one_refusal_with_the_count(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The run is refused (1) only when no domain has a report (ADR-11)."""
    empty = tmp_path / "empty"
    empty.mkdir()

    code, out, err = run(capsys, "verdict", str(empty), "--domain", _COM, "--domain", _NET)

    assert (code, out) == (1, "")
    assert err.splitlines()[0] == "No DMARC report for any of the 2 domains was kept."


# ---------------------------------------------------------------------------
# --domain with a file (RF-02, ADR-9)
# ---------------------------------------------------------------------------


def test_domain_with_a_file_picks_the_listed_domains_in_the_order_of_the_file(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--domain`` selects; it does not reorder (RF-02, RNF-03)."""
    folder = windows(
        tmp_path / "reports", make_report_xml, make_record_xml, {_COM: 3, _NET: 3, _ORG: 3}
    )
    config = str(write_domains_config(tmp_path / "c.toml", [_COM, _NET, _ORG]))

    code, out, _err = run(
        capsys, "summary", str(folder), "--config", config, "--domain", _ORG, "--domain", _COM
    )

    assert code == 0
    titles = [block.splitlines()[0] for block in blocks_of(out)]
    assert [domain in title for title, domain in zip(titles, [_COM, _ORG], strict=True)] == [
        True,
        True,
    ]
    assert len(titles) == 2


def test_a_domain_given_twice_is_covered_once(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A repeat, in any case and with a trailing dot, is the same domain (RF-02)."""
    folder = windows(tmp_path / "reports", make_report_xml, make_record_xml, {_COM: 3})

    code, out, _err = run(
        capsys, "summary", str(folder), "--domain", _COM, "--domain", "EXAMPLE.com."
    )

    assert code == 0
    assert len(blocks_of(out)) == 1
    assert RULE not in out


def test_a_domain_the_file_of_several_does_not_list_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The file is the source of the identities; a flag cannot invent a domain (ADR-9)."""
    config = write_domains_config(tmp_path / "c.toml", [_COM, _NET])

    code, out, err = run(
        capsys, "summary", str(tmp_path), "--config", str(config), "--domain", _ORG
    )

    assert (code, out) == (1, "")
    assert err == f"mailvigil: --domain {_ORG} is not one of the domains of {config}\n"


def test_a_domain_the_file_of_one_does_not_name_is_the_mismatch_of_today(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A file of one domain keeps its own sentence (RNF-01)."""
    config = write_domains_config(tmp_path / "c.toml", [_COM])

    code, _out, err = run(
        capsys, "summary", str(tmp_path), "--config", str(config), "--domain", _NET
    )

    assert code == 1
    assert err == f"mailvigil: --domain {_NET} does not match the domain {_COM} of {config}\n"


def test_a_bad_domain_value_is_refused_before_the_file_is_read(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every ``--domain`` is checked first, so a bad one costs no file (ADR-9)."""

    def forbidden(*args: object, **kwargs: object) -> None:
        """Fail the test if the file is read."""
        raise AssertionError("the file was read")

    monkeypatch.setattr("mailvigil.cli.load_configs", forbidden)

    code, _out, err = run(
        capsys,
        "summary",
        str(tmp_path),
        "--config",
        str(tmp_path / "c.toml"),
        "--domain",
        _COM,
        "--domain",
        "not a domain",
    )

    assert code == 1
    assert err == "mailvigil: invalid_domain [--domain]: not a plausible host name\n"


# ---------------------------------------------------------------------------
# --domain without a file (RF-02, ADR-10)
# ---------------------------------------------------------------------------


def test_domains_without_a_file_are_covered_in_the_order_given_with_empty_maps(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The first run: each value is a domain, and nothing is recognized yet (RF-02)."""
    folder = windows(tmp_path / "reports", make_report_xml, make_record_xml, {_COM: 3, _NET: 3})

    code, out, _err = run(capsys, "summary", str(folder), "--domain", _NET, "--domain", _COM)

    assert code == 0
    first, second = blocks_of(out)
    assert _NET in first.splitlines()[0]
    assert _COM in second.splitlines()[0]
    assert "Example Mail" not in out


def test_fifty_one_distinct_domains_without_a_file_are_refused_and_fifty_are_not(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The cap of ADR-10 counts the distinct values, after the repeats are folded."""
    names = [f"d{n}.example" for n in range(MAX_DOMAINS + 1)]
    flags = [flag for name in names for flag in ("--domain", name)]

    code, out, err = run(capsys, "summary", str(tmp_path), *flags)

    assert (code, out) == (1, "")
    assert err.startswith("mailvigil: too_many_domains [--domain]")
    # Fifty values plus a repeat of the first: still fifty distinct domains, so under the cap.
    code, _out, err = run(capsys, "summary", str(tmp_path), *flags[:-2], *flags[:2])
    assert err.splitlines()[0] == (
        f"No DMARC report for any of the {MAX_DOMAINS} domains was kept."
    )


# ---------------------------------------------------------------------------
# A file of several domains that is refused
# ---------------------------------------------------------------------------


def test_a_refused_entry_names_its_place_in_the_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The line carries the path and the key of the entry (RF-01)."""
    config = tmp_path / "c.toml"
    config.write_text(
        '[[domains]]\ndomain = "example.com"\n[[domains]]\ndomain = "example.net"\nsender = 1\n',
        encoding="utf-8",
    )

    code, out, err = run(capsys, "verdict", str(tmp_path), "--config", str(config))

    assert (code, out) == (1, "")
    assert err == (
        f'mailvigil: {config}: unknown_key [domains[2].sender]: did you mean "senders"?\n'
    )


# ---------------------------------------------------------------------------
# --json: the envelope (RF-07, ADR-7)
# ---------------------------------------------------------------------------


def test_summary_json_of_two_domains_is_an_envelope_of_the_one_domain_documents(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Each element is the document of a run of that one domain (RNF-01, RF-07)."""
    first = windows(tmp_path / "a", make_report_xml, make_record_xml, {_COM: LONG})
    second = windows(tmp_path / "b", make_report_xml, make_record_xml, {_NET: LONG})
    config = str(write_domains_config(tmp_path / "c.toml", [_COM, _NET]))

    code, out, err = run(capsys, "summary", str(first), str(second), "--config", config, "--json")

    assert (code, err) == (0, "")
    document = json.loads(out)
    assert list(document) == ["schema_version", "command", "domains"]
    assert document["command"] == "summary"
    alone = [
        json.loads(
            run(capsys, "summary", str(folder), "--config", config, "--domain", domain, "--json")[1]
        )
        for folder, domain in ((first, _COM), (second, _NET))
    ]
    assert document["domains"] == alone
    assert all("domains" not in element for element in alone)


def test_summary_json_of_one_domain_is_the_document_of_today(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A file of two domains narrowed to one by ``--domain`` prints no envelope (ADR-7)."""
    folder = windows(tmp_path / "reports", make_report_xml, make_record_xml, {_COM: LONG})
    config = str(write_domains_config(tmp_path / "c.toml", [_COM, _NET]))

    code, out, _err = run(
        capsys, "summary", str(folder), "--config", config, "--domain", _COM, "--json"
    )

    assert code == 0
    document = json.loads(out)
    assert "domains" not in document
    assert document["domain"] == _COM


@pytest.mark.parametrize(
    ("days", "failing", "code", "answer"),
    [
        ({_COM: LONG, _NET: LONG, _ORG: LONG}, [], 0, "ready"),
        ({_COM: LONG, _NET: 2, _ORG: LONG}, [], 3, "too_early"),
        ({_COM: LONG, _NET: 2, _ORG: LONG}, [_ORG], 4, "not_ready"),
    ],
    ids=["all ready", "one too early", "not ready beats too early"],
)
def test_verdict_json_of_three_domains_carries_the_answer_the_exit_code_stands_for(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
    days: dict[str, int],
    failing: list[str],
    code: int,
    answer: str,
) -> None:
    """The document and the code say the same thing, in the order of the file (RF-06, RF-07)."""
    folder = tmp_path / "reports"
    for domain, span in days.items():
        write_window(
            folder,
            make_report_xml,
            make_record_xml,
            days=span,
            domain=domain,
            failing=domain in failing,
        )
    config = str(write_domains_config(tmp_path / "c.toml", list(days)))

    got, out, err = run(capsys, "verdict", str(folder), "--config", config, "--json")

    assert (got, err) == (code, "")
    document = json.loads(out)
    assert list(document) == ["schema_version", "command", "answer", "domains"]
    assert document["answer"] == answer
    assert [element["domain"] for element in document["domains"]] == list(days)


def test_json_of_several_domains_with_top_trims_each_element(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Each element carries its own ``top`` key; the envelope has none (RF-07)."""
    folder = windows(
        tmp_path / "reports", make_report_xml, make_record_xml, {_COM: LONG, _NET: LONG}
    )

    for command in ("summary", "verdict"):
        _code, out, _err = run(
            capsys, command, str(folder), "--domain", _COM, "--domain", _NET, "--json", "--top", "1"
        )

        document = json.loads(out)
        assert "top" not in document
        assert [element["top"]["limit"] for element in document["domains"]] == [1, 1]


def test_json_of_several_domains_is_ascii_and_the_same_in_portuguese(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The document has no language: ``--lang`` changes neither a byte nor the code (RF-07)."""
    folder = windows(tmp_path / "reports", make_report_xml, make_record_xml, {_COM: LONG, _NET: 2})
    argv = ("verdict", str(folder), "--domain", _COM, "--domain", _NET, "--json")

    english = run(capsys, *argv)
    portuguese = run(capsys, *argv, "--lang", "pt-BR")

    assert english == portuguese
    assert english[1].isascii()
