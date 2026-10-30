"""
Tests of the report parser (RF-04, RF-05): ``parse_report`` and its text cleaning.

Isolation: every report is built in the test as ``bytes`` by the ``conftest.py`` factories, from
invented domains and documentation address ranges; nothing touches the disk, the network or an
environment variable. Every refusal expects ``ReportRefused`` and asserts ``.reason``, and the ones
about a bad value also assert that the detail names the field and never echoes the value.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from xml.etree import ElementTree

import pytest

from mailvigil.reports.errors import Reason, ReportRefused
from mailvigil.reports.model import (
    DkimResult,
    OverrideReason,
    PolicyPublished,
    Record,
    Report,
    SpfResult,
)
from mailvigil.reports.parser import MAX_COUNT, MAX_TEXT, _clean, _find, _find_all, parse_report

ReportBuilder = Callable[..., bytes]
RecordBuilder = Callable[..., str]

# 1790000000 and 1790086399, the default period of the factory.
_BEGIN = datetime(2026, 9, 21, 14, 13, 20, tzinfo=UTC)
_END = datetime(2026, 9, 22, 14, 13, 19, tzinfo=UTC)

# An extension namespace: its elements sit inside a report and must be ignored (RF-04).
_FOREIGN = 'xmlns:x="urn:example:extension"'

# ---------------------------------------------------------------------------
# Text cleaning (RF-05)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("a\x85b", "ab"),  # C1 control (next line)
        (
            "a\N{RIGHT-TO-LEFT OVERRIDE}b\N{LEFT-TO-RIGHT ISOLATE}c",
            "abc",
        ),  # bidirectional override and isolate
        ("a\N{ZERO WIDTH SPACE}b", "ab"),  # zero-width space (Cf)
        ("a\N{LINE SEPARATOR}b\N{PARAGRAPH SEPARATOR}c", "abc"),  # Zl and Zp
        ("a\nb\rc\td", "a b c d"),  # line breaks and tab become a space
        ("  spaced  ", "spaced"),
        ("", ""),
    ],
    ids=["c1", "bidi", "zero-width", "separators", "whitespace-controls", "strip", "empty"],
)
def test_clean_removes_or_replaces_what_can_change_a_terminal(raw: str, expected: str) -> None:
    """Characters that hide text or move the cursor never survive ``_clean``."""
    assert _clean(raw) == expected


def test_clean_cuts_a_long_field_at_the_limit() -> None:
    """A 1,000-character field is cut at ``MAX_TEXT`` (255) characters."""
    assert MAX_TEXT == 255
    assert _clean("a" * 1000) == "a" * 255


def test_clean_keeps_ordinary_international_text() -> None:
    """Letters of any script are not touched: only control and format characters go."""
    assert _clean("Müller Støre 日本語") == "Müller Støre 日本語"


def test_hostile_text_never_reaches_the_model(make_report_xml: ReportBuilder) -> None:
    """Organization, report id, domain, selector and file name are cleaned through the parser."""
    record = (
        "<record><row><source_ip>192.0.2.1</source_ip><count>1</count></row>"
        "<identifiers><header_from>Exa\N{RIGHT-TO-LEFT OVERRIDE}mple.COM</header_from>"
        "</identifiers>"
        "<auth_results><dkim><domain>a\x85.example</domain>"
        "<selector>s\N{ZERO WIDTH SPACE}1</selector><result>pass</result></dkim></auth_results>"
        "</record>"
    )
    xml = make_report_xml(
        reporter="Evil\N{RIGHT-TO-LEFT OVERRIDE} Corp\x85",
        report_id="id\n1",
        records=[record],
        domain="Ex\N{LINE SEPARATOR}.com",
    )

    report = parse_report(xml, source="x\N{RIGHT-TO-LEFT OVERRIDE}.xml\n")

    assert report.reporter == "Evil Corp"
    assert report.report_id == "id 1"
    assert report.policy.domain == "ex.com"
    assert report.records[0].header_from == "example.com"
    assert report.records[0].dkim[0].domain == "a.example"
    assert report.records[0].dkim[0].selector == "s1"
    assert report.source_file == "x.xml"


def test_overlong_field_is_cut_through_the_parser(make_report_xml: ReportBuilder) -> None:
    """The cap holds on a value read from a document, not only on ``_clean`` called alone."""
    report = parse_report(make_report_xml(reporter="o" * 1000))

    assert report.reporter == "o" * MAX_TEXT


@pytest.mark.parametrize("raw", ["a\x1bb", "a\x00b", "a&#27;b", "a&#0;b"], ids=str)
def test_esc_and_nul_are_refused_by_the_xml_parser(
    make_report_xml: ReportBuilder, raw: str
) -> None:
    """Documents the parser: C0 controls never reach ``_clean``, the document is refused."""
    with pytest.raises(ReportRefused) as caught:
        parse_report(make_report_xml(reporter=raw))

    assert caught.value.reason is Reason.MALFORMED_XML


# ---------------------------------------------------------------------------
# The report skeleton (RF-04)
# ---------------------------------------------------------------------------


def test_full_report_is_read_into_the_model(
    make_report_xml: ReportBuilder, make_record_xml: RecordBuilder
) -> None:
    """Every field of a complete RFC 7489 style report reaches the model."""
    records = [
        make_record_xml(
            ip="192.0.2.10",
            count=12,
            disposition="quarantine",
            dkim_evaluated="pass",
            spf_evaluated="fail",
            reasons=[("forwarded", "relayed by a list"), ("mailing_list", "")],
            header_from="Example.COM",
            dkim=[("example.com", "s1", "pass"), ("mailer.example.net", "k2", "fail")],
            spf=[("bounce.example.com", "softfail")],
        ),
        make_record_xml(ip="2001:db8::7", count=1),
    ]
    xml = make_report_xml(
        version="1.0",
        reporter="Example Mail",
        report_id="r-42",
        domain="Example.COM",
        p="reject",
        pct=50,
        policy_extra=(
            "<sp>quarantine</sp><np>none</np><adkim>s</adkim><aspf>r</aspf>"
            "<fo>1</fo><testing>n</testing><discovery_method>psl</discovery_method>"
        ),
        records=records,
    )

    report = parse_report(xml, source="mail.example.net!example.com!1!2.xml")

    assert report == Report(
        reporter="Example Mail",
        report_id="r-42",
        begin=_BEGIN,
        end=_END,
        policy=PolicyPublished(
            domain="example.com",
            p="reject",
            sp="quarantine",
            np="none",
            adkim="s",
            aspf="r",
            testing="n",
            discovery_method="psl",
            pct=50,
        ),
        records=(
            Record(
                source_ip="192.0.2.10",
                count=12,
                disposition="quarantine",
                dkim_evaluated="pass",
                spf_evaluated="fail",
                override_reasons=(
                    OverrideReason("forwarded", "relayed by a list"),
                    OverrideReason("mailing_list", ""),
                ),
                header_from="example.com",
                dkim=(
                    DkimResult("example.com", "s1", "pass"),
                    DkimResult("mailer.example.net", "k2", "fail"),
                ),
                spf=(SpfResult("bounce.example.com", "softfail"),),
            ),
            Record(
                source_ip="2001:db8::7",
                count=1,
                disposition="none",
                dkim_evaluated="pass",
                spf_evaluated="pass",
                header_from="example.com",
                dkim=(DkimResult("example.com", "s1", "pass"),),
                spf=(SpfResult("example.com", "pass"),),
            ),
        ),
        source_file="mail.example.net!example.com!1!2.xml",
    )
    assert report.begin.tzinfo is UTC
    assert report.end.tzinfo is UTC


def test_both_report_generations_give_equal_reports(make_report_xml: ReportBuilder) -> None:
    """The RFC 7489 form and the RFC 9990 namespace give the same model (ADR-5)."""
    old = parse_report(make_report_xml(flavor="7489"), source="a.xml")
    new = parse_report(make_report_xml(flavor="9990"), source="a.xml")

    assert old == new


def test_source_file_defaults_to_empty(make_report_xml: ReportBuilder) -> None:
    """Without a ``source`` the display name is empty."""
    assert parse_report(make_report_xml()).source_file == ""


@pytest.mark.parametrize(
    "kwargs",
    [
        {"root_tag": "html"},
        {"root_tag": "feedback", "namespace": "urn:example:other"},
        {"root_tag": "feedback", "namespace": "urn:ietf:params:xml:ns:dmarc-2.0x"},
    ],
    ids=["wrong-root", "foreign-namespace-root", "lookalike-namespace-root"],
)
def test_a_document_that_is_not_a_report_is_refused(
    make_report_xml: ReportBuilder, kwargs: dict[str, str]
) -> None:
    """A wrong root, or a ``feedback`` in a namespace the project does not know, is no report."""
    with pytest.raises(ReportRefused) as caught:
        parse_report(make_report_xml(**kwargs))

    assert caught.value.reason is Reason.NOT_A_REPORT


@pytest.mark.parametrize("version", [None, "1.0"], ids=["absent", "1.0"])
def test_supported_versions_are_accepted(
    make_report_xml: ReportBuilder, version: str | None
) -> None:
    """``version`` 1.0 and its absence are accepted."""
    assert parse_report(make_report_xml(version=version)).policy.domain == "example.com"


@pytest.mark.parametrize("version", ["2.0", "1", "", "1.0.1"], ids=str)
def test_any_other_version_is_refused(make_report_xml: ReportBuilder, version: str) -> None:
    """A version other than 1.0 is refused, not guessed at."""
    with pytest.raises(ReportRefused) as caught:
        parse_report(make_report_xml(version=version))

    assert caught.value.reason is Reason.UNSUPPORTED_VERSION


def test_missing_report_metadata_is_refused() -> None:
    """A ``feedback`` without ``report_metadata`` is not a report."""
    xml = b"<feedback><policy_published><domain>example.com</domain></policy_published></feedback>"

    with pytest.raises(ReportRefused) as caught:
        parse_report(xml)

    assert caught.value.reason is Reason.NOT_A_REPORT


def test_missing_policy_published_is_refused() -> None:
    """A ``feedback`` without ``policy_published`` is not a report."""
    xml = (
        b"<feedback><report_metadata><report_id>r</report_id><date_range><begin>1</begin>"
        b"<end>2</end></date_range></report_metadata></feedback>"
    )

    with pytest.raises(ReportRefused) as caught:
        parse_report(xml)

    assert caught.value.reason is Reason.NOT_A_REPORT


def test_malformed_xml_is_refused_with_a_position(make_report_xml: ReportBuilder) -> None:
    """The refusal of broken XML comes through ``parse_report`` with the parser position."""
    with pytest.raises(ReportRefused) as caught:
        parse_report(make_report_xml()[:-12])

    assert caught.value.reason is Reason.MALFORMED_XML
    assert "line" in caught.value.detail


def test_declaration_is_refused_through_the_parser(make_report_xml: ReportBuilder) -> None:
    """The refusal of a DOCTYPE reaches the caller of ``parse_report`` unchanged."""
    xml = make_report_xml(declaration='<!DOCTYPE feedback [<!ENTITY a "x">]>')

    with pytest.raises(ReportRefused) as caught:
        parse_report(xml)

    assert caught.value.reason is Reason.FORBIDDEN_DECLARATION


# ---------------------------------------------------------------------------
# Metadata and policy values (RF-04)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "field"),
    [
        ({"begin": "yesterday"}, "begin"),
        ({"end": "12abc"}, "end"),
        ({"begin": ""}, "begin"),
        ({"begin": "-5"}, "begin"),
        ({"begin": "1_000"}, "begin"),
        ({"begin": "9" * 40}, "begin"),
        ({"begin": 1790086400, "end": 1790000000}, "end"),
        ({"begin": 1790000000, "end": 1790000000 + 8 * 86400}, "end"),
        ({"pct": 101}, "pct"),
        ({"pct": -1}, "pct"),
        ({"pct": "fifty"}, "pct"),
        ({"pct": ""}, "pct"),
    ],
    ids=[
        "begin-text",
        "end-text",
        "begin-empty",
        "begin-negative",
        "begin-underscore",
        "begin-out-of-range",
        "end-before-begin",
        "period-over-a-week",
        "pct-101",
        "pct-negative",
        "pct-text",
        "pct-empty",
    ],
)
def test_untrustworthy_numbers_refuse_the_whole_report(
    make_report_xml: ReportBuilder, kwargs: dict[str, object], field: str
) -> None:
    """A bad timestamp, an inverted period or a ``pct`` out of range refuses the report."""
    with pytest.raises(ReportRefused) as caught:
        parse_report(make_report_xml(**kwargs))

    assert caught.value.reason is Reason.INVALID_FIELD
    assert field in caught.value.detail


def test_refusal_detail_does_not_echo_the_value(make_report_xml: ReportBuilder) -> None:
    """The detail names the field, never the value the document held."""
    with pytest.raises(ReportRefused) as caught:
        parse_report(make_report_xml(begin="12abc-secret"))

    assert "secret" not in caught.value.detail


def test_missing_period_is_refused() -> None:
    """A report with no ``date_range`` has no period the verdict could trust."""
    xml = (
        b"<feedback><report_metadata><report_id>r</report_id></report_metadata>"
        b"<policy_published><domain>example.com</domain></policy_published></feedback>"
    )

    with pytest.raises(ReportRefused) as caught:
        parse_report(xml)

    assert caught.value.reason is Reason.INVALID_FIELD


def test_policy_without_a_domain_is_refused() -> None:
    """The domain filter needs ``policy_published/domain``, so its absence is an invalid field."""
    xml = (
        b"<feedback><report_metadata><report_id>r</report_id><date_range><begin>1</begin>"
        b"<end>2</end></date_range></report_metadata>"
        b"<policy_published><p>none</p></policy_published></feedback>"
    )

    with pytest.raises(ReportRefused) as caught:
        parse_report(xml)

    assert caught.value.reason is Reason.INVALID_FIELD
    assert "domain" in caught.value.detail


def test_a_long_number_is_never_cut_into_a_valid_one(make_report_xml: ReportBuilder) -> None:
    """Numbers skip the 255-character cut: 255 zeros then 500 must not read as ``0``."""
    with pytest.raises(ReportRefused) as caught:
        parse_report(make_report_xml(pct="0" * 255 + "500"))

    assert caught.value.reason is Reason.INVALID_FIELD


def test_pct_boundaries_are_accepted(make_report_xml: ReportBuilder) -> None:
    """0 and 100 are inside the range."""
    assert parse_report(make_report_xml(pct=0)).policy.pct == 0
    assert parse_report(make_report_xml(pct=100)).policy.pct == 100


def test_absent_optionals_take_the_defaults(make_report_xml: ReportBuilder) -> None:
    """No ``pct``, ``p``, optional policy tags or organization: the documented defaults apply."""
    report = parse_report(make_report_xml(reporter=None, p=None, pct=None))

    assert report.reporter == "?"
    assert report.policy == PolicyPublished(domain="example.com")
    assert report.policy.p == "?"
    assert report.policy.pct == 100


def test_report_without_records_is_accepted(make_report_xml: ReportBuilder) -> None:
    """A report with no ``record`` has an empty tuple, not a refusal."""
    assert parse_report(make_report_xml(records=[])).records == ()


def test_whitespace_around_values_is_stripped(make_report_xml: ReportBuilder) -> None:
    """Providers pad values with spaces and line breaks; the model holds the bare value."""
    xml = make_report_xml(
        reporter="\n   Example Mail \t",
        begin=" 1790000000\n",
        end="\t1790086399 ",
        pct=" 70 ",
        domain="  Example.com\n",
    )

    report = parse_report(xml)

    assert report.reporter == "Example Mail"
    assert (report.begin, report.end) == (_BEGIN, _END)
    assert report.policy.pct == 70
    assert report.policy.domain == "example.com"


def test_unknown_elements_and_order_do_not_matter() -> None:
    """Lookups go by name: an unknown element and a different order change nothing."""
    xml = (
        b"<feedback><policy_published><surprise>1</surprise><domain>example.com</domain>"
        b"<p>none</p></policy_published><record><row><count>2</count></row></record>"
        b"<report_metadata><date_range><end>20</end><begin>10</begin></date_range>"
        b"<report_id>r</report_id></report_metadata></feedback>"
    )

    report = parse_report(xml)

    assert report.report_id == "r"
    assert report.records[0].count == 2
    assert report.end > report.begin


# ---------------------------------------------------------------------------
# Records (RF-04)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "count",
    ["-1", "1.5", "three", "", "1e3", "1_0", str(MAX_COUNT + 1), "9" * 4000, "9" * 5000],
    ids=str,
)
def test_a_bad_count_refuses_the_whole_report(
    make_report_xml: ReportBuilder, make_record_xml: RecordBuilder, count: str
) -> None:
    """Negative, non-integer, over-the-ceiling and absurdly long counts refuse the whole report."""
    xml = make_report_xml(records=[make_record_xml(), make_record_xml(count=count)])

    with pytest.raises(ReportRefused) as caught:
        parse_report(xml)

    assert caught.value.reason is Reason.INVALID_FIELD
    assert "count" in caught.value.detail


def test_a_missing_count_refuses_the_report(make_report_xml: ReportBuilder) -> None:
    """A record that does not say how many messages it stands for cannot be trusted."""
    record = "<record><row><source_ip>192.0.2.1</source_ip></row></record>"

    with pytest.raises(ReportRefused) as caught:
        parse_report(make_report_xml(records=[record]))

    assert caught.value.reason is Reason.INVALID_FIELD


def test_zero_and_large_counts_are_accepted(
    make_report_xml: ReportBuilder, make_record_xml: RecordBuilder
) -> None:
    """Zero is a count; a large one is a count too."""
    xml = make_report_xml(records=[make_record_xml(count=0), make_record_xml(count=10**9)])

    assert [record.count for record in parse_report(xml).records] == [0, 10**9]


def test_the_count_ceiling_itself_is_accepted(
    make_report_xml: ReportBuilder, make_record_xml: RecordBuilder
) -> None:
    """``MAX_COUNT`` is the last value taken; one more is refused (see the test above)."""
    xml = make_report_xml(records=[make_record_xml(count=MAX_COUNT)])

    assert parse_report(xml).records[0].count == MAX_COUNT


def test_whitespace_around_record_values_is_stripped(
    make_report_xml: ReportBuilder, make_record_xml: RecordBuilder
) -> None:
    """Padding in a count and an address does not change what they mean."""
    xml = make_report_xml(records=[make_record_xml(ip=" 192.0.2.5\n", count=" 7 ")])

    record = parse_report(xml).records[0]

    assert (record.source_ip, record.count) == ("192.0.2.5", 7)


def test_several_dkim_and_spf_blocks_are_all_kept(
    make_report_xml: ReportBuilder, make_record_xml: RecordBuilder
) -> None:
    """Every ``dkim`` and ``spf`` block is read, in document order."""
    xml = make_report_xml(
        records=[
            make_record_xml(
                dkim=[("a.example", "s1", "pass"), ("b.example", "s2", "fail")],
                spf=[("c.example", "pass"), ("d.example", "fail")],
            )
        ]
    )

    record = parse_report(xml).records[0]

    assert [(d.domain, d.selector, d.result) for d in record.dkim] == [
        ("a.example", "s1", "pass"),
        ("b.example", "s2", "fail"),
    ]
    assert [(s.domain, s.result) for s in record.spf] == [
        ("c.example", "pass"),
        ("d.example", "fail"),
    ]


def test_override_reasons_are_read(
    make_report_xml: ReportBuilder, make_record_xml: RecordBuilder
) -> None:
    """Each ``reason`` block keeps its type and comment; a missing comment is empty."""
    xml = make_report_xml(
        records=[make_record_xml(reasons=[("forwarded", "via list"), ("local_policy", "")])]
    )

    assert parse_report(xml).records[0].override_reasons == (
        OverrideReason("forwarded", "via list"),
        OverrideReason("local_policy", ""),
    )


def test_absent_record_optionals_take_the_defaults(
    make_report_xml: ReportBuilder, make_record_xml: RecordBuilder
) -> None:
    """No disposition, evaluated results, reasons, ``header_from`` or auth blocks: defaults."""
    record_xml = make_record_xml(
        disposition=None, dkim_evaluated=None, spf_evaluated=None, header_from=None, dkim=(), spf=()
    )

    record = parse_report(make_report_xml(records=[record_xml])).records[0]

    assert record == Record(source_ip="192.0.2.10", count=3)
    assert record.disposition == "none"
    assert record.override_reasons == () == record.dkim == record.spf


@pytest.mark.parametrize(
    "ip", ["2001:DB8::1", "2001:db8:0::1", "2001:0db8:0000:0000:0000:0000:0000:0001"], ids=str
)
def test_ipv6_source_is_normalized(
    make_report_xml: ReportBuilder, make_record_xml: RecordBuilder, ip: str
) -> None:
    """Spellings of the same IPv6 address end up equal, so they group together later."""
    record = parse_report(make_report_xml(records=[make_record_xml(ip=ip)])).records[0]

    assert record.source_ip == "2001:db8::1"


def test_an_invalid_source_address_is_kept_sanitized(
    make_report_xml: ReportBuilder, make_record_xml: RecordBuilder
) -> None:
    """A source the report named but ``ipaddress`` refuses is still shown, cleaned."""
    xml = make_report_xml(records=[make_record_xml(ip="not an\N{RIGHT-TO-LEFT OVERRIDE} ip\n")])

    assert parse_report(xml).records[0].source_ip == "not an ip"


def test_header_from_is_lower_cased(
    make_report_xml: ReportBuilder, make_record_xml: RecordBuilder
) -> None:
    """The ``From`` domain is lower case so later comparisons need not care."""
    xml = make_report_xml(records=[make_record_xml(header_from="Mail.EXAMPLE.com")])

    assert parse_report(xml).records[0].header_from == "mail.example.com"


def test_elements_in_a_foreign_namespace_are_ignored(
    make_report_xml: ReportBuilder, make_record_xml: RecordBuilder
) -> None:
    """Extensions inside a report, even ones named like a field, never replace the real field."""
    record_xml = make_record_xml(ip="192.0.2.20", count=4).replace(
        "<row>", f"<row><x:source_ip {_FOREIGN}>198.51.100.99</x:source_ip>"
    )
    foreign_record = f"<x:record {_FOREIGN}><row><count>999</count></row></x:record>"
    xml = make_report_xml(
        records=[record_xml],
        body_extra=foreign_record,
        policy_extra=f"<x:p {_FOREIGN}>reject</x:p>",
        metadata_extra=f"<x:org_name {_FOREIGN}>Impostor</x:org_name>",
    )

    report = parse_report(xml)

    assert len(report.records) == 1
    assert report.records[0].source_ip == "192.0.2.20"
    assert report.records[0].count == 4
    assert report.policy.p == "none"
    assert report.reporter == "Example Mail"


# ---------------------------------------------------------------------------
# Lookups (issue #70)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["row/count", "row/policy_evaluated/reason", "auth_results/dkim", "row", "missing", "row/x/y"],
)
def test_lookups_answer_like_element_tree_even_with_repeated_parents(path: str) -> None:
    """``_find`` and ``_find_all`` match ``find`` and ``findall``, repeated parents included."""
    node = ElementTree.fromstring(
        "<record><row><source_ip>a</source_ip></row>"
        "<row><count>1</count><policy_evaluated><reason/><reason/></policy_evaluated></row>"
        "<row><count>2</count></row><auth_results><dkim/><dkim/></auth_results></record>"
    )
    assert _find(node, path) is node.find(path)
    assert _find_all(node, path.split("/")) == node.findall(path)
