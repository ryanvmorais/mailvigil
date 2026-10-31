"""
Tests of the reading that serves several domains at once (RF-04, RNF-02 of 010): ``ingest_many``.

Isolation: every report is built in memory by the ``conftest.py`` factories and written under
``tmp_path`` with an attachment name, so a folder is discovered the way a real download folder is;
nothing touches the network, an environment variable or a path outside it. The domains are invented
(``example.com``, ``example.net``, ``example.org``) and the foreign one is ``example.invalid``. The
cost test puts a spy on the two functions that do the work of a file, so it counts what the loop
does and not how long it takes.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from pathlib import Path

import pytest

import mailvigil.reports
from mailvigil.reports import ingest, ingest_many

# The package attribute ``ingest`` is the function, so the module is fetched by name.
ingest_module = importlib.import_module("mailvigil.reports.ingest")

# The shape of the ``conftest.py`` report factory, named once so each test signature stays short.
type _MakeReport = Callable[..., bytes]

# Invented names (RNF-06): ``example.*`` is reserved for documentation, ``.invalid`` never resolves.
_COM = "example.com"
_NET = "example.net"
_ORG = "example.org"
_FOREIGN = "example.invalid"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _attachment(directory: Path, label: str, content: bytes) -> Path:
    """
    Write a file under a name the providers' pattern accepts, so a folder discovers it.

    Args:
        directory (Path): Where to write, normally ``tmp_path``.
        label (str): Tells the files apart; it is the provider part of the name, and it decides the
            discovery order.
        content (bytes): The file content.

    Returns:
        Path: The file written.
    """
    path = directory / f"{label}!example.com!1790000000!1790086399.xml"
    path.write_bytes(content)
    return path


def _mixed_folder(directory: Path, make_report_xml: _MakeReport) -> None:
    """
    Fill a folder with a report for each of three domains, a foreign one and a corrupt file.

    Args:
        directory (Path): The folder, normally ``tmp_path``.
        make_report_xml (_MakeReport): The report factory.
    """
    _attachment(directory, "a", make_report_xml(domain=_COM, report_id="com"))
    _attachment(directory, "b", make_report_xml(domain=_NET, report_id="net"))
    _attachment(directory, "c", make_report_xml(domain=_ORG, report_id="org"))
    _attachment(directory, "d", make_report_xml(domain=_FOREIGN, report_id="foreign"))
    _attachment(directory, "e", b"not a report")
    (directory / "renamed.xml").write_bytes(make_report_xml(domain=_COM, report_id="renamed"))


# ---------------------------------------------------------------------------
# Each report goes to its own domain (RF-04)
# ---------------------------------------------------------------------------


def test_each_report_goes_to_its_own_domain_and_the_results_follow_the_wanted_order(
    tmp_path: Path, make_report_xml: _MakeReport
) -> None:
    _mixed_folder(tmp_path, make_report_xml)

    results = ingest_many([tmp_path], [_ORG, _COM, _NET])

    assert list(results) == [_ORG, _COM, _NET]
    assert [report.report_id for report in results[_COM].reports] == ["com"]
    assert [report.report_id for report in results[_NET].reports] == ["net"]
    assert [report.report_id for report in results[_ORG].reports] == ["org"]


def test_a_report_is_in_exactly_one_result(tmp_path: Path, make_report_xml: _MakeReport) -> None:
    _mixed_folder(tmp_path, make_report_xml)

    results = ingest_many([tmp_path], [_COM, _NET, _ORG])

    kept = [report.source_file for result in results.values() for report in result.reports]
    assert len(kept) == len(set(kept)) == 3


def test_other_domain_counts_only_the_reports_of_no_domain_of_the_run(
    tmp_path: Path, make_report_xml: _MakeReport
) -> None:
    """A report of domain B is not "other domain" in A's result (ADR-4)."""
    _mixed_folder(tmp_path, make_report_xml)

    results = ingest_many([tmp_path], [_COM, _NET, _ORG])

    assert [result.other_domain for result in results.values()] == [1, 1, 1]


def test_a_domain_nobody_reported_for_has_an_empty_result_and_the_run_goes_on(
    tmp_path: Path, make_report_xml: _MakeReport
) -> None:
    _attachment(tmp_path, "a", make_report_xml(domain=_COM, report_id="com"))

    results = ingest_many([tmp_path], [_COM, _NET])

    assert len(results[_COM].reports) == 1
    assert results[_NET].reports == ()
    assert results[_NET].other_domain == 0


def test_the_shared_parts_are_the_same_in_every_result(
    tmp_path: Path, make_report_xml: _MakeReport
) -> None:
    """A file that could not be read cannot be assigned to a domain (ADR-4)."""
    _mixed_folder(tmp_path, make_report_xml)

    results = ingest_many([tmp_path], [_COM, _NET, _ORG])

    skipped = {result.skipped for result in results.values()}
    passed_over = {result.passed_over for result in results.values()}
    assert len(skipped) == 1
    assert len(next(iter(skipped))) == 1
    assert passed_over == {1}


def test_a_name_is_normalized_and_a_repeat_is_one_domain(
    tmp_path: Path, make_report_xml: _MakeReport
) -> None:
    _attachment(tmp_path, "a", make_report_xml(domain=_COM, report_id="com"))

    results = ingest_many([tmp_path], ["  Example.COM. ", _COM, _NET])

    assert list(results) == [_COM, _NET]
    assert len(results[_COM].reports) == 1


# ---------------------------------------------------------------------------
# Duplicates are per domain (ADR-4)
# ---------------------------------------------------------------------------


def test_a_duplicate_is_counted_in_its_own_domain(
    tmp_path: Path, make_report_xml: _MakeReport
) -> None:
    _attachment(tmp_path, "a", make_report_xml(domain=_COM, report_id="r1"))
    _attachment(tmp_path, "b", make_report_xml(domain=_COM, report_id="r1"))
    _attachment(tmp_path, "c", make_report_xml(domain=_NET, report_id="r2"))

    results = ingest_many([tmp_path], [_COM, _NET])

    assert (results[_COM].duplicates, len(results[_COM].reports)) == (1, 1)
    assert (results[_NET].duplicates, len(results[_NET].reports)) == (0, 1)


def test_the_same_reporter_and_id_under_two_domains_is_not_a_duplicate(
    tmp_path: Path, make_report_xml: _MakeReport
) -> None:
    _attachment(tmp_path, "a", make_report_xml(domain=_COM, report_id="r1"))
    _attachment(tmp_path, "b", make_report_xml(domain=_NET, report_id="r1"))

    results = ingest_many([tmp_path], [_COM, _NET])

    assert [len(result.reports) for result in results.values()] == [1, 1]
    assert [result.duplicates for result in results.values()] == [0, 0]


# ---------------------------------------------------------------------------
# The one-domain call is the loop of one (ADR-3)
# ---------------------------------------------------------------------------


def test_ingest_is_ingest_many_with_one_domain(
    tmp_path: Path, make_report_xml: _MakeReport
) -> None:
    _mixed_folder(tmp_path, make_report_xml)

    assert ingest([tmp_path], _COM) == ingest_many([tmp_path], [_COM])[_COM]


def test_the_many_domain_result_of_one_domain_is_what_a_run_of_that_domain_gives(
    tmp_path: Path, make_report_xml: _MakeReport
) -> None:
    """Besides ``other_domain``, which the other domains of the run no longer feed."""
    _mixed_folder(tmp_path, make_report_xml)

    alone = ingest([tmp_path], _NET)
    together = ingest_many([tmp_path], [_COM, _NET, _ORG])[_NET]

    assert (together.reports, together.skipped, together.duplicates, together.passed_over) == (
        alone.reports,
        alone.skipped,
        alone.duplicates,
        alone.passed_over,
    )
    assert (alone.other_domain, together.other_domain) == (3, 1)


def test_ingest_many_is_public() -> None:
    assert "ingest_many" in mailvigil.reports.__all__


@pytest.mark.parametrize("domains", [[], [""], ["   "], [_COM, ""], [_COM, "."]])
def test_an_empty_list_or_an_empty_name_is_a_programming_error(
    domains: list[str], tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match="domain"):
        ingest_many([tmp_path], domains)


# ---------------------------------------------------------------------------
# The cost does not grow with the number of domains (RNF-02)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("domains", [[_COM], [_COM, _NET, _ORG], [_COM, _NET, _ORG, _FOREIGN]])
def test_each_file_is_opened_and_each_report_parsed_once_whatever_the_number_of_domains(
    domains: list[str],
    tmp_path: Path,
    make_report_xml: _MakeReport,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mixed_folder(tmp_path, make_report_xml)
    opened: list[Path] = []
    parsed: list[str] = []
    real_read, real_parse = ingest_module.read_xml, ingest_module.parse_report

    def spy_read(path: Path) -> bytes:
        """Count the opening of a file and return what the real reader gives."""
        opened.append(path)
        return real_read(path)

    def spy_parse(xml: bytes, *, source: str = "") -> mailvigil.reports.Report:
        """Count the parsing of a report and hand it to the real parser."""
        parsed.append(source)
        return real_parse(xml, source=source)

    monkeypatch.setattr(ingest_module, "read_xml", spy_read)
    monkeypatch.setattr(ingest_module, "parse_report", spy_parse)

    ingest_many([tmp_path], domains)

    # Five files are discovered; the corrupt one is opened but never parsed to a report.
    assert len(opened) == len(set(opened)) == 5
    assert len(parsed) == len(set(parsed)) == 5
