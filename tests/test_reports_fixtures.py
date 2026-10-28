"""
Tests of the synthetic factories in ``conftest.py``.

The factories feed every other reports test, so a wrong one would make them pass or fail for the
wrong reason. The documents here are clean, so the standard parser is safe to use on them.
"""

from __future__ import annotations

import gzip
import io
import zipfile
from collections.abc import Callable, Mapping
from xml.etree import ElementTree

# The RFC 9990 namespace, repeated here on purpose: the test must not share the constant of the
# factory it checks.
_NAMESPACE_9990 = "urn:ietf:params:xml:ns:dmarc-2.0"


# ---------------------------------------------------------------------------
# The report and record builders
# ---------------------------------------------------------------------------


def test_default_report_is_well_formed_without_a_namespace(
    make_report_xml: Callable[..., bytes],
) -> None:
    """The RFC 7489 flavor has a plain ``feedback`` root with the three blocks."""
    root = ElementTree.fromstring(make_report_xml())

    assert root.tag == "feedback"
    assert root.find("report_metadata/org_name") is not None
    assert root.findtext("policy_published/domain") == "example.com"
    assert len(root.findall("record")) == 1


def test_rfc_9990_flavor_puts_the_root_in_the_namespace(
    make_report_xml: Callable[..., bytes],
) -> None:
    """The RFC 9990 flavor differs from the other only by the namespace."""
    root = ElementTree.fromstring(make_report_xml(flavor="9990"))

    assert root.tag == f"{{{_NAMESPACE_9990}}}feedback"


def test_report_overrides_and_omissions(make_report_xml: Callable[..., bytes]) -> None:
    """``None`` omits an element and an empty record list gives a report without rows."""
    root = ElementTree.fromstring(make_report_xml(reporter=None, pct=50, version="1.0", records=[]))

    assert root.find("report_metadata/org_name") is None
    assert root.findtext("policy_published/pct") == "50"
    assert root.findtext("version") == "1.0"
    assert root.findall("record") == []


def test_record_blocks_repeat(make_record_xml: Callable[..., str]) -> None:
    """Several DKIM blocks and override reasons are emitted in order."""
    record = ElementTree.fromstring(
        make_record_xml(
            dkim=[("a.example.com", "s1", "pass"), ("b.example.com", "s2", "fail")],
            reasons=[("forwarded", "relay")],
        )
    )

    selectors = [node.findtext("selector") for node in record.findall("auth_results/dkim")]
    assert selectors == ["s1", "s2"]
    assert record.findtext("row/policy_evaluated/reason/type") == "forwarded"


# ---------------------------------------------------------------------------
# The archive builders
# ---------------------------------------------------------------------------


def test_gzip_and_zip_round_trip(
    make_gzip: Callable[[bytes], bytes], make_zip: Callable[[Mapping[str, bytes]], bytes]
) -> None:
    """The archive builders produce files the standard library reads back unchanged."""
    assert gzip.decompress(make_gzip(b"data")) == b"data"

    with zipfile.ZipFile(io.BytesIO(make_zip({"a.xml": b"one", "b.xml": b"two"}))) as archive:
        assert archive.namelist() == ["a.xml", "b.xml"]
        assert archive.read("b.xml") == b"two"
