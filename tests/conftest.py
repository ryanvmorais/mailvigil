"""
Shared fixtures: factories that build synthetic reports, zips and gzips.

Nothing here is a real report and no file is committed (RNF-07): every document is built in memory
from invented domains and the documentation address ranges (``192.0.2.0/24``, ``198.51.100.0/24``,
``203.0.113.0/24``, ``2001:db8::/32``). The factories are exposed as fixtures that return the
builder, so a test asks for ``make_report_xml`` as an argument instead of importing from here.
"""

from __future__ import annotations

import gzip
import io
import os
import zipfile
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime

import pytest
from hypothesis import settings

# The property tests (``test_properties.py``) draw their examples from the profile named here. The
# default is small and derandomized, so the suite stays fast and a red run can be reproduced; the
# ``thorough`` profile is for a long hunt (set HYPOTHESIS_PROFILE=thorough, then run the file).
settings.register_profile("default", max_examples=60, derandomize=True, deadline=None)
settings.register_profile("thorough", max_examples=3000, deadline=None)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "default"))

# The RFC 9990 namespace; an RFC 7489 report has no namespace at all.
_NAMESPACE_9990 = "urn:ietf:params:xml:ns:dmarc-2.0"

# The moment every CLI run believes it is: the day after the 28-day windows of ``cli_helpers.py``
# end, so no test depends on the real date (a future report, or a stale note, would).
CLOCK = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the clock the CLI reads, so the date of the run never changes a result."""
    monkeypatch.setattr("mailvigil.cli._now", lambda: CLOCK)


@pytest.fixture(autouse=True)
def windows_pipe(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Pin the platform the Portuguese catalog is chosen for: a test runs as on Windows, with
    ``capsys`` for a pipe, so it gets the ASCII text on every machine (spec 006 ADR-9). A test of
    the accents sets the platform itself.
    """
    monkeypatch.setattr("mailvigil.messages.fold._on_windows", lambda: True)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _optional(tag: str, value: str | None) -> str:
    """
    Render an element, or nothing when the value is ``None``.

    Args:
        tag (str): The element name.
        value (str | None): The text content; ``None`` omits the element.

    Returns:
        str: ``<tag>value</tag>``, or an empty string.
    """
    return "" if value is None else f"<{tag}>{value}</{tag}>"


def _build_record_xml(
    *,
    ip: str = "192.0.2.10",
    count: str | int = 3,
    disposition: str | None = "none",
    dkim_evaluated: str | None = "pass",
    spf_evaluated: str | None = "pass",
    reasons: Sequence[tuple[str, str]] = (),
    header_from: str | None = "example.com",
    dkim: Sequence[tuple[str, str, str]] = (("example.com", "s1", "pass"),),
    spf: Sequence[tuple[str, str]] = (("example.com", "pass"),),
) -> str:
    """
    Build one ``<record>`` element.

    Args:
        ip (str, optional): The ``row/source_ip`` text. Default: a documentation address.
        count (str | int, optional): The ``row/count`` text, a string to allow invalid values.
        disposition (str | None, optional): The disposition; ``None`` omits it.
        dkim_evaluated (str | None, optional): ``policy_evaluated/dkim``; ``None`` omits it.
        spf_evaluated (str | None, optional): ``policy_evaluated/spf``; ``None`` omits it.
        reasons (Sequence[tuple[str, str]], optional): ``(type, comment)`` override reasons.
        header_from (str | None, optional): ``identifiers/header_from``; ``None`` omits it.
        dkim (Sequence[tuple[str, str, str]], optional): ``(domain, selector, result)`` blocks.
        spf (Sequence[tuple[str, str]], optional): ``(domain, result)`` blocks.

    Returns:
        str: The XML of the record.
    """
    reason_xml = "".join(
        f"<reason>{_optional('type', kind)}{_optional('comment', comment)}</reason>"
        for kind, comment in reasons
    )
    dkim_xml = "".join(
        f"<dkim><domain>{domain}</domain><selector>{selector}</selector>"
        f"<result>{result}</result></dkim>"
        for domain, selector, result in dkim
    )
    spf_xml = "".join(
        f"<spf><domain>{domain}</domain><result>{result}</result></spf>" for domain, result in spf
    )
    return (
        "<record>"
        f"<row><source_ip>{ip}</source_ip><count>{count}</count>"
        "<policy_evaluated>"
        f"{_optional('disposition', disposition)}"
        f"{_optional('dkim', dkim_evaluated)}{_optional('spf', spf_evaluated)}{reason_xml}"
        "</policy_evaluated></row>"
        f"<identifiers>{_optional('header_from', header_from)}</identifiers>"
        f"<auth_results>{dkim_xml}{spf_xml}</auth_results>"
        "</record>"
    )


def _build_report_xml(
    *,
    flavor: str = "7489",
    domain: str = "example.com",
    reporter: str | None = "Example Mail",
    report_id: str = "r1",
    begin: str | int = 1790000000,
    end: str | int = 1790086399,
    version: str | None = None,
    p: str | None = "none",
    pct: str | int | None = None,
    policy_extra: str = "",
    records: Sequence[str] | None = None,
    root_tag: str = "feedback",
    namespace: str | None = None,
    metadata_extra: str = "",
    body_extra: str = "",
    declaration: str = "",
) -> bytes:
    """
    Build a synthetic aggregate report, after the RFC 9990 Appendix B sample.

    Args:
        flavor (str, optional): ``"7489"`` (no namespace) or ``"9990"`` (the dmarc-2.0 namespace).
        domain (str, optional): The ``policy_published/domain`` text.
        reporter (str | None, optional): ``report_metadata/org_name``; ``None`` omits it.
        report_id (str, optional): ``report_metadata/report_id``.
        begin (str | int, optional): ``date_range/begin``, a string to allow invalid values.
        end (str | int, optional): ``date_range/end``.
        version (str | None, optional): The ``version`` element; ``None`` omits it.
        p (str | None, optional): ``policy_published/p``; ``None`` omits it.
        pct (str | int | None, optional): ``policy_published/pct``; ``None`` omits it.
        policy_extra (str, optional): Raw XML appended inside ``policy_published``.
        records (Sequence[str] | None, optional): Record XML strings; ``None`` gives one default
            record, an empty sequence gives none.
        root_tag (str, optional): The root element name, to build a non-report.
        namespace (str | None, optional): Overrides the namespace implied by ``flavor``.
        metadata_extra (str, optional): Raw XML appended inside ``report_metadata``.
        body_extra (str, optional): Raw XML appended inside the root.
        declaration (str, optional): Text placed before the root, e.g. an XML declaration.

    Returns:
        bytes: The document, UTF-8 encoded.
    """
    uri = namespace if namespace is not None else (_NAMESPACE_9990 if flavor == "9990" else None)
    xmlns = f' xmlns="{uri}"' if uri else ""
    record_list = [_build_record_xml()] if records is None else list(records)
    text = (
        f"{declaration}<{root_tag}{xmlns}>"
        f"{_optional('version', version)}"
        "<report_metadata>"
        f"{_optional('org_name', reporter)}<email>reports@mail.example.net</email>"
        f"<report_id>{report_id}</report_id>"
        f"<date_range><begin>{begin}</begin><end>{end}</end></date_range>"
        f"{metadata_extra}</report_metadata>"
        "<policy_published>"
        f"<domain>{domain}</domain>{_optional('p', p)}{_optional('pct', pct)}{policy_extra}"
        "</policy_published>"
        f"{''.join(record_list)}{body_extra}"
        f"</{root_tag}>"
    )
    return text.encode("utf-8")


def _build_gzip(data: bytes) -> bytes:
    """
    Compress bytes into a gzip stream.

    Args:
        data (bytes): The content.

    Returns:
        bytes: The gzip file content.
    """
    return gzip.compress(data)


def _build_zip(members: Mapping[str, bytes]) -> bytes:
    """
    Build a deflated zip in memory.

    Args:
        members (Mapping[str, bytes]): Member name to content, in insertion order.

    Returns:
        bytes: The zip file content.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def make_record_xml() -> Callable[..., str]:
    """
    Provide the ``<record>`` builder.

    Returns:
        Callable[..., str]: ``make_record_xml(**overrides)``, see ``_build_record_xml``.
    """
    return _build_record_xml


@pytest.fixture
def make_report_xml() -> Callable[..., bytes]:
    """
    Provide the report builder, in the RFC 7489 or the RFC 9990 flavor.

    Returns:
        Callable[..., bytes]: ``make_report_xml(**overrides)``, see ``_build_report_xml``.
    """
    return _build_report_xml


@pytest.fixture
def make_gzip() -> Callable[[bytes], bytes]:
    """
    Provide the gzip builder.

    Returns:
        Callable[[bytes], bytes]: ``make_gzip(data)``.
    """
    return _build_gzip


@pytest.fixture
def make_zip() -> Callable[[Mapping[str, bytes]], bytes]:
    """
    Provide the zip builder.

    Returns:
        Callable[[Mapping[str, bytes]], bytes]: ``make_zip(members)``.
    """
    return _build_zip
