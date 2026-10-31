"""
Property-based tests of the hostile-input surface (issue #67).

The hand-written hostile tests feed the attacks someone thought of. These feed the ones nobody did,
and assert the invariants the product promises instead of one answer: whatever bytes a report, a
message or a configuration file holds, the reading raises nothing but its own typed refusal, and a
report that does get through reaches every output without raising, with an ASCII text of at most 80
columns, a JSON document that parses and a page with no element that could run or load something.

Isolation: pure functions over generated values, plus one temporary folder per example for the
tests that need a file. Every input is built from nothing or from the synthetic builders of
``conftest.py`` and ``mail_helpers.py``; no real report is read (RNF-07). Hypothesis is a dev
dependency only, so the wheel stays free of dependencies. The number of examples comes from the
profile loaded in ``conftest.py``: a small, derandomized one for the suite and ``thorough`` for a
long hunt (``HYPOTHESIS_PROFILE=thorough uv run pytest tests/test_properties.py``).
"""

from __future__ import annotations

import io
import json
import tempfile
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import cast
from xml.sax.saxutils import escape

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st
from tests.html_helpers import Page
from tests.mail_helpers import build_eml

from mailvigil.config import Config, ConfigError, load_config
from mailvigil.messages import ENGLISH, PORTUGUESE
from mailvigil.render import render_summary
from mailvigil.render_html import render_html
from mailvigil.render_json import dumps, summary_document, verdict_document
from mailvigil.render_verdict import render_verdict
from mailvigil.reports import (
    IngestionResult,
    Reason,
    Report,
    ReportRefused,
    ingest,
    ingest_many,
)
from mailvigil.reports.mail import iter_mailbox, read_message
from mailvigil.reports.parser import parse_report
from mailvigil.reports.reader import Kind, read_xml_bytes
from mailvigil.summary import summarize
from mailvigil.text import DROPPED_CATEGORIES, clean_text, has_dropped_characters
from mailvigil.verdict import judge

# The fixtures here only return a pure builder, so Hypothesis may reuse one across examples.
PURE_FIXTURES = settings(suppress_health_check=[HealthCheck.function_scoped_fixture])

# The characters TOML cares about, plus a bidi override and a NUL: the draw reaches the rules of
# the loader (a table, a key, a quote, a comment) more often than a plain text would.
_TOML_ALPHABET = "abs1 .\"'=[]#\\\n\u202e\x00"

# The elements that could run or load something: none may ever appear, whatever a report says.
_BANNED = {"script", "iframe", "object", "embed", "form", "link", "base"}

# The widest line a text of the tool may have (004, RF-09).
_LINE_LIMIT = 80

# Two known services, so the draws hit the recognized and the unrecognized paths of the summary.
_SENDERS: Mapping[str, str] = MappingProxyType({"s1": "Example Mail", "selector1": "Service Two"})

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# The first bytes of the formats the readers sniff, so a draw often gets past the first check.
_MAGIC = st.sampled_from(
    (b"", b"\x1f\x8b\x08\x00", b"PK\x03\x04", b"PK\x05\x06", b"<?xml", b"<feedback>", b"From ")
)

#: Bytes that are sometimes the start of a real format and then nonsense.
raw_bytes = st.builds(lambda head, tail: head + tail, _MAGIC, st.binary(max_size=600))

#: One change to a valid document: what to do, where (taken modulo the length) and with which byte.
edits = st.lists(
    st.tuples(
        st.sampled_from(("set", "delete", "insert", "repeat", "truncate")),
        st.integers(min_value=0, max_value=10**6),
        st.integers(min_value=0, max_value=255),
    ),
    min_size=1,
    max_size=8,
)

# Text an XML parser accepts, so the draw reaches the layers after the parser more often.
_XML_SAFE = st.text(
    st.characters(blacklist_categories=["Cs", "Cc"], blacklist_characters="\ufffe\uffff"),
    max_size=40,
)


#: A text field of a report that parses. The parser's own refusals (a control character, a number
#: that is not one) are the job of the tests above; a document with one such field never reaches the
#: code after the parser, which is what these examples are for.
field_text = _XML_SAFE.map(escape)

# What a DKIM or SPF block holds: a real result most of the time, any parseable text otherwise.
_RESULTS = st.one_of(st.sampled_from(("pass", "fail", "none", "neutral")), field_text)


def mutate(base: bytes, changes: Sequence[tuple[str, int, int]]) -> bytes:
    """
    Apply a list of small changes to a document.

    Args:
        base (bytes): The valid document.
        changes (Sequence[tuple[str, int, int]]): ``(action, place, byte)``: ``place`` is taken
            modulo the current length, so any draw is a valid position.

    Returns:
        bytes: The changed document, possibly empty.
    """
    data = bytearray(base)
    for action, place, byte in changes:
        if not data:
            break
        at = place % len(data)
        if action == "set":
            data[at] = byte
        elif action == "delete":
            del data[at]
        elif action == "insert":
            data.insert(at, byte)
        elif action == "repeat":
            # Grows the document, which is what finds a limit nobody lowered.
            data[at:at] = data[at : at + byte % 64 + 1] * 8
        else:
            del data[at:]
    return bytes(data)


@st.composite
def record_fields(draw: st.DrawFn) -> dict[str, object]:
    """
    Draw the arguments of one ``<record>``, valid or not.

    Args:
        draw (st.DrawFn): Hypothesis' draw function.

    Returns:
        dict[str, object]: The keyword arguments of the ``make_record_xml`` fixture.
    """
    maybe = st.none() | _RESULTS
    return {
        "ip": draw(st.ip_addresses().map(str)),
        "count": draw(st.integers(min_value=0, max_value=2 * 10**12).map(str)),
        "disposition": draw(st.none() | st.sampled_from(("none", "quarantine", "reject"))),
        "dkim_evaluated": draw(maybe),
        "spf_evaluated": draw(maybe),
        "reasons": draw(st.lists(st.tuples(field_text, field_text), max_size=2)),
        "header_from": draw(st.none() | st.sampled_from(("example.com",)) | field_text),
        "dkim": draw(
            st.lists(
                st.tuples(
                    st.sampled_from(("example.com", "mail.example.net")) | field_text,
                    st.sampled_from(("s1", "selector1", "other")) | field_text,
                    _RESULTS,
                ),
                max_size=3,
            )
        ),
        "spf": draw(
            st.lists(
                st.tuples(st.sampled_from(("example.com",)) | field_text, _RESULTS), max_size=3
            )
        ),
    }


@st.composite
def report_fields(draw: st.DrawFn) -> dict[str, object]:
    """
    Draw the arguments of one report: the header fields, valid or not, and its records.

    Args:
        draw (st.DrawFn): Hypothesis' draw function.

    Returns:
        dict[str, object]: The keyword arguments of the ``make_report_xml`` fixture, with the
            records as the dictionaries ``record_fields`` draws.
    """
    first = draw(st.integers(min_value=0, max_value=4_000_000_000))
    return {
        "reporter": draw(st.none() | field_text),
        "report_id": draw(field_text),
        "begin": first,
        "end": draw(st.integers(first, first + 86_400 * 7)),
        "p": draw(st.none() | st.sampled_from(("none", "quarantine", "reject")) | field_text),
        "pct": draw(st.none() | st.integers(min_value=0, max_value=100)),
        "records": draw(st.lists(record_fields(), max_size=6)),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def settled[T](call: Callable[[], T]) -> T | ReportRefused:
    """
    Run a reading and return its refusal instead of raising it.

    Any other exception escapes, which is the failure the property is looking for.

    Args:
        call (Callable[[], T]): The reading.

    Returns:
        T | ReportRefused: What the reading returned, or the typed refusal it raised.
    """
    try:
        return call()
    except ReportRefused as refused:
        return refused


def assert_typed(result: object) -> None:
    """
    Check that a refusal carries a ``Reason`` and a text that is safe to print.

    Args:
        result (object): What ``settled`` returned; anything that is not a refusal passes.
    """
    if isinstance(result, ReportRefused):
        assert isinstance(result.reason, Reason)
        assert isinstance(result.detail, str)


def build_records(
    make_record_xml: Callable[..., str], fields: Sequence[Mapping[str, object]]
) -> list[str]:
    """
    Turn drawn record arguments into record XML.

    Args:
        make_record_xml (Callable[..., str]): The conftest fixture.
        fields (Sequence[Mapping[str, object]]): What ``record_fields`` drew.

    Returns:
        list[str]: One ``<record>`` per entry.
    """
    return [make_record_xml(**record) for record in fields]


def build_report(
    make_report_xml: Callable[..., bytes],
    make_record_xml: Callable[..., str],
    fields: Mapping[str, object],
) -> bytes:
    """
    Turn drawn report arguments into a report for ``example.com``.

    Args:
        make_report_xml (Callable[..., bytes]): The conftest fixture.
        make_record_xml (Callable[..., str]): The conftest fixture.
        fields (Mapping[str, object]): What ``report_fields`` drew.

    Returns:
        bytes: The XML document.
    """
    arguments = dict(fields)
    records = cast("Sequence[Mapping[str, object]]", arguments.pop("records"))
    return make_report_xml(records=build_records(make_record_xml, records), **arguments)


def check_text(text: str) -> None:
    """
    Check the promise of every text the tool prints: inert, and no line wider than the terminal.

    The layout is ASCII by design (004, RF-09), but a reporter's name or a policy value may be any
    letter, so the property is that nothing in the text could move the cursor or hide a character.

    Args:
        text (str): The text of a command.
    """
    assert not has_dropped_characters("".join(text.splitlines()))
    assert all(len(line) <= _LINE_LIMIT for line in text.splitlines())


def check_page(page: str) -> None:
    """
    Check the promise of the HTML page: ASCII, and no element that could run or load something.

    Args:
        page (str): The document.
    """
    assert page.isascii()
    found = {tag for tag, _ in Page(page).elements}
    assert not found & _BANNED


# ---------------------------------------------------------------------------
# The readers refuse, they do not raise
# ---------------------------------------------------------------------------


@given(raw_bytes)
def test_the_xml_parser_only_ever_refuses(data: bytes) -> None:
    """Arbitrary bytes give a report or a typed refusal, never another exception."""
    assert_typed(settled(lambda: parse_report(data)))


@PURE_FIXTURES
@given(report=report_fields(), changes=edits)
def test_a_damaged_report_only_ever_refuses(
    make_report_xml: Callable[..., bytes],
    make_record_xml: Callable[..., str],
    report: dict[str, object],
    changes: list[tuple[str, int, int]],
) -> None:
    """A valid report with bytes changed, repeated or cut off ends in a report or a refusal."""
    document = mutate(build_report(make_report_xml, make_record_xml, report), changes)
    assert_typed(settled(lambda: parse_report(document)))


@given(raw_bytes, st.sampled_from(("xml", "gz", "zip")))
def test_the_archive_reader_only_ever_refuses(data: bytes, kind: Kind) -> None:
    """Arbitrary bytes, taken as any of the three forms, come out as a document or a refusal."""
    result = settled(lambda: read_xml_bytes(data, kind))
    assert_typed(result)


@PURE_FIXTURES
@given(changes=edits, kind=st.sampled_from(("gz", "zip")))
def test_a_damaged_archive_only_ever_refuses(
    make_report_xml: Callable[..., bytes],
    make_gzip: Callable[[bytes], bytes],
    make_zip: Callable[[Mapping[str, bytes]], bytes],
    changes: list[tuple[str, int, int]],
    kind: Kind,
) -> None:
    """A real gzip or zip with bytes changed ends in a document or a refusal, under the cap."""
    xml = make_report_xml()
    archive = make_gzip(xml) if kind == "gz" else make_zip({"report.xml": xml})
    result = settled(lambda: read_xml_bytes(mutate(archive, changes), kind))
    assert_typed(result)
    if isinstance(result, bytes):
        assert len(result) <= 5 * 1024 * 1024


@given(raw_bytes)
def test_the_message_reader_only_ever_refuses(raw: bytes) -> None:
    """Arbitrary bytes taken as a mail message give attachments or a typed refusal."""
    assert_typed(settled(lambda: read_message(raw)))


@PURE_FIXTURES
@given(changes=edits)
def test_a_damaged_message_only_ever_refuses(
    make_report_xml: Callable[..., bytes],
    make_gzip: Callable[[bytes], bytes],
    changes: list[tuple[str, int, int]],
) -> None:
    """A real report mail with bytes changed still gives attachments or a typed refusal."""
    message = build_eml(("report.xml.gz", "gzip", make_gzip(make_report_xml())))
    assert_typed(settled(lambda: read_message(mutate(message, changes))))


@given(raw_bytes)
def test_the_mailbox_splitter_numbers_every_message_and_never_raises(data: bytes) -> None:
    """Whatever the bytes, the splitter yields numbered messages, each bytes or a refusal."""
    numbers = []
    for number, item in iter_mailbox(io.BytesIO(data)):
        numbers.append(number)
        assert isinstance(item, bytes | ReportRefused)
    assert numbers == list(range(1, len(numbers) + 1))


@settings(max_examples=20)
@given(contents=st.lists(raw_bytes, min_size=5, max_size=5))
def test_ingestion_keeps_going_whatever_the_files_hold(contents: list[bytes]) -> None:
    """Five files of nonsense, one per format, are five refusals or reports and never a crash."""
    with tempfile.TemporaryDirectory() as folder:
        paths = []
        for name, data in zip(("a.xml", "b.gz", "c.zip", "d.eml", "e.mbox"), contents, strict=True):
            path = Path(folder) / name
            path.write_bytes(data)
            paths.append(path)
        result = ingest(paths, "example.com")
    assert isinstance(result, IngestionResult)
    assert all(isinstance(skipped.reason, Reason) for skipped in result.skipped)


@settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    drawn=st.lists(
        st.tuples(
            st.sampled_from(("example.com", "example.net", "example.org", "example.invalid")),
            st.sampled_from(("r1", "r2", "r3")),
        ),
        max_size=8,
    )
)
def test_many_domains_never_share_a_report_and_each_matches_a_run_of_its_own(
    make_report_xml: Callable[..., bytes], drawn: list[tuple[str, str]]
) -> None:
    """A report is kept by one domain at most, and a domain's result is what it gets alone."""
    wanted = ["example.com", "example.net", "example.org"]
    with tempfile.TemporaryDirectory() as folder:
        for index, (domain, report_id) in enumerate(drawn):
            document = make_report_xml(domain=domain, report_id=report_id)
            name = f"f{index}!example.com!1790000000!1790086399.xml"
            (Path(folder) / name).write_bytes(document)
        together = ingest_many([Path(folder)], wanted)
        alone = {domain: ingest([Path(folder)], domain) for domain in wanted}

    kept = [report.source_file for result in together.values() for report in result.reports]
    assert len(kept) == len(set(kept))
    for domain in wanted:
        assert together[domain].reports == alone[domain].reports
        assert together[domain].duplicates == alone[domain].duplicates
        assert together[domain].skipped == alone[domain].skipped


# ---------------------------------------------------------------------------
# A report that gets through reaches every output
# ---------------------------------------------------------------------------


@PURE_FIXTURES
@given(reports=st.lists(report_fields(), min_size=1, max_size=3))
def test_every_report_the_parser_builds_reaches_every_output(
    make_report_xml: Callable[..., bytes],
    make_record_xml: Callable[..., str],
    reports: list[dict[str, object]],
) -> None:
    """Whatever the parser lets through, the summary, the verdict and the four outputs hold up."""
    parsed: list[Report] = []
    for fields in reports:
        document = build_report(make_report_xml, make_record_xml, fields)
        outcome = settled(lambda document=document: parse_report(document))
        if isinstance(outcome, Report):
            parsed.append(outcome)
    assume(parsed)

    summary = summarize(IngestionResult(tuple(parsed)), Config("example.com", _SENDERS))
    verdict = judge(summary)

    for messages in (ENGLISH, PORTUGUESE):
        check_text(render_summary(summary, None, messages))
        check_text(render_verdict(verdict, messages))
        check_page(render_html(summary, verdict, messages))
    for document in (summary_document(summary, None), verdict_document(verdict)):
        written = dumps(document)
        assert written.isascii()
        assert isinstance(json.loads(written), dict)


# ---------------------------------------------------------------------------
# Text and configuration
# ---------------------------------------------------------------------------


def _reference_clean(value: str, limit: int) -> str:
    """
    Clean a text the slow and obvious way, to compare with ``clean_text``'s fast path.

    Args:
        value (str): The text.
        limit (int): The longest result.

    Returns:
        str: The text with line breaks as spaces, the dropped categories removed, stripped and cut.
    """
    spaced = value.replace("\t", " ").replace("\r", " ").replace("\n", " ")
    kept = "".join(c for c in spaced if unicodedata.category(c) not in DROPPED_CATEGORIES)
    return kept.strip()[:limit]


@given(st.text(max_size=300), st.integers(min_value=0, max_value=300))
def test_clean_text_leaves_nothing_a_terminal_could_obey(value: str, limit: int) -> None:
    """No control, format or separator character survives, and the result is within the limit."""
    cleaned = clean_text(value, limit)
    assert not has_dropped_characters(cleaned)
    assert len(cleaned) <= limit
    assert cleaned == _reference_clean(value, limit)


@given(st.binary(max_size=400))
def test_the_configuration_loader_only_ever_refuses(data: bytes) -> None:
    """Arbitrary bytes in a configuration file give a configuration or a typed ``ConfigError``."""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "mailvigil.toml"
        path.write_bytes(data)
        try:
            config = load_config(path)
        except ConfigError:
            return
    assert config.domain == config.domain.lower()


@given(st.text(alphabet=_TOML_ALPHABET, max_size=120))
def test_the_configuration_loader_handles_text_that_looks_like_toml(body: str) -> None:
    """Text drawn from a TOML-ish alphabet reaches the validation rules, not only the parser."""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "mailvigil.toml"
        path.write_text(f'domain = "example.com"\n[senders]\n{body}\n', encoding="utf-8")
        try:
            config = load_config(path)
        except ConfigError:
            return
    assert all(not has_dropped_characters(name) for name in config.senders.values())
