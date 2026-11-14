"""
Tests of the reporter-reliance note through ``main(argv)`` (spec 011, RF-02, RF-03, RF-04, RNF-05).

Isolation: every run reads synthetic reports written in ``tmp_path`` by the ``conftest.py``
factories and the helpers of ``cli_helpers.py``. Domains, organizations and addresses are invented
(``example.com``, ``example.net``; ``192.0.2.0/24``; RNF-06). The note is checked in the three
outputs, for one domain and for several, and the exit code is the one of the answer.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest
from tests.cli_helpers import (
    LONG,
    RecordXml,
    ReportXml,
    write_config,
    write_domains_config,
    write_window,
)
from tests.html_helpers import Page

from mailvigil.cli import main
from mailvigil.render import RULE

# The two sentences the runs below must print, written out so a change of wording fails here.
_ALONE = (
    "Every report came from Example Mail, so the answer rests on its numbers alone. Check that "
    "you recognize this reporter."
)
_HALF = (
    "The answer rests on Example Mail (50.0% of the messages): without its reports it would be "
    "TOO EARLY to say. Check that you recognize this reporter."
)
# The first half of a long window, so each of two organizations alone spans too few days.
_HALF_DAYS = LONG // 2


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


def flat(text: str) -> str:
    """
    Join the wrapped lines of a text, so a sentence can be found whatever the width.

    Args:
        text (str): The text.

    Returns:
        str: The words, one space apart.
    """
    return " ".join(text.split())


def halves(folder: Path, make_report_xml: ReportXml, make_record_xml: RecordXml) -> Path:
    """
    Write a long window whose two halves come from two organizations, with the same messages.

    Args:
        folder (Path): The folder to fill.
        make_report_xml (ReportXml): The report factory.
        make_record_xml (RecordXml): The record factory.

    Returns:
        Path: The folder.
    """
    write_window(folder, make_report_xml, make_record_xml, days=_HALF_DAYS)
    return write_window(
        folder,
        make_report_xml,
        make_record_xml,
        days=LONG - _HALF_DAYS,
        reporter="Other Receiver",
        host="example.org",
        first_day=_HALF_DAYS,
    )


def both(
    folder: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    domain: str = "example.com",
) -> Path:
    """
    Write a long window that two organizations both report on, every day.

    Args:
        folder (Path): The folder to fill.
        make_report_xml (ReportXml): The report factory.
        make_record_xml (RecordXml): The record factory.
        domain (str, optional): The domain. Default: ``example.com``.

    Returns:
        Path: The folder.
    """
    write_window(folder, make_report_xml, make_record_xml, days=LONG, domain=domain)
    return write_window(
        folder,
        make_report_xml,
        make_record_xml,
        days=LONG,
        domain=domain,
        reporter="Other Receiver",
        host="example.org",
    )


# ---------------------------------------------------------------------------
# One domain, the three outputs (RF-02, RF-03, RF-04)
# ---------------------------------------------------------------------------


def test_a_run_from_one_organization_is_ready_with_the_note(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    folder = write_window(tmp_path / "r", make_report_xml, make_record_xml, days=LONG)
    config = str(write_config(tmp_path / "c.toml"))

    code, out, err = run(capsys, "verdict", str(folder), "--config", config)

    assert (code, err) == (0, "")
    assert out.startswith("MailVigil verdict for example.com: READY")
    assert _ALONE in flat(out)


def test_two_halves_of_the_period_name_the_first_name_of_the_tie(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Without either half the period is too short; the tie in messages goes to the name."""
    folder = halves(tmp_path / "r", make_report_xml, make_record_xml)
    config = str(write_config(tmp_path / "c.toml"))

    code, out, err = run(capsys, "verdict", str(folder), "--config", config)

    assert (code, err) == (0, "")
    assert _HALF in flat(out)
    assert "Other Receiver" not in out


def test_two_organizations_over_the_whole_period_give_no_note(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    folder = both(tmp_path / "r", make_report_xml, make_record_xml)
    config = str(write_config(tmp_path / "c.toml"))

    code, out, err = run(capsys, "verdict", str(folder), "--config", config)

    assert (code, err) == (0, "")
    assert "rests on" not in out


def test_a_short_run_from_one_organization_is_too_early_without_the_note(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The note is for ``ready`` only, and the exit code is the answer's (RF-04)."""
    folder = write_window(tmp_path / "r", make_report_xml, make_record_xml, days=3)
    config = str(write_config(tmp_path / "c.toml"))

    for extra in ([], ["--json"], ["--html"]):
        code, out, _err = run(capsys, "verdict", str(folder), "--config", config, *extra)

        assert code == 3
        assert "rests on" not in out
        assert "reporter_reliance" not in out


def test_the_json_note_carries_its_figures(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Its messages, all of them, the organizations and rule 1; its name and the answer."""
    folder = halves(tmp_path / "r", make_report_xml, make_record_xml)
    config = str(write_config(tmp_path / "c.toml"))

    code, out, err = run(capsys, "verdict", str(folder), "--config", config, "--json")

    assert (code, err) == (0, "")
    document = json.loads(out)
    # why: rule 3 measures every message, and each half holds the same number of them.
    total = document["rules"][2]["measured"]
    notes = [note for note in document["notes"] if note["kind"] == "reporter_reliance"]
    assert notes == [
        {
            "kind": "reporter_reliance",
            "numbers": [total // 2, total, 2, 1],
            "texts": ["Example Mail", "too_early"],
        }
    ]


def test_the_page_lists_the_note_with_the_others(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    folder = write_window(tmp_path / "r", make_report_xml, make_record_xml, days=LONG)
    config = str(write_config(tmp_path / "c.toml"))

    code, out, err = run(capsys, "verdict", str(folder), "--config", config, "--html")

    assert (code, err) == (0, "")
    assert _ALONE in Page(out).texts


def test_the_note_is_in_portuguese_with_lang(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    folder = write_window(tmp_path / "r", make_report_xml, make_record_xml, days=LONG)
    config = str(write_config(tmp_path / "c.toml"))

    code, out, _err = run(capsys, "verdict", str(folder), "--config", config, "--lang", "pt-BR")

    assert code == 0
    assert "vieram de Example Mail" in flat(out)


# ---------------------------------------------------------------------------
# Several domains: each its own note or none (RF-03)
# ---------------------------------------------------------------------------


def _two_domains(tmp_path: Path, make_report_xml: ReportXml, make_record_xml: RecordXml) -> str:
    """
    Write ``example.com`` from one organization and ``example.net`` from two, both ready.

    Args:
        tmp_path (Path): The folder of the test.
        make_report_xml (ReportXml): The report factory.
        make_record_xml (RecordXml): The record factory.

    Returns:
        str: The folder of the reports.
    """
    folder = tmp_path / "r"
    write_window(folder, make_report_xml, make_record_xml, days=LONG)
    both(folder, make_report_xml, make_record_xml, domain="example.net")
    write_domains_config(tmp_path / "c.toml", ["example.com", "example.net"])
    return str(folder)


def test_each_domain_of_a_run_gets_its_own_note_or_none_in_text(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    folder = _two_domains(tmp_path, make_report_xml, make_record_xml)

    code, out, err = run(capsys, "verdict", folder, "--config", str(tmp_path / "c.toml"))

    assert (code, err) == (0, "")
    com, net, _tally = out.split(f"\n\n{RULE}\n\n")
    assert _ALONE in flat(com)
    assert "rests on" not in net


def test_each_domain_of_a_run_gets_its_own_note_or_none_in_json(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    folder = _two_domains(tmp_path, make_report_xml, make_record_xml)

    code, out, err = run(capsys, "verdict", folder, "--config", str(tmp_path / "c.toml"), "--json")

    assert (code, err) == (0, "")
    kinds = [[note["kind"] for note in domain["notes"]] for domain in json.loads(out)["domains"]]
    assert ["reporter_reliance" in found for found in kinds] == [True, False]


def test_each_domain_of_a_run_gets_its_own_note_or_none_on_its_page(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    folder = _two_domains(tmp_path, make_report_xml, make_record_xml)
    pages = tmp_path / "pages"
    pages.mkdir()

    code, out, err = run(
        capsys,
        "verdict",
        folder,
        "--config",
        str(tmp_path / "c.toml"),
        "--html",
        "--output",
        str(pages),
    )

    assert (code, out, err) == (0, "", "")
    com = Page((pages / "mailvigil-example.com.html").read_text(encoding="ascii"))
    net = Page((pages / "mailvigil-example.net.html").read_text(encoding="ascii"))
    assert _ALONE in com.texts
    assert not any("rests on" in text for text in net.texts)


# ---------------------------------------------------------------------------
# A hostile organization name (RNF-05)
# ---------------------------------------------------------------------------

# Markup, a tab, a newline and a right-to-left override, written as the XML of a report carries
# them; the ingestion cleans the name (002) and the page escapes what is left.
_HOSTILE = "&lt;b onclick=x&gt;Evil&lt;/b&gt;\t\n&#x202E;Org"


def _page_from(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
    reporter: str,
) -> tuple[str, Page]:
    """
    Run ``verdict`` on a long window from one organization, in text and as a page.

    Args:
        tmp_path (Path): A folder of its own.
        make_report_xml (ReportXml): The report factory.
        make_record_xml (RecordXml): The record factory.
        capsys (pytest.CaptureFixture[str]): The capture of the test.
        reporter (str): The organization, as the XML of the report writes it.

    Returns:
        tuple[str, Page]: The text and the parsed page.
    """
    tmp_path.mkdir()
    folder = write_window(
        tmp_path / "r", make_report_xml, make_record_xml, days=LONG, reporter=reporter
    )
    config = str(write_config(tmp_path / "c.toml"))
    code, out, _err = run(capsys, "verdict", str(folder), "--config", config)
    assert code == 0
    code, page, _err = run(capsys, "verdict", str(folder), "--config", config, "--html")
    assert code == 0
    return out, Page(page)


def shape(page: Page) -> tuple[Counter[str], Counter[str]]:
    """
    Describe the markup of a page without its text: the elements and attributes, counted.

    Args:
        page (Page): The parsed page.

    Returns:
        tuple[Counter[str], Counter[str]]: The tags and the attribute names.
    """
    tags = Counter(tag for tag, _attrs in page.elements)
    names = Counter(name for _tag, attrs in page.elements for name in attrs)
    return tags, names


def test_a_hostile_organization_name_reaches_the_note_cleaned_and_only_as_text(
    tmp_path: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The text has no control character; the page has the markup of an innocent name."""
    out, page = _page_from(tmp_path / "bad", make_report_xml, make_record_xml, capsys, _HOSTILE)
    _out, innocent = _page_from(
        tmp_path / "good", make_report_xml, make_record_xml, capsys, "Innocent"
    )

    assert flat(out).split("Every report came from ", 1)[1].startswith("<b onclick=x>Evil</b>")
    assert "\N{RIGHT-TO-LEFT OVERRIDE}" not in out and "\t" not in out
    assert shape(page) == shape(innocent)
    assert any("Every report came from <b onclick=x>Evil</b>" in text for text in page.texts)
    assert "\N{RIGHT-TO-LEFT OVERRIDE}" not in page.text
