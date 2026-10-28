"""
Tests of ingestion (RF-07, RF-08, RF-09, RF-10, RNF-02, RNF-05): ``ingest`` and the public API.

Isolation: every report is built in memory by the ``conftest.py`` factories and written under
``tmp_path`` with an attachment name, so a folder is discovered the way a real download folder is;
nothing touches the network, an environment variable or a path outside it. The hostile files are the
attack itself, so a failure in the refusal table means a defense is gone.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

import mailvigil.reports
from mailvigil.reports import (
    MAX_BYTES,
    MAX_TEXT,
    DkimResult,
    IngestionResult,
    OverrideReason,
    PolicyPublished,
    Reason,
    Record,
    Report,
    ReportRefused,
    SkippedFile,
    SpfResult,
    discover,
    ingest,
    parse_report,
    read_xml,
)

# The shapes of the ``conftest.py`` factories, named once so each test signature stays short.
type _MakeReport = Callable[..., bytes]
type _MakeRecord = Callable[..., str]
type _MakeZip = Callable[[Mapping[str, bytes]], bytes]
type _MakeGzip = Callable[[bytes], bytes]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _attachment(directory: Path, label: str, content: bytes, extension: str = "xml") -> Path:
    """
    Write a file under a name the providers' pattern accepts, so a folder discovers it.

    Args:
        directory (Path): Where to write, normally ``tmp_path``.
        label (str): Tells the files apart; it is the provider part of the name, and it decides the
            discovery order.
        content (bytes): The file content.
        extension (str, optional): ``xml``, ``gz`` or ``zip``. Default: ``xml``.

    Returns:
        Path: The file written.
    """
    path = directory / f"{label}!example.com!1790000000!1790086399.{extension}"
    path.write_bytes(content)
    return path


def _snapshot(directory: Path) -> dict[str, bytes | None]:
    """
    Record everything under a folder: each path, and the content of each file.

    Args:
        directory (Path): The folder to look at.

    Returns:
        dict[str, bytes | None]: Relative path to content; ``None`` for a folder.
    """
    return {
        str(path.relative_to(directory)): path.read_bytes() if path.is_file() else None
        for path in sorted(directory.rglob("*"))
    }


# ---------------------------------------------------------------------------
# One bad file never stops the others (RF-09, RF-10)
# ---------------------------------------------------------------------------


def test_a_good_report_is_returned_and_every_refusal_is_listed_with_its_reason(
    tmp_path: Path, make_report_xml: _MakeReport, make_zip: _MakeZip, make_gzip: _MakeGzip
) -> None:
    good = make_report_xml(report_id="good")
    refused: dict[str, tuple[bytes, str, Reason]] = {
        "doctype": (
            b'<?xml version="1.0"?><!DOCTYPE feedback [<!ENTITY x "y">]><feedback/>',
            "xml",
            Reason.FORBIDDEN_DECLARATION,
        ),
        "malformed": (b"<feedback><a></feedback>", "xml", Reason.MALFORMED_XML),
        "notreport": (make_report_xml(root_tag="other"), "xml", Reason.NOT_A_REPORT),
        "version": (make_report_xml(version="2.0"), "xml", Reason.UNSUPPORTED_VERSION),
        "field": (make_report_xml(pct=101), "xml", Reason.INVALID_FIELD),
        "corrupt": (b"this is not gzip", "gz", Reason.NOT_AN_ARCHIVE),
        "noxml": (make_zip({"readme.txt": b"hi"}), "zip", Reason.NO_XML_MEMBER),
        "twoxml": (make_zip({"a.xml": good, "b.xml": good}), "zip", Reason.MULTIPLE_XML_MEMBERS),
        "bomb": (make_gzip(bytes(MAX_BYTES + 1)), "gz", Reason.DECOMPRESSED_TOO_LARGE),
        "huge": (bytes(MAX_BYTES + 1), "xml", Reason.FILE_TOO_LARGE),
    }
    _attachment(tmp_path, "good", good)
    for label, (content, extension, _) in refused.items():
        _attachment(tmp_path, label, content, extension)
    # The two refusals a folder never produces, because discovery filters by name or lists what
    # exists: a file the user named that is no attachment, and a path that is not there.
    named = tmp_path / "notes.txt"
    named.write_text("not a report")
    missing = tmp_path / "gone.zip"

    result = ingest([tmp_path, named, missing], "example.com")

    assert [report.report_id for report in result.reports] == ["good"]
    by_provider = {entry.path.name.split("!")[0]: entry.reason for entry in result.skipped}
    expected = {label: reason for label, (_, _, reason) in refused.items()}
    expected |= {"notes.txt": Reason.UNSUPPORTED_EXTENSION, "gone.zip": Reason.UNREADABLE}
    assert by_provider == expected
    # Every way to be refused is exercised, so a new ``Reason`` has to come with a test. The four
    # about mail messages are exercised by the ingestion tests of spec 007, not by loose files.
    message_reasons = {
        Reason.MESSAGE_TOO_LARGE,
        Reason.MESSAGE_TOO_COMPLEX,
        Reason.NO_REPORT_ATTACHMENT,
        Reason.MALFORMED_MESSAGE,
    }
    assert set(by_provider.values()) == set(Reason) - message_reasons
    assert (result.duplicates, result.other_domain) == (0, 0)


def test_skipped_files_come_in_discovery_order(tmp_path: Path) -> None:
    for label in ("b", "a", "c"):
        _attachment(tmp_path, label, b"not xml")

    result = ingest([tmp_path], "example.com")

    assert [entry.path.name.split("!")[0] for entry in result.skipped] == ["a", "b", "c"]


def test_an_empty_folder_gives_an_empty_result(tmp_path: Path) -> None:
    assert ingest([tmp_path], "example.com") == IngestionResult()


def test_a_path_that_is_not_there_does_not_stop_a_good_report(
    tmp_path: Path, make_report_xml: _MakeReport
) -> None:
    good = _attachment(tmp_path, "good", make_report_xml())
    missing = tmp_path / "gone.zip"

    result = ingest([missing, good], "example.com")

    assert len(result.reports) == 1
    assert [(entry.path, entry.reason) for entry in result.skipped] == [
        (missing, Reason.UNREADABLE)
    ]


def test_the_source_file_of_a_report_is_its_file_name(
    tmp_path: Path, make_report_xml: _MakeReport
) -> None:
    path = _attachment(tmp_path, "good", make_report_xml())

    (report,) = ingest([path], "example.com").reports

    assert report.source_file == path.name


# ---------------------------------------------------------------------------
# Domain filter (RF-07)
# ---------------------------------------------------------------------------


def test_the_domain_filter_is_exact_and_ignores_case_and_a_trailing_dot(
    tmp_path: Path, make_report_xml: _MakeReport
) -> None:
    _attachment(tmp_path, "a", make_report_xml(domain="EXAMPLE.com", report_id="a"))
    _attachment(tmp_path, "b", make_report_xml(domain="example.com", report_id="b"))

    result = ingest([tmp_path], "  Example.COM. ")

    assert [report.report_id for report in result.reports] == ["a", "b"]
    assert result.other_domain == 0


def test_a_subdomain_and_a_parent_are_another_domain(
    tmp_path: Path, make_report_xml: _MakeReport
) -> None:
    _attachment(tmp_path, "sub", make_report_xml(domain="mail.example.com", report_id="sub"))
    _attachment(tmp_path, "parent", make_report_xml(domain="com", report_id="parent"))
    _attachment(tmp_path, "same", make_report_xml(domain="example.com", report_id="same"))

    result = ingest([tmp_path], "example.com")

    assert [report.report_id for report in result.reports] == ["same"]
    assert result.other_domain == 2


def test_no_report_for_the_domain_still_counts_the_other_domains(
    tmp_path: Path, make_report_xml: _MakeReport
) -> None:
    _attachment(tmp_path, "a", make_report_xml(domain="example.org", report_id="a"))
    _attachment(tmp_path, "b", make_report_xml(domain="example.net", report_id="b"))

    result = ingest([tmp_path], "example.com")

    assert result.reports == ()
    assert result.skipped == ()
    assert result.other_domain == 2


@pytest.mark.parametrize("domain", ["", "   ", ".", " . "])
def test_an_empty_domain_is_a_programming_error(domain: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="domain"):
        ingest([tmp_path], domain)


# ---------------------------------------------------------------------------
# Duplicates (RF-08)
# ---------------------------------------------------------------------------


def test_the_same_reporter_and_id_twice_counts_one_duplicate_and_does_not_sum_records(
    tmp_path: Path, make_report_xml: _MakeReport, make_record_xml: _MakeRecord
) -> None:
    first = make_report_xml(report_id="r1", records=[make_record_xml(count=3)])
    # Same report downloaded again, here with different records to prove which one was kept.
    second = make_report_xml(report_id="r1", records=[make_record_xml(count=40)])
    _attachment(tmp_path, "a", first)
    _attachment(tmp_path, "b", second)

    result = ingest([tmp_path], "example.com")

    assert len(result.reports) == 1
    assert [record.count for record in result.reports[0].records] == [3]
    assert result.duplicates == 1


def test_the_same_id_from_two_reporters_is_kept(
    tmp_path: Path, make_report_xml: _MakeReport
) -> None:
    _attachment(tmp_path, "a", make_report_xml(reporter="Example Mail", report_id="r1"))
    _attachment(tmp_path, "b", make_report_xml(reporter="Other Mail", report_id="r1"))

    result = ingest([tmp_path], "example.com")

    assert [report.reporter for report in result.reports] == ["Example Mail", "Other Mail"]
    assert result.duplicates == 0


def test_a_report_of_another_domain_is_never_a_duplicate(
    tmp_path: Path, make_report_xml: _MakeReport
) -> None:
    """The domain filter runs first, so other-domain reports never feed the duplicate rule."""
    # Two other-domain reports with one id are two "other domain", and an other-domain report does
    # not make a later one for the wanted domain a duplicate.
    _attachment(tmp_path, "a", make_report_xml(domain="example.org", report_id="r1"))
    _attachment(tmp_path, "b", make_report_xml(domain="example.org", report_id="r1"))
    _attachment(tmp_path, "c", make_report_xml(domain="example.com", report_id="r1"))

    result = ingest([tmp_path], "example.com")

    assert len(result.reports) == 1
    assert (result.duplicates, result.other_domain) == (0, 2)


def test_the_same_file_given_twice_is_not_a_duplicate_report(
    tmp_path: Path, make_report_xml: _MakeReport
) -> None:
    # Discovery reads it once, so the duplicate counter stays for files that are really distinct.
    path = _attachment(tmp_path, "a", make_report_xml())

    result = ingest([path, tmp_path], "example.com")

    assert len(result.reports) == 1
    assert result.duplicates == 0


# ---------------------------------------------------------------------------
# Containers: gzip and zip go through the whole chain
# ---------------------------------------------------------------------------


def test_reports_are_read_from_xml_gz_and_zip(
    tmp_path: Path, make_report_xml: _MakeReport, make_gzip: _MakeGzip, make_zip: _MakeZip
) -> None:
    _attachment(tmp_path, "a", make_report_xml(report_id="plain"))
    _attachment(tmp_path, "b", make_gzip(make_report_xml(report_id="gzipped")), "gz")
    _attachment(tmp_path, "c", make_zip({"r.xml": make_report_xml(report_id="zipped")}), "zip")

    result = ingest([tmp_path], "example.com")

    assert [report.report_id for report in result.reports] == ["plain", "gzipped", "zipped"]
    assert result.skipped == ()


# ---------------------------------------------------------------------------
# Deterministic and read-only (RNF-02, RNF-05)
# ---------------------------------------------------------------------------


def test_ingesting_twice_gives_equal_results(tmp_path: Path, make_report_xml: _MakeReport) -> None:
    _attachment(tmp_path, "b", make_report_xml(report_id="r2"))
    _attachment(tmp_path, "a", make_report_xml(report_id="r1"))
    _attachment(tmp_path, "dup", make_report_xml(report_id="r1"))
    _attachment(tmp_path, "other", make_report_xml(domain="example.org"))
    _attachment(tmp_path, "bad", b"not xml")

    assert ingest([tmp_path], "example.com") == ingest([tmp_path], "example.com")


def test_nothing_is_written_besides_the_inputs(
    tmp_path: Path, make_report_xml: _MakeReport, make_gzip: _MakeGzip, make_zip: _MakeZip
) -> None:
    _attachment(tmp_path, "a", make_report_xml())
    _attachment(tmp_path, "b", make_gzip(make_report_xml(report_id="r2")), "gz")
    _attachment(tmp_path, "c", make_zip({"r.xml": make_report_xml(report_id="r3")}), "zip")
    _attachment(tmp_path, "bad", b"not xml")
    before = _snapshot(tmp_path)

    ingest([tmp_path], "example.com")

    assert _snapshot(tmp_path) == before


# ---------------------------------------------------------------------------
# Public API (RF-09)
# ---------------------------------------------------------------------------


def test_the_public_api_is_exactly_what_the_design_lists() -> None:
    assert set(mailvigil.reports.__all__) == {
        "MAX_BYTES",
        "MAX_TEXT",
        "DkimResult",
        "IngestionResult",
        "OverrideReason",
        "PolicyPublished",
        "Reason",
        "Record",
        "Report",
        "ReportRefused",
        "SkippedFile",
        "SpfResult",
        "discover",
        "ingest",
        "parse_report",
        "read_xml",
    }
    for name in mailvigil.reports.__all__:
        assert hasattr(mailvigil.reports, name)


def test_the_public_functions_work_together(tmp_path: Path, make_report_xml: _MakeReport) -> None:
    # The imports at the top of this file are the check that each name is reachable; this uses the
    # entry points as a caller would, without reaching into a submodule.
    path = _attachment(tmp_path, "a", make_report_xml())

    (found,), skipped = discover([tmp_path])
    report = parse_report(read_xml(found), source=found.name)

    assert (found, skipped) == (path, ())
    assert isinstance(report, Report)
    assert report.policy == PolicyPublished(domain="example.com", p="none")
    assert isinstance(report.records[0], Record)
    assert report.records[0].dkim == (DkimResult("example.com", "s1", "pass"),)
    assert report.records[0].spf == (SpfResult("example.com", "pass"),)
    assert OverrideReason().type == ""
    assert isinstance(SkippedFile(path, Reason.UNREADABLE, ""), SkippedFile)
    assert MAX_TEXT == 255
    with pytest.raises(ReportRefused):
        parse_report(b"<other/>")
