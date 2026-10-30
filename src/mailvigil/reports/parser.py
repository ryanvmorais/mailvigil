"""
Turns the bytes of one aggregate report into an immutable ``Report``.

The XML is parsed by ``xmlsafe.parse_xml``, so a document that declares a ``DOCTYPE`` or an
``ENTITY`` never gets here. This module reads the tree by local name with ``_find`` and
``_find_all``, so the order of elements does not matter, unknown elements and extensions in a
foreign namespace are ignored, and a report in the RFC 7489 form and one in the RFC 9990 namespace
give the same model (ADR-5).

Only what the verdict cannot do without is strict: the period, ``pct`` and every ``count`` refuse
the whole report when they cannot be trusted. Every other optional element takes the default of the
model. Every text that reaches the model went through ``_clean``, so any caller may print it
(RF-05, ADR-6).
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from xml.etree.ElementTree import Element

from mailvigil.reports.errors import Reason, ReportRefused
from mailvigil.reports.model import (
    DkimResult,
    OverrideReason,
    PolicyPublished,
    Record,
    Report,
    SpfResult,
)
from mailvigil.reports.xmlsafe import parse_xml
from mailvigil.text import MAX_TEXT, clean_text

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# A whole number written with ASCII digits only. ``int`` alone also takes ``1_000``, ``-5``, ``+5``
# and digits of other scripts, none of which a report has any reason to hold.
_DIGITS = re.compile(r"[0-9]+")

# The most messages one record may claim: a trillion, which no real report reaches. Without a
# ceiling, a count of thousands of digits is a valid ``int`` that the output cannot turn back into
# text (CPython stops at 4,300 digits), so the run would end in a traceback. With it, the sum of
# every record of every file stays far below that limit.
MAX_COUNT = 10**12

# The longest period one report may cover. Aggregate reports cover a day; a week leaves room for
# reporters that batch. Without a ceiling, one report with a long window would satisfy the rules
# about the period and its coverage by itself.
MAX_PERIOD = timedelta(days=7)

# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


def _find_all(node: Element, names: Sequence[str]) -> list[Element]:
    """
    List the elements at the end of a path of local names, in document order.

    The same answer as ``Element.findall`` for a path of plain names, without the path engine of
    ``ElementTree``: it compiles and walks a selector chain for every call, which was the largest
    cost of reading a record after the XML parser itself (issue #70). A name matches the children
    one level down, so ``("row", "count")`` finds a ``count`` under any ``row``, not only the first.

    Args:
        node (Element): The element to search from.
        names (Sequence[str]): The local names of each level, such as ``("row", "count")``.

    Returns:
        list[Element]: Every element the path reaches; empty when none does.
    """
    level = [node]
    for name in names:
        level = [child for parent in level for child in parent.findall(name)]
        if not level:
            break
    return level


def _find(node: Element, path: str) -> Element | None:
    """
    Find the first element at the end of a path of local names.

    Args:
        node (Element): The element to search from.
        path (str): A path of local names, such as ``row/count``.

    Returns:
        Element | None: The first element in document order, or ``None`` when there is none.
    """
    names = path.split("/")
    if len(names) == 1:
        return node.find(path)
    found = _find_all(node, names)
    return found[0] if found else None


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------


def _clean(value: str) -> str:
    """
    Make a text from a report safe to print: inert and short.

    The rules live in ``mailvigil.text.clean_text``, shared with the configuration layer (ADR-4 of
    003): the report text is cut to ``MAX_TEXT``.

    Args:
        value (str): The text as the XML parser produced it.

    Returns:
        str: The cleaned text, possibly empty.
    """
    return clean_text(value, MAX_TEXT)


def _raw_text(node: Element, path: str) -> str | None:
    """
    Read the stripped text of a sub-element, uncut and uncleaned.

    Only numbers use this: they must match ``_DIGITS`` whole, so nothing in them needs cleaning,
    and cutting them at ``MAX_TEXT`` would turn a long number into a different, valid one.

    Args:
        node (Element): The element to search from.
        path (str): A path of local names, such as ``row/count``.

    Returns:
        str | None: The stripped text (empty when the element holds none), or ``None`` when the
            element is absent.
    """
    found = _find(node, path)
    return None if found is None else (found.text or "").strip()


def _find_text(node: Element, path: str) -> str | None:
    """
    Read the cleaned text of a sub-element, telling "absent" from "empty".

    Args:
        node (Element): The element to search from.
        path (str): A path of local names, such as ``policy_evaluated/dkim``.

    Returns:
        str | None: The cleaned text (empty when the element holds none), or ``None`` when the
            element is absent.
    """
    raw = _raw_text(node, path)
    return None if raw is None else _clean(raw)


def _text(node: Element, path: str, default: str = "", *, lower: bool = False) -> str:
    """
    Read the cleaned text of a sub-element, with a default for absent and empty.

    Args:
        node (Element): The element to search from.
        path (str): A path of local names, such as ``policy_evaluated/dkim``.
        default (str, optional): Returned when the element is absent or holds no text.
        lower (bool, optional): Lower-case the result, for domains. The default is not changed.

    Returns:
        str: The cleaned text, or the default.
    """
    value = _find_text(node, path)
    if not value:
        return default
    return value.lower() if lower else value


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------


def _integer(value: str | None, field: str, maximum: int | None = None) -> int:
    """
    Read a whole number a report must get right.

    Args:
        value (str | None): The raw text, or ``None`` when the element is absent.
        field (str): The path of the field, named in the refusal.
        maximum (int | None, optional): The largest value accepted. Default: no ceiling.

    Returns:
        int: The number, zero or more.

    Raises:
        ReportRefused: ``INVALID_FIELD`` when the value is absent, empty or not ASCII digits, is
            so long that ``int`` refuses it, or is above ``maximum``. The detail names the field,
            never the value.
    """
    if value is None or _DIGITS.fullmatch(value) is None:
        raise ReportRefused(Reason.INVALID_FIELD, f"invalid value in {field}")
    try:
        number = int(value)
    except ValueError:  # more digits than the interpreter converts
        raise ReportRefused(Reason.INVALID_FIELD, f"invalid value in {field}") from None
    if maximum is not None and number > maximum:
        raise ReportRefused(Reason.INVALID_FIELD, f"invalid value in {field}")
    return number


def _timestamp(value: str | None, field: str) -> datetime:
    """
    Read a Unix timestamp as an aware UTC datetime.

    Args:
        value (str | None): The raw text, or ``None`` when the element is absent.
        field (str): The path of the field, named in the refusal.

    Returns:
        datetime: The moment, timezone-aware, UTC.

    Raises:
        ReportRefused: ``INVALID_FIELD`` when the value is not a whole number or is outside what
            the platform can represent as a date.
    """
    seconds = _integer(value, field)
    try:
        return datetime.fromtimestamp(seconds, UTC)
    except (ValueError, OverflowError, OSError):
        raise ReportRefused(Reason.INVALID_FIELD, f"invalid value in {field}") from None


# ---------------------------------------------------------------------------
# Parts of the report
# ---------------------------------------------------------------------------


def _parse_policy(node: Element) -> PolicyPublished:
    """
    Read ``policy_published``.

    Args:
        node (Element): The ``policy_published`` element.

    Returns:
        PolicyPublished: The policy, with the defaults of the model for what is absent.

    Raises:
        ReportRefused: ``INVALID_FIELD`` for a missing domain or a ``pct`` outside 0 to 100.
    """
    domain = _text(node, "domain", lower=True)
    if not domain:
        raise ReportRefused(Reason.INVALID_FIELD, "missing value in policy_published/domain")

    pct_text = _raw_text(node, "pct")
    pct = 100 if pct_text is None else _integer(pct_text, "policy_published/pct")
    if pct > 100:
        raise ReportRefused(Reason.INVALID_FIELD, "invalid value in policy_published/pct")

    return PolicyPublished(
        domain=domain,
        p=_text(node, "p", "?"),
        sp=_text(node, "sp"),
        np=_text(node, "np"),
        adkim=_text(node, "adkim"),
        aspf=_text(node, "aspf"),
        testing=_text(node, "testing"),
        discovery_method=_text(node, "discovery_method"),
        pct=pct,
    )


def _source_ip(node: Element) -> str:
    """
    Read ``row/source_ip``, normalized when it is an address.

    Args:
        node (Element): The ``record`` element.

    Returns:
        str: ``str(address)`` when ``ipaddress`` accepts the text, so two spellings of one IPv6
            address are equal; otherwise the cleaned text, because a source the report named but
            that cannot be reasoned about is still worth showing.
    """
    text = _text(node, "row/source_ip")
    try:
        return str(ipaddress.ip_address(text))
    except ValueError:
        return text


def _parse_record(node: Element) -> Record:
    """
    Read one ``record``.

    Args:
        node (Element): The ``record`` element.

    Returns:
        Record: The row, every DKIM and SPF block, and the override reasons, in document order.

    Raises:
        ReportRefused: ``INVALID_FIELD`` when ``row/count`` is absent, not a whole number or above
            ``MAX_COUNT``.
    """
    evaluated = "row/policy_evaluated"
    return Record(
        source_ip=_source_ip(node),
        count=_integer(_raw_text(node, "row/count"), "row/count", MAX_COUNT),
        disposition=_text(node, f"{evaluated}/disposition", "none"),
        dkim_evaluated=_text(node, f"{evaluated}/dkim"),
        spf_evaluated=_text(node, f"{evaluated}/spf"),
        override_reasons=tuple(
            OverrideReason(type=_text(reason, "type"), comment=_text(reason, "comment"))
            for reason in _find_all(node, ("row", "policy_evaluated", "reason"))
        ),
        header_from=_text(node, "identifiers/header_from", lower=True),
        dkim=tuple(
            DkimResult(
                domain=_text(block, "domain", lower=True),
                selector=_text(block, "selector"),
                result=_text(block, "result"),
            )
            for block in _find_all(node, ("auth_results", "dkim"))
        ),
        spf=tuple(
            SpfResult(domain=_text(block, "domain", lower=True), result=_text(block, "result"))
            for block in _find_all(node, ("auth_results", "spf"))
        ),
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def parse_report(xml: bytes, *, source: str = "") -> Report:
    """
    Turn the XML of an aggregate report into a ``Report``.

    Args:
        xml (bytes): The document, in any encoding XML allows.
        source (str, optional): The file name the XML came from, kept for display. It is cleaned
            like any other text.

    Returns:
        Report: The immutable report.

    Raises:
        ReportRefused: ``FORBIDDEN_DECLARATION`` or ``MALFORMED_XML`` from the XML parser;
            ``NOT_A_REPORT`` for a wrong root or a missing ``report_metadata`` or
            ``policy_published``; ``UNSUPPORTED_VERSION`` for a ``version`` other than ``1.0``;
            ``INVALID_FIELD`` for a period (backwards or longer than ``MAX_PERIOD``), a ``pct`` or a
            ``count`` that cannot be trusted.
    """
    root = parse_xml(xml)
    if root.tag != "feedback":
        raise ReportRefused(Reason.NOT_A_REPORT, "the root element is not feedback")

    version = _find_text(root, "version")
    if version is not None and version != "1.0":
        raise ReportRefused(Reason.UNSUPPORTED_VERSION, "version is not 1.0")

    metadata = root.find("report_metadata")
    policy = root.find("policy_published")
    if metadata is None or policy is None:
        raise ReportRefused(Reason.NOT_A_REPORT, "report_metadata or policy_published is missing")

    begin = _timestamp(_raw_text(metadata, "date_range/begin"), "date_range/begin")
    end = _timestamp(_raw_text(metadata, "date_range/end"), "date_range/end")
    if end < begin or end - begin > MAX_PERIOD:
        raise ReportRefused(Reason.INVALID_FIELD, "invalid value in date_range/end")

    return Report(
        reporter=_text(metadata, "org_name", "?"),
        report_id=_text(metadata, "report_id"),
        begin=begin,
        end=end,
        policy=_parse_policy(policy),
        records=tuple(_parse_record(record) for record in root.findall("record")),
        source_file=_clean(source),
    )
