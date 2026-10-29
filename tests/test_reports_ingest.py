"""
Tests of ingestion (RF-07, RF-08, RF-09, RF-10, RNF-02, RNF-05 of 002; RF-01, RF-02, RF-07, RF-08
of 007): ``ingest`` and the public API.

Isolation: every report is built in memory by the ``conftest.py`` factories and written under
``tmp_path`` with an attachment name, so a folder is discovered the way a real download folder is;
a mail message is built with ``email.message.EmailMessage`` and a mailbox is messages joined with
separator lines; nothing touches the network, an environment variable or a path outside it. The
hostile files are the attack itself, so a failure in the refusal table means a defense is gone.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from tests.mail_helpers import build_eml, build_mbox

import mailvigil.reports
from mailvigil.reports import (
    MAX_BYTES,
    MAX_LINES,
    MAX_MESSAGE_BYTES,
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
from mailvigil.reports.ingest import FUTURE_TOLERANCE

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
# Mail files (007: RF-01, RF-02, RF-07, RF-08)
# ---------------------------------------------------------------------------


def test_the_same_report_as_a_loose_zip_and_inside_an_eml_is_kept_once(
    tmp_path: Path, make_report_xml: _MakeReport, make_zip: _MakeZip
) -> None:
    content = make_zip({"r.xml": make_report_xml(report_id="r1")})
    _attachment(tmp_path, "a", content, "zip")
    (tmp_path / "inbox.eml").write_bytes(build_eml(("report.zip", "zip", content)))

    result = ingest([tmp_path], "example.com")

    assert len(result.reports) == 1
    assert result.duplicates == 1
    assert result.skipped == ()


def test_each_kind_of_attachment_in_a_message_is_read(
    tmp_path: Path, make_report_xml: _MakeReport, make_gzip: _MakeGzip, make_zip: _MakeZip
) -> None:
    path = tmp_path / "inbox.eml"
    path.write_bytes(
        build_eml(
            ("a.xml", "xml", make_report_xml(report_id="plain")),
            ("b.xml.gz", "gzip", make_gzip(make_report_xml(report_id="gzipped"))),
            (None, "zip", make_zip({"r.xml": make_report_xml(report_id="zipped")})),
        )
    )

    result = ingest([path], "example.com")

    assert [report.report_id for report in result.reports] == ["plain", "gzipped", "zipped"]
    assert result.skipped == ()


def test_a_mailbox_gives_its_reports_in_file_order_and_stays_silent_about_other_mail(
    tmp_path: Path, make_report_xml: _MakeReport
) -> None:
    path = tmp_path / "inbox.mbox"
    path.write_bytes(
        build_mbox(
            build_eml(("a.xml", "xml", make_report_xml(report_id="first"))),
            build_eml(),  # an ordinary message: not a report, and a mailbox is full of them
            build_eml(("b.xml", "xml", make_report_xml(report_id="second", domain="example.org"))),
            build_eml(("c.xml", "xml", make_report_xml(report_id="third"))),
        )
    )

    result = ingest([path], "example.com")

    assert [report.report_id for report in result.reports] == ["first", "third"]
    assert result.other_domain == 1
    assert result.skipped == ()


def test_an_explicit_eml_with_no_attachment_is_said_and_the_same_file_in_a_folder_is_not(
    tmp_path: Path,
) -> None:
    path = tmp_path / "plain.eml"
    path.write_bytes(build_eml())

    named = ingest([path], "example.com")
    listed = ingest([tmp_path], "example.com")

    assert [(entry.path, entry.reason, entry.part) for entry in named.skipped] == [
        (path, Reason.NO_REPORT_ATTACHMENT, "")
    ]
    assert listed.skipped == ()


def test_a_bad_attachment_is_refused_with_its_part_and_the_good_one_is_kept(
    tmp_path: Path, make_report_xml: _MakeReport
) -> None:
    path = tmp_path / "inbox.eml"
    path.write_bytes(
        build_eml(
            ("bad.xml", "xml", b"<feedback><a></feedback>"),
            ("good.xml", "xml", make_report_xml()),
        )
    )

    result = ingest([path], "example.com")

    assert len(result.reports) == 1
    assert [(entry.path, entry.reason, entry.part) for entry in result.skipped] == [
        (path, Reason.MALFORMED_XML, "bad.xml")
    ]


def test_a_mailbox_refusal_names_the_message_and_the_attachment(
    tmp_path: Path, make_report_xml: _MakeReport
) -> None:
    path = tmp_path / "inbox.mbox"
    path.write_bytes(
        build_mbox(
            build_eml(("a.xml", "xml", make_report_xml(report_id="a"))),
            build_eml(("broken.gz", "gzip", b"this is not gzip")),
            build_eml((None, "xml", b"<other/>")),
        )
    )

    result = ingest([path], "example.com")

    assert len(result.reports) == 1
    assert [(entry.reason, entry.part) for entry in result.skipped] == [
        (Reason.NOT_AN_ARCHIVE, "#2 broken.gz"),
        (Reason.NOT_A_REPORT, "#3"),
    ]


def test_the_source_file_of_a_report_in_a_message_is_the_file_and_the_part(
    tmp_path: Path, make_report_xml: _MakeReport
) -> None:
    eml = tmp_path / "one.eml"
    eml.write_bytes(build_eml(("report.xml", "xml", make_report_xml(report_id="e"))))
    mbox = tmp_path / "many.mbox"
    mbox.write_bytes(
        build_mbox(
            build_eml(),
            build_eml(("report.xml", "xml", make_report_xml(report_id="m"))),
            build_eml(),
        )
    )

    result = ingest([eml, mbox], "example.com")

    assert [report.source_file for report in result.reports] == [
        "one.eml: report.xml",
        "many.mbox: #2 report.xml",
    ]


def test_an_attachment_with_no_name_is_still_told_apart_by_its_message(
    tmp_path: Path, make_report_xml: _MakeReport
) -> None:
    path = tmp_path / "inbox.mbox"
    path.write_bytes(
        build_mbox(build_eml(), build_eml((None, "xml", make_report_xml(report_id="n"))))
    )

    (report,) = ingest([path], "example.com").reports

    assert report.source_file == "inbox.mbox: #2"


def test_an_oversized_message_in_a_mailbox_costs_one_entry_and_the_run_goes_on(
    tmp_path: Path, make_report_xml: _MakeReport
) -> None:
    path = tmp_path / "inbox.mbox"
    oversized = b"Subject: huge\n\n" + b"A" * MAX_MESSAGE_BYTES + b"\n"
    path.write_bytes(
        build_mbox(
            build_eml(("a.xml", "xml", make_report_xml(report_id="before"))),
            oversized,
            build_eml(("b.xml", "xml", make_report_xml(report_id="after"))),
        )
    )

    result = ingest([path], "example.com")

    assert [report.report_id for report in result.reports] == ["before", "after"]
    assert [(entry.path, entry.reason, entry.part) for entry in result.skipped] == [
        (path, Reason.MESSAGE_TOO_LARGE, "#2")
    ]


def test_a_whole_eml_that_is_refused_has_no_part(tmp_path: Path) -> None:
    too_large = tmp_path / "large.eml"
    too_large.write_bytes(b"A" * (MAX_MESSAGE_BYTES + 1))
    too_complex = tmp_path / "complex.eml"
    too_complex.write_bytes(b"\n" * (MAX_LINES + 1))

    result = ingest([too_large, too_complex], "example.com")

    assert [(entry.path.name, entry.reason, entry.part) for entry in result.skipped] == [
        ("large.eml", Reason.MESSAGE_TOO_LARGE, ""),
        ("complex.eml", Reason.MESSAGE_TOO_COMPLEX, ""),
    ]


def test_a_message_of_a_mailbox_the_reader_refuses_is_named_by_its_number(
    tmp_path: Path, make_report_xml: _MakeReport
) -> None:
    path = tmp_path / "inbox.mbox"
    path.write_bytes(
        build_mbox(
            build_eml(("a.xml", "xml", make_report_xml(report_id="a"))),
            b"\n" * (MAX_LINES + 1),
        )
    )

    result = ingest([path], "example.com")

    assert len(result.reports) == 1
    assert [(entry.reason, entry.part) for entry in result.skipped] == [
        (Reason.MESSAGE_TOO_COMPLEX, "#2")
    ]


def test_a_mailbox_that_cannot_be_opened_is_skipped_and_the_others_are_still_read(
    tmp_path: Path, make_report_xml: _MakeReport, monkeypatch: pytest.MonkeyPatch
) -> None:
    locked = tmp_path / "locked.mbox"
    locked.write_bytes(build_mbox(build_eml()))
    good = tmp_path / "good.eml"
    good.write_bytes(build_eml(("a.xml", "xml", make_report_xml())))
    real_open = Path.open

    # ``Any``: the signature of ``Path.open`` is forwarded as it comes.
    def open_(self: Path, *args: Any, **kwargs: Any) -> Any:
        """Open any file as usual, except ``locked``, which pretends to deny permission."""
        if self == locked:
            raise PermissionError(13, "denied")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_)

    result = ingest([locked, good], "example.com")

    assert len(result.reports) == 1
    assert [(entry.path, entry.reason, entry.part) for entry in result.skipped] == [
        (locked, Reason.UNREADABLE, "")
    ]


def test_a_mailbox_that_is_not_a_regular_file_is_refused_without_being_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A pipe cannot be built the same way on every platform, so the check is made to fail instead;
    # ``open`` is replaced by a trap because opening a real pipe would block the run.
    path = tmp_path / "pipe.mbox"
    path.write_bytes(build_mbox(build_eml()))
    # The package re-exports the function ``ingest``, so the module is looked up by name.
    module = importlib.import_module("mailvigil.reports.ingest")
    monkeypatch.setattr(module, "stat", SimpleNamespace(S_ISREG=lambda mode: False))

    # ``Any``: it stands in for ``Path.open`` whatever the arguments.
    def trap(self: Path, *args: Any, **kwargs: Any) -> Any:
        """Fail the test if the mailbox is opened."""
        raise AssertionError("a file that is not regular must not be opened")

    monkeypatch.setattr(Path, "open", trap)

    result = ingest([path], "example.com")

    assert [(entry.path, entry.reason, entry.part) for entry in result.skipped] == [
        (path, Reason.UNREADABLE, "")
    ]


def test_nothing_the_attachment_name_holds_survives_uncleaned(tmp_path: Path) -> None:
    hostile = "re\u202eport\x07\x1b[31m.xml"
    path = tmp_path / "inbox.mbox"
    path.write_bytes(build_mbox(build_eml((hostile, "xml", b"<feedback><a></feedback>"))))

    (entry,) = ingest([path], "example.com").skipped

    assert entry.part.startswith("#1 ")
    assert entry.part.isprintable()
    assert len(entry.part) <= len("#1 ") + MAX_TEXT


def test_ingesting_mail_twice_gives_equal_results(
    tmp_path: Path, make_report_xml: _MakeReport, make_zip: _MakeZip
) -> None:
    (tmp_path / "b.eml").write_bytes(build_eml(("b.xml", "xml", make_report_xml(report_id="b"))))
    (tmp_path / "a.mbox").write_bytes(
        build_mbox(
            build_eml(("a.zip", "zip", make_zip({"r.xml": make_report_xml(report_id="a")}))),
            build_eml(("dup.xml", "xml", make_report_xml(report_id="a"))),
            build_eml(("bad.xml", "xml", b"not xml")),
        )
    )

    assert ingest([tmp_path], "example.com") == ingest([tmp_path], "example.com")


# ---------------------------------------------------------------------------
# A report cannot end after the clock
# ---------------------------------------------------------------------------


def test_a_report_ending_beyond_the_tolerance_is_refused_with_a_clock(
    tmp_path: Path, make_report_xml: _MakeReport
) -> None:
    """With ``now``, a report ending over a day ahead is skipped; without it nothing is checked."""
    now = datetime(2026, 10, 20, tzinfo=UTC)
    ahead = int((now + FUTURE_TOLERANCE).timestamp()) + 60
    _attachment(tmp_path, "future", make_report_xml(report_id="f", begin=ahead - 3600, end=ahead))
    _attachment(
        tmp_path, "fine", make_report_xml(report_id="ok", begin=ahead - 7200, end=ahead - 61)
    )

    checked = ingest([tmp_path], "example.com", now)

    assert [report.report_id for report in checked.reports] == ["ok"]
    assert [skip.reason for skip in checked.skipped] == [Reason.INVALID_FIELD]
    assert len(ingest([tmp_path], "example.com").reports) == 2
    assert timedelta(0) < FUTURE_TOLERANCE


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
        "MAX_DEPTH",
        "MAX_LINES",
        "MAX_MESSAGE_BYTES",
        "MAX_PARTS",
        "MAX_TEXT",
        "Attachment",
        "DkimResult",
        "IngestionResult",
        "OverrideReason",
        "PolicyPublished",
        "Reason",
        "Record",
        "Report",
        "ReportRefused",
        "SkippedFile",
        "Source",
        "SpfResult",
        "discover",
        "ingest",
        "iter_mailbox",
        "parse_report",
        "read_message",
        "read_message_file",
        "read_xml",
        "read_xml_bytes",
    }
    for name in mailvigil.reports.__all__:
        assert hasattr(mailvigil.reports, name)


def test_the_public_functions_work_together(tmp_path: Path, make_report_xml: _MakeReport) -> None:
    # The imports at the top of this file are the check that each name is reachable; this uses the
    # entry points as a caller would, without reaching into a submodule.
    path = _attachment(tmp_path, "a", make_report_xml())

    (source,), skipped = discover([tmp_path])
    found = source.path
    report = parse_report(read_xml(found), source=found.name)

    assert (found, source.explicit, skipped) == (path, False, ())
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
