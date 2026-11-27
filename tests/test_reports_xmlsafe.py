"""
Tests of the safe XML parser (RF-03, RF-10): ``parse_xml`` and its refusal of declarations.

Isolation: every document is built in the test as ``bytes``; nothing touches the disk, the network
or an environment variable. The hostile documents are the attack itself, so a failure here means
the defense is gone. Each one expects ``ReportRefused`` and asserts ``.reason``.
"""

from __future__ import annotations

import re
from collections.abc import Callable

import pytest

from mailvigil.reports import xmlsafe
from mailvigil.reports.errors import Reason, ReportRefused
from mailvigil.reports.xmlsafe import MAX_DEPTH, MAX_ELEMENTS, parse_xml

# The RFC 9990 namespace; parsed names in it lose the namespace (ADR-5).
_NAMESPACE_9990 = "urn:ietf:params:xml:ns:dmarc-2.0"

# ---------------------------------------------------------------------------
# Encodings
# ---------------------------------------------------------------------------

# Each encoder turns text into the bytes of one encoding. The UTF-16 one writes a byte order mark,
# which is how a real UTF-16 document announces itself; the source script's byte search missed it.
_ENCODERS: dict[str, Callable[[str], bytes]] = {
    "utf-8": lambda text: text.encode("utf-8"),
    "utf-8-bom": lambda text: b"\xef\xbb\xbf" + text.encode("utf-8"),
    "utf-16": lambda text: text.encode("utf-16"),
}

_encodings = pytest.mark.parametrize("encode", _ENCODERS.values(), ids=_ENCODERS.keys())

# ---------------------------------------------------------------------------
# Declarations are refused (RF-03)
# ---------------------------------------------------------------------------

_DOCTYPE = "<!DOCTYPE feedback><feedback/>"
_INTERNAL_ENTITY = '<!DOCTYPE feedback [<!ENTITY a "expanded">]><feedback>&a;</feedback>'
# Never resolved: the parser registers no external-entity handler, so nothing is opened.
_EXTERNAL_ENTITY = (
    '<!DOCTYPE feedback [<!ENTITY a SYSTEM "file:///nonexistent/mailvigil-test">]>'
    "<feedback>&a;</feedback>"
)


@_encodings
@pytest.mark.parametrize(
    "document",
    [_DOCTYPE, _INTERNAL_ENTITY, _EXTERNAL_ENTITY],
    ids=["doctype", "internal-entity", "external-entity"],
)
def test_declaration_is_refused_in_every_encoding(
    encode: Callable[[str], bytes], document: str
) -> None:
    """A DOCTYPE or an ENTITY is refused whatever the encoding the document uses."""
    with pytest.raises(ReportRefused) as caught:
        parse_xml(encode(document))

    assert caught.value.reason is Reason.FORBIDDEN_DECLARATION


def test_declaration_after_an_xml_declaration_is_refused() -> None:
    """The XML declaration before the DOCTYPE does not hide it."""
    document = b'<?xml version="1.0" encoding="UTF-8"?>' + _INTERNAL_ENTITY.encode()

    with pytest.raises(ReportRefused) as caught:
        parse_xml(document)

    assert caught.value.reason is Reason.FORBIDDEN_DECLARATION


def test_refusal_detail_does_not_echo_the_document() -> None:
    """The detail names the declaration, never the content the document declared."""
    with pytest.raises(ReportRefused) as caught:
        parse_xml(_EXTERNAL_ENTITY.encode())

    assert "mailvigil-test" not in caught.value.detail
    assert "file:" not in caught.value.detail


# ---------------------------------------------------------------------------
# Clean documents are accepted (RF-03)
# ---------------------------------------------------------------------------


def test_document_with_a_declaration_and_a_comment_is_accepted() -> None:
    """An XML declaration and a comment are not declarations of the kind refused."""
    document = b'<?xml version="1.0" encoding="UTF-8"?><!-- ok --><feedback><a>x</a></feedback>'

    root = parse_xml(document)

    assert root.tag == "feedback"
    assert root.findtext("a") == "x"


def test_clean_utf16_document_is_accepted() -> None:
    """The check does not refuse a UTF-16 document just for its encoding."""
    root = parse_xml("<feedback><a>x</a></feedback>".encode("utf-16"))

    assert root.findtext("a") == "x"


def test_text_is_joined_and_built_in_entities_are_expanded() -> None:
    """``buffer_text`` hands the builder whole text nodes, with ``&amp;`` already resolved."""
    root = parse_xml(b"<feedback><a>one &amp; two &lt;three&gt;</a></feedback>")

    assert root.findtext("a") == "one & two <three>"


# ---------------------------------------------------------------------------
# Malformed XML (RF-10)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "document",
    [b"<feedback><a></feedback>", b"", b"not xml at all", b"<feedback>&undefined;</feedback>"],
    ids=["mismatched-tag", "empty", "not-xml", "undefined-entity"],
)
def test_malformed_xml_is_refused_with_the_position(document: bytes) -> None:
    """Broken XML is ``MALFORMED_XML`` and the detail carries ``line L, column C``."""
    with pytest.raises(ReportRefused) as caught:
        parse_xml(document)

    assert caught.value.reason is Reason.MALFORMED_XML
    assert re.fullmatch(r"line \d+, column \d+", caught.value.detail)


@pytest.mark.parametrize(
    "encoding", ["x-mailvigil-no-such-codec", "shift_jis"], ids=["unknown", "multibyte"]
)
def test_an_encoding_the_parser_cannot_use_is_refused(encoding: str) -> None:
    """Expat hands such an encoding to a hook that raises outside ``ExpatError``."""
    document = f'<?xml version="1.0" encoding="{encoding}"?><feedback/>'.encode("ascii")

    with pytest.raises(ReportRefused) as caught:
        parse_xml(document)

    assert caught.value.reason is Reason.MALFORMED_XML


# ---------------------------------------------------------------------------
# Namespace translation (ADR-5)
# ---------------------------------------------------------------------------


def test_no_namespace_keeps_the_local_names() -> None:
    """An RFC 7489 report has no namespace, so the names are used as written."""
    root = parse_xml(b"<feedback><a/></feedback>")

    assert root.tag == "feedback"
    assert [child.tag for child in root] == ["a"]


def test_rfc_9990_namespace_becomes_the_local_name() -> None:
    """The dmarc-2.0 namespace is dropped, so both generations are read the same way."""
    document = f'<feedback xmlns="{_NAMESPACE_9990}"><a/></feedback>'.encode()

    root = parse_xml(document)

    assert root.tag == "feedback"
    assert [child.tag for child in root] == ["a"]


def test_foreign_namespace_keeps_the_uri_so_no_lookup_matches() -> None:
    """A foreign root becomes ``{uri}feedback``, which fails the parser's root check."""
    root = parse_xml(b'<feedback xmlns="urn:example:other"><a/></feedback>')

    assert root.tag == "{urn:example:other}feedback"
    assert [child.tag for child in root] == ["{urn:example:other}a"]


def test_extension_element_in_a_foreign_namespace_is_set_apart() -> None:
    """An extension inside a plain report keeps its URI and does not shadow a real element."""
    document = b'<feedback xmlns:x="urn:example:ext"><x:extra/><extra/></feedback>'

    root = parse_xml(document)

    assert [child.tag for child in root] == ["{urn:example:ext}extra", "extra"]
    assert root.find("extra") is not None


# ---------------------------------------------------------------------------
# A document built to be expensive for its size (RF-03b, ADR-8)
# ---------------------------------------------------------------------------


def _nested(depth: int) -> bytes:
    """
    Build a well-formed document that is ``depth`` levels deep.

    Args:
        depth (int): How many elements are open at the deepest point.

    Returns:
        bytes: The document.
    """
    return b"<a>" * depth + b"</a>" * depth


def _flat(elements: int) -> bytes:
    """
    Build a document of ``elements`` elements, the root included, all but the root empty.

    Args:
        elements (int): The total number of elements, at least one.

    Returns:
        bytes: The document.
    """
    return b"<f>" + b"<a/>" * (elements - 1) + b"</f>"


def test_a_document_at_the_depth_limit_is_accepted() -> None:
    """The limit itself is allowed; only a level more is refused."""
    root = parse_xml(_nested(MAX_DEPTH))

    assert root.tag == "a"


def test_a_document_one_level_over_the_depth_limit_is_refused() -> None:
    """The first element past ``MAX_DEPTH`` levels refuses the document."""
    with pytest.raises(ReportRefused) as caught:
        parse_xml(_nested(MAX_DEPTH + 1))

    assert caught.value.reason is Reason.XML_TOO_COMPLEX
    assert str(MAX_DEPTH) in caught.value.detail


def test_depth_is_the_nesting_and_not_the_total_of_the_siblings() -> None:
    """A long run of siblings is wide, not deep, so only the element count can stop it."""
    document = b"<f>" + (b"<a><b/></a>" * 1000) + b"</f>"

    assert len(parse_xml(document)) == 1000


def test_a_five_mebibyte_nest_is_refused_while_it_is_read() -> None:
    """The attack itself: the refusal comes at the 33rd element, not after a tree of 750,000."""
    document = b"<a>" * (5 * 1024 * 1024 // 7)

    with pytest.raises(ReportRefused) as caught:
        parse_xml(document)

    assert caught.value.reason is Reason.XML_TOO_COMPLEX


def test_a_document_at_the_element_limit_is_accepted() -> None:
    """``MAX_ELEMENTS`` elements, the root included, are allowed."""
    root = parse_xml(_flat(MAX_ELEMENTS))

    assert len(root) == MAX_ELEMENTS - 1


def test_a_document_one_element_over_the_limit_is_refused() -> None:
    """One element more than ``MAX_ELEMENTS`` refuses the document."""
    with pytest.raises(ReportRefused) as caught:
        parse_xml(_flat(MAX_ELEMENTS + 1))

    assert caught.value.reason is Reason.XML_TOO_COMPLEX
    assert str(MAX_ELEMENTS) in caught.value.detail


def test_the_complexity_detail_does_not_echo_the_document() -> None:
    """The detail names the limit only, never a name from the document."""
    with pytest.raises(ReportRefused) as caught:
        parse_xml(_nested(MAX_DEPTH + 1).replace(b"a", b"secret_tag"))

    assert "secret_tag" not in caught.value.detail


# ---------------------------------------------------------------------------
# Attributes and namespace declarations count like elements
# ---------------------------------------------------------------------------


def _attributes(count: int, shape: str) -> bytes:
    """
    Build a root element that holds ``count`` attributes or namespace declarations.

    Args:
        count (int): How many to put on the root.
        shape (str): ``"a{n}"`` for plain attributes, ``"xmlns:p{n}"`` for declarations.

    Returns:
        bytes: The document, one empty root element.
    """
    pairs = " ".join(f'{shape.format(n=number)}="u"' for number in range(count))
    return f"<feedback {pairs}/>".encode()


@pytest.mark.parametrize("shape", ["a{n}", "xmlns:p{n}"])
def test_attributes_at_the_cap_with_their_element_are_accepted(
    shape: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The root and four attributes, or four declarations, are five items: exactly the cap."""
    monkeypatch.setattr(xmlsafe, "MAX_ELEMENTS", 5)

    assert parse_xml(_attributes(4, shape)).tag == "feedback"


@pytest.mark.parametrize("shape", ["a{n}", "xmlns:p{n}"])
def test_attributes_past_the_cap_refuse_the_document(
    shape: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One more is six items: the attributes count against ``MAX_ELEMENTS``, not only elements."""
    monkeypatch.setattr(xmlsafe, "MAX_ELEMENTS", 5)

    with pytest.raises(ReportRefused) as caught:
        parse_xml(_attributes(5, shape))

    assert caught.value.reason is Reason.XML_TOO_COMPLEX


def test_attributes_spread_over_elements_add_up_to_the_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two elements of two attributes each are six items, so the count runs across the document."""
    monkeypatch.setattr(xmlsafe, "MAX_ELEMENTS", 5)
    document = b'<feedback a="" b=""><x c="" d=""/></feedback>'

    with pytest.raises(ReportRefused) as caught:
        parse_xml(document)

    assert caught.value.reason is Reason.XML_TOO_COMPLEX
