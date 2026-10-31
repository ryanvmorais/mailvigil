"""
Tests of ``verdict --html`` over several domains: one page per domain in a folder (spec 010,
stage 6, RF-07, RNF-05, ADR-8).

Isolation: the commands run through ``main(argv)`` with ``capsys``. Every report is synthetic, built
by the ``conftest.py`` factories and the helpers of ``cli_helpers.py`` from invented domains
(``example.com``, ``example.net``, ``con.example``) and the documentation address ranges (RNF-06).
Every test runs from an empty folder, so no ``mailvigil.toml`` is found by accident. The page of a
domain is compared with the page of a run of that one domain over a folder holding only its
reports, which is the promise of ADR-4 and of RNF-01.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.cli_helpers import LONG, RecordXml, ReportXml, write_domains_config, write_window

from mailvigil.cli import (
    EXIT_INTERNAL,
    EXIT_NOT_READY,
    EXIT_OK,
    EXIT_REFUSED,
    EXIT_TOO_EARLY,
    main,
)

_COM = "example.com"
_NET = "example.net"
_CON = "con.example"
_IDN = "xn--bcher-kva.example"


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


def reports_of(
    root: Path,
    report: ReportXml,
    record: RecordXml,
    domains: dict[str, int],
    *,
    failing: tuple[str, ...] = (),
) -> Path:
    """
    Write the reports of each domain into a folder of its own and into one folder for all.

    Args:
        root (Path): The folder to fill: ``all`` holds every domain, ``<domain>`` only that one.
        report (ReportXml): The report factory.
        record (RecordXml): The record factory.
        domains (dict[str, int]): The days each domain's window spans.
        failing (tuple[str, ...], optional): The domains whose messages fail DMARC.

    Returns:
        Path: The folder that holds every domain.
    """
    root.mkdir(parents=True, exist_ok=True)
    for domain, days in domains.items():
        for target in (root / "all", root / domain):
            write_window(
                target, report, record, days=days, domain=domain, failing=domain in failing
            )
    return root / "all"


# ---------------------------------------------------------------------------
# A folder of pages (RF-07, ADR-8)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("lang", [[], ["--lang", "pt-BR"]], ids=["english", "portuguese"])
def test_each_domain_gets_the_page_of_a_run_of_that_domain_alone(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
    lang: list[str],
) -> None:
    """The folder holds one ASCII page per domain, equal to the single run's, and nothing prints."""
    folder = reports_of(tmp_path / "r", make_report_xml, make_record_xml, {_COM: LONG, _NET: 3})
    config = str(write_domains_config(tmp_path / "c.toml", [_COM, _NET]))
    pages = tmp_path / "pages"
    pages.mkdir()

    code, out, err = run(
        capsys, "verdict", str(folder), "--config", config, "--html", "--output", str(pages), *lang
    )

    assert (code, out, err) == (EXIT_TOO_EARLY, "", "")
    assert sorted(entry.name for entry in pages.iterdir()) == [
        "mailvigil-example.com.html",
        "mailvigil-example.net.html",
    ]
    for domain in (_COM, _NET):
        alone = run(
            capsys,
            "verdict",
            str(tmp_path / "r" / domain),
            "--config",
            config,
            "--domain",
            domain,
            "--html",
            *lang,
        )
        data = (pages / f"mailvigil-{domain}.html").read_bytes()
        assert data.isascii() and b"\r" not in data
        assert data == alone[1].encode("ascii")


def test_the_exit_code_is_the_worst_answer_and_the_pages_are_still_written(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    folder = reports_of(
        tmp_path / "r",
        make_report_xml,
        make_record_xml,
        {_COM: LONG, _NET: LONG},
        failing=(_NET,),
    )
    config = str(write_domains_config(tmp_path / "c.toml", [_COM, _NET]))
    pages = tmp_path / "pages"
    pages.mkdir()

    code, out, _err = run(
        capsys, "verdict", str(folder), "--config", config, "--html", "--output", str(pages)
    )

    assert (code, out) == (EXIT_NOT_READY, "")
    assert len(list(pages.iterdir())) == 2


def test_a_domain_named_like_a_device_gets_a_safe_name_and_an_idn_its_xn_name(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The prefix keeps ``con`` from a reserved name; the file name comes from the ASCII form."""
    folder = reports_of(tmp_path / "r", make_report_xml, make_record_xml, {_CON: LONG, _IDN: LONG})
    config = str(write_domains_config(tmp_path / "c.toml", [_CON, _IDN]))
    pages = tmp_path / "pages"
    pages.mkdir()

    code, _out, _err = run(
        capsys, "verdict", str(folder), "--config", config, "--html", "--output", str(pages)
    )

    assert code == EXIT_OK
    assert sorted(entry.name for entry in pages.iterdir()) == [
        "mailvigil-con.example.html",
        "mailvigil-xn--bcher-kva.example.html",
    ]


def test_domains_given_by_flag_are_written_the_same_way(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    folder = reports_of(tmp_path / "r", make_report_xml, make_record_xml, {_COM: LONG, _NET: LONG})
    pages = tmp_path / "pages"
    pages.mkdir()

    code, out, err = run(
        capsys,
        "verdict",
        str(folder),
        "--domain",
        _COM,
        "--domain",
        _NET,
        "--html",
        "--output",
        str(pages),
    )

    assert (out, err) == ("", "")
    assert code != EXIT_REFUSED
    assert len(list(pages.iterdir())) == 2


def test_a_page_already_there_is_replaced_and_no_temporary_file_stays(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    folder = reports_of(tmp_path / "r", make_report_xml, make_record_xml, {_COM: LONG, _NET: LONG})
    config = str(write_domains_config(tmp_path / "c.toml", [_COM, _NET]))
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "mailvigil-example.com.html").write_text("old page", encoding="ascii")

    run(capsys, "verdict", str(folder), "--config", config, "--html", "--output", str(pages))

    assert (pages / "mailvigil-example.com.html").read_bytes().startswith(b"<!doctype html>")
    assert not [entry for entry in pages.iterdir() if entry.suffix == ".tmp"]


def test_a_relative_folder_is_the_one_of_the_working_directory(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
    empty_cwd: Path,
) -> None:
    folder = reports_of(tmp_path / "r", make_report_xml, make_record_xml, {_COM: LONG, _NET: LONG})
    config = str(write_domains_config(tmp_path / "c.toml", [_COM, _NET]))
    (empty_cwd / "pages").mkdir()

    run(capsys, "verdict", str(folder), "--config", config, "--html", "--output", "pages")

    assert len(list((empty_cwd / "pages").iterdir())) == 2


# ---------------------------------------------------------------------------
# Hostile text stays text (RNF-05)
# ---------------------------------------------------------------------------


def test_the_pages_have_no_script_and_no_network(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    folder = reports_of(tmp_path / "r", make_report_xml, make_record_xml, {_COM: LONG, _NET: LONG})
    config = str(write_domains_config(tmp_path / "c.toml", [_COM, _NET]))
    pages = tmp_path / "pages"
    pages.mkdir()

    run(capsys, "verdict", str(folder), "--config", config, "--html", "--output", str(pages))

    for page in pages.iterdir():
        text = page.read_text(encoding="ascii").lower()
        assert "<script" not in text
        assert "http://" not in text and "https://" not in text
        assert "url(" not in text and "@import" not in text


# ---------------------------------------------------------------------------
# Refusals (RF-07, ADR-8)
# ---------------------------------------------------------------------------


def _forbid_reading(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Make the test fail if a report is read.

    Args:
        monkeypatch (pytest.MonkeyPatch): Used to replace the reader.
    """

    def forbidden(*args: object, **kwargs: object) -> None:
        """Fail the test if a report is read."""
        raise AssertionError("a report was read")

    monkeypatch.setattr("mailvigil.cli.ingest_many", forbidden)


@pytest.mark.parametrize(
    ("lang", "phrase"),
    [
        ([], "--html of 2 domains writes one page each: pass --output FOLDER"),
        (["--lang", "pt-BR"], "--html de 2 dominios"),
    ],
    ids=["english", "portuguese"],
)
def test_several_domains_without_output_are_refused_before_any_report_is_read(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    lang: list[str],
    phrase: str,
) -> None:
    _forbid_reading(monkeypatch)

    code, out, err = run(
        capsys, "verdict", str(tmp_path), "--domain", _COM, "--domain", _NET, "--html", *lang
    )

    assert (code, out) == (EXIT_REFUSED, "")
    assert err.startswith("mailvigil: ") and phrase in err
    assert err.count("\n") == 1


@pytest.mark.parametrize("kind", ["missing", "file"])
def test_an_output_that_is_not_a_folder_is_refused_before_any_report_is_read(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    _forbid_reading(monkeypatch)
    target = tmp_path / "pages"
    if kind == "file":
        target.write_text("a file", encoding="ascii")

    code, out, err = run(
        capsys,
        "verdict",
        str(tmp_path),
        "--domain",
        _COM,
        "--domain",
        _NET,
        "--html",
        "--output",
        str(target),
    )

    assert (code, out) == (EXIT_REFUSED, "")
    assert err.startswith("mailvigil: --output ") and "is not an existing folder" in err
    assert not target.exists() or target.read_text(encoding="ascii") == "a file"


def test_a_page_that_cannot_be_written_is_named_and_the_earlier_ones_are_whole(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    folder = reports_of(tmp_path / "r", make_report_xml, make_record_xml, {_COM: LONG, _NET: LONG})
    config = str(write_domains_config(tmp_path / "c.toml", [_COM, _NET]))
    pages = tmp_path / "pages"
    pages.mkdir()
    # A folder where the second page belongs: the write cannot replace it, on any system.
    (pages / "mailvigil-example.net.html").mkdir()

    code, out, err = run(
        capsys, "verdict", str(folder), "--config", config, "--html", "--output", str(pages)
    )

    assert (code, out) == (EXIT_REFUSED, "")
    assert err.startswith("mailvigil: could not write ") and "mailvigil-example.net.html" in err
    assert err.count("\n") == 1
    assert (pages / "mailvigil-example.com.html").read_bytes().startswith(b"<!doctype html>")
    assert sorted(entry.name for entry in pages.iterdir()) == [
        "mailvigil-example.com.html",
        "mailvigil-example.net.html",
    ]


def test_every_page_is_rendered_before_the_first_is_written(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A renderer that fails on the second domain leaves the folder empty (ADR-8)."""
    folder = reports_of(tmp_path / "r", make_report_xml, make_record_xml, {_COM: LONG, _NET: LONG})
    config = str(write_domains_config(tmp_path / "c.toml", [_COM, _NET]))
    pages = tmp_path / "pages"
    pages.mkdir()
    calls: list[int] = []

    def failing_second(*args: object, **kwargs: object) -> str:
        """Render nothing, and fail on the second call."""
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("boom")
        return "<!doctype html>\n"

    monkeypatch.setattr("mailvigil.cli.render_html", failing_second)

    code, _out, _err = run(
        capsys, "verdict", str(folder), "--config", config, "--html", "--output", str(pages)
    )

    assert code == EXIT_INTERNAL
    assert list(pages.iterdir()) == []


def test_no_reports_for_any_domain_writes_no_page(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = str(write_domains_config(tmp_path / "c.toml", [_COM, _NET]))
    empty = tmp_path / "reports"
    empty.mkdir()
    pages = tmp_path / "pages"
    pages.mkdir()

    code, out, _err = run(
        capsys, "verdict", str(empty), "--config", config, "--html", "--output", str(pages)
    )

    assert (code, out) == (EXIT_REFUSED, "")
    assert list(pages.iterdir()) == []


def test_json_with_html_is_still_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as stop:
        main(["verdict", str(tmp_path), "--domain", _COM, "--domain", _NET, "--json", "--html"])

    assert stop.value.code == 2
    assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# One domain: nothing changes (RF-07, RNF-01)
# ---------------------------------------------------------------------------


def test_one_domain_still_prints_the_page_or_writes_the_file(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    folder = reports_of(tmp_path / "r", make_report_xml, make_record_xml, {_COM: LONG})
    config = str(write_domains_config(tmp_path / "c.toml", [_COM]))
    target = tmp_path / "report.html"

    printed = run(capsys, "verdict", str(folder), "--config", config, "--html")
    written = run(
        capsys, "verdict", str(folder), "--config", config, "--html", "--output", str(target)
    )

    assert printed[1].startswith("<!doctype html>") and printed[2] == ""
    assert written[1:] == ("", "")
    assert target.read_bytes() == printed[1].encode("ascii")
