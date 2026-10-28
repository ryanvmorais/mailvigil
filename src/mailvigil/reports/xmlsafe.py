"""
The only place that touches an XML parser: it refuses declarations and builds the tree.

A DMARC report never needs a ``DOCTYPE`` or an ``ENTITY``, and both are how XML is attacked (entity
expansion, external entities). The parser is hooked at the level of ``xml.parsers.expat``, which
decodes the document first and then calls the handlers, so the check sees exactly what the parser
sees in whatever encoding the document uses. Searching the raw bytes does not (ADR-1). No
external-entity handler is registered, so even a bug in the refusal could not make the parser open a
file or a URL.

This module does nothing but parse, so a security reviewer can read it alone.
"""

from __future__ import annotations

from typing import NoReturn
from xml.etree.ElementTree import Element, TreeBuilder
from xml.parsers import expat

from mailvigil.reports.errors import Reason, ReportRefused

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# The RFC 9990 namespace. Names in it are read as plain local names, so a report of either
# generation is looked up the same way (ADR-5).
_NAMESPACE_9990 = "urn:ietf:params:xml:ns:dmarc-2.0"

# Separates the namespace URI from the local name in what expat reports. "}" cannot appear in an
# XML name, so the split is unambiguous and the result matches ElementTree's "{uri}local".
_SEPARATOR = "}"

# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _refuse(kind: str) -> NoReturn:
    """
    Refuse the document because it declares something a report never needs.

    Args:
        kind (str): The declaration found, ``"DOCTYPE"`` or ``"ENTITY"``. It goes in the detail;
            the content the declaration carried does not.

    Raises:
        ReportRefused: Always, with ``FORBIDDEN_DECLARATION``.
    """
    raise ReportRefused(Reason.FORBIDDEN_DECLARATION, f"{kind} declaration")


def _local_name(name: str) -> str:
    """
    Translate a name as expat reports it into the name the lookups use.

    Args:
        name (str): ``local``, or ``uri}local`` when the name is in a namespace.

    Returns:
        str: The local name for no namespace and for the RFC 9990 namespace; ``{uri}local`` for any
            other, a name no later lookup asks for, so extension elements are ignored and a
            foreign-namespace root fails the root check.
    """
    if _SEPARATOR not in name:
        return name
    uri, local = name.split(_SEPARATOR, 1)
    return local if uri == _NAMESPACE_9990 else f"{{{uri}}}{local}"


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_xml(xml: bytes) -> Element:
    """
    Parse a document into an element tree, refusing ``DOCTYPE`` and ``ENTITY``.

    Args:
        xml (bytes): The document as read, in any encoding XML allows.

    Returns:
        Element: The root element, with names translated as described in ``_local_name``.

    Raises:
        ReportRefused: ``FORBIDDEN_DECLARATION`` for a ``DOCTYPE`` or an ``ENTITY``, and
            ``MALFORMED_XML`` (detail ``line L, column C``) for a document that is not well formed.
    """
    builder = TreeBuilder()
    parser = expat.ParserCreate(namespace_separator=_SEPARATOR)

    # An exception raised inside a handler stops the parse and comes out of Parse unchanged.
    # The handler attributes are typed loosely by the stubs, so the lambdas need no cast.
    parser.StartDoctypeDeclHandler = lambda *_: _refuse("DOCTYPE")
    # Defense in depth: a DOCTYPE already refused the document, so this one is not expected to fire.
    parser.EntityDeclHandler = lambda *_: _refuse("ENTITY")
    parser.StartElementHandler = lambda name, attrs: builder.start(
        _local_name(name), {_local_name(key): value for key, value in attrs.items()}
    )
    parser.EndElementHandler = lambda name: builder.end(_local_name(name))
    parser.CharacterDataHandler = builder.data
    # Hands the builder whole text nodes instead of the pieces expat splits them into.
    parser.buffer_text = True

    try:
        parser.Parse(xml, True)
    except expat.ExpatError as error:
        raise ReportRefused(
            Reason.MALFORMED_XML, f"line {error.lineno}, column {error.offset}"
        ) from None
    return builder.close()
