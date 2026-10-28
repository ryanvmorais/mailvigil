"""
The one module that builds markup (spec 008, ADR-1).

The HTML report is made of text that a third party controls (organizations, selectors, source
addresses, domains), so the rule is that **no ``str`` becomes markup except through this module**.
``Safe`` is a ``NewType`` of ``str``: ``text()`` is the only function that turns a ``str`` into a
``Safe`` by escaping it, ``el()`` accepts nothing but ``Safe`` children, and so passing a raw
``str`` where markup is expected is a type error that the strict ``mypy`` gate reports on every
commit. The type is erased at run time, so the other half of the defense is a test that reads the
source of the modules of the page and that parses the finished document.

``el()`` also refuses, at run time, any tag or attribute outside an allowlist: no ``script``, no
``iframe``, no event handler and no ``href`` other than a ``#`` fragment, even if a caller tried.
The constant parts of the page (the stylesheet, the paths of the icons) enter through ``raw()``,
and a test lists its call sites so that no variable reaches it. ``finish()`` writes the whole
document as ASCII with numeric character references (ADR-7). The module imports nothing of the
project.
"""

from __future__ import annotations

import re
from html import escape
from typing import Final, NewType

#: Markup that is already safe to concatenate into a document.
Safe = NewType("Safe", str)

# ---------------------------------------------------------------------------
# The allowlists
# ---------------------------------------------------------------------------

# The elements the page uses and no other: the structure, the text, the tables, ``details`` for the
# numbers behind a chart, and the few SVG elements of the icons and the charts. ``style`` and
# ``meta`` are absent on purpose: only ``document()`` writes the head.
_TAGS: Final = frozenset(
    {
        "header",
        "main",
        "section",
        "footer",
        "div",
        "span",
        "p",
        "h1",
        "h2",
        "h3",
        "ul",
        "li",
        "dl",
        "dt",
        "dd",
        "table",
        "thead",
        "tbody",
        "tfoot",
        "tr",
        "th",
        "td",
        "strong",
        "code",
        "i",
        "b",
        "details",
        "summary",
        "br",
        "svg",
        "g",
        "defs",
        "pattern",
        "path",
        "rect",
        "polygon",
        "line",
        "circle",
    }
)

# Elements with no content in HTML: a closing tag would be an error.
_VOID: Final = frozenset({"br"})

# SVG shapes: an empty one is written self-closed, which the HTML parser accepts inside ``svg``.
_SHAPES: Final = frozenset({"path", "rect", "polygon", "line", "circle"})

# The attributes the page uses. ``href`` is checked apart; ``src``, ``srcdoc``, ``formaction`` and
# every ``on...`` handler are simply not here, so there is nothing to forget to forbid.
_ATTRS: Final = frozenset(
    {
        "class",
        "id",
        "role",
        "tabindex",
        "scope",
        "colspan",
        "open",
        "style",
        "href",
        "aria-label",
        "aria-labelledby",
        "aria-hidden",
        "focusable",
        "width",
        "height",
        "viewBox",
        "preserveAspectRatio",
        "x",
        "y",
        "x1",
        "y1",
        "x2",
        "y2",
        "cx",
        "cy",
        "r",
        "rx",
        "ry",
        "d",
        "points",
        "transform",
        "fill",
        "stroke",
        "stroke-width",
        "stroke-linecap",
        "stroke-linejoin",
        "stroke-dasharray",
        "patternUnits",
        "patternTransform",
    }
)

# The only link the page may hold: a fragment of itself.
_FRAGMENT: Final = re.compile(r"#[A-Za-z0-9_-]+")

# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------


def text(value: str) -> Safe:
    """
    Escape a string so that it can only be read as text.

    This is the only function that turns a ``str`` into a ``Safe``, in a text position or inside a
    quoted attribute: ``<``, ``>``, ``&``, ``"`` and ``'`` all become references.

    Args:
        value (str): Any text, trusted or not.

    Returns:
        Safe: The escaped text.
    """
    return Safe(escape(value, quote=True))


def raw(markup: str) -> Safe:
    """
    Pass a constant through as markup, unescaped.

    For the stylesheet and the fixed paths of the icons only. A test reads every call site and
    accepts a string literal or an upper-case constant, so a variable cannot reach this function.

    Args:
        markup (str): A constant piece of markup.

    Returns:
        Safe: The same string, marked as safe.
    """
    return Safe(markup)


def fragment(*children: Safe) -> Safe:
    """
    Put pieces of markup side by side.

    Args:
        *children (Safe): The pieces, in order.

    Returns:
        Safe: Their concatenation.
    """
    return Safe("".join(children))


def _attribute_name(name: str) -> str:
    # ``class_`` is ``class`` and ``aria_label`` is ``aria-label``; ``viewBox`` stays as it is.
    return name.removesuffix("_").replace("_", "-")


def _check_attribute(name: str, value: str) -> None:
    if name not in _ATTRS:
        raise ValueError(f"attribute not allowed: {name!r}")
    if name == "href" and not _FRAGMENT.fullmatch(value):
        raise ValueError(f"attribute not allowed: href must be a '#fragment', got {value!r}")


def el(name: str, *children: Safe, **attrs: str) -> Safe:
    """
    Build one element, escaping every attribute value.

    Args:
        name (str): The tag, which must be in the allowlist.
        *children (Safe): The content, already safe; a ``str`` here is a type error.
        **attrs (str): The attributes; a trailing underscore is dropped and the others become
            hyphens (``class_`` is ``class``, ``aria_label`` is ``aria-label``).

    Returns:
        Safe: The element.

    Raises:
        ValueError: If the tag or an attribute is outside the allowlist, or an ``href`` is not a
            fragment of the page.
    """
    if name not in _TAGS:
        raise ValueError(f"tag not allowed: {name!r}")
    pairs = []
    for key, value in attrs.items():
        attribute = _attribute_name(key)
        _check_attribute(attribute, value)
        pairs.append(f' {attribute}="{escape(value, quote=True)}"')
    opening = f"{name}{''.join(pairs)}"
    if name in _VOID:
        return Safe(f"<{opening}>")
    if name in _SHAPES and not children:
        return Safe(f"<{opening}/>")
    return Safe(f"<{opening}>{''.join(children)}</{name}>")


# ---------------------------------------------------------------------------
# The document
# ---------------------------------------------------------------------------


def _meta(**attrs: str) -> str:
    # The head is the one place that writes ``meta``, with fixed attribute names.
    pairs = "".join(
        f' {key.replace("_", "-")}="{escape(value, quote=True)}"' for key, value in attrs.items()
    )
    return f"<meta{pairs}>"


def document(*, lang: str, title: str, policy: str, css: Safe, body: Safe) -> Safe:
    """
    Wrap the body in a complete document.

    The head carries the charset, the viewport, the content security policy (ADR-8), the title and
    the stylesheet; nothing else, so the page loads nothing.

    Args:
        lang (str): The language code of the text, for the ``lang`` attribute.
        title (str): The title of the page; escaped.
        policy (str): The content security policy; escaped.
        css (Safe): The stylesheet, a constant passed through ``raw()``.
        body (Safe): The content of the ``body`` element.

    Returns:
        Safe: The document, starting with the doctype.
    """
    head = "".join(
        [
            _meta(charset="utf-8"),
            _meta(name="viewport", content="width=device-width, initial-scale=1"),
            _meta(http_equiv="Content-Security-Policy", content=policy),
            f"<title>{text(title)}</title>",
            f"<style>{css}</style>",
        ]
    )
    return Safe(
        f'<!doctype html><html lang="{escape(lang, quote=True)}">'
        f"<head>{head}</head><body>{body}</body></html>"
    )


def finish(markup: Safe) -> str:
    """
    Write the document as the string the command prints.

    ASCII only, with numeric character references for everything else, so that no console encoding
    or code page can change a character (ADR-7); the page still declares UTF-8. Ends in one
    newline.

    Args:
        markup (Safe): The finished document.

    Returns:
        str: ASCII text ending in a newline.
    """
    ascii_text = markup.encode("ascii", errors="xmlcharrefreplace").decode("ascii")
    return ascii_text.rstrip("\n") + "\n"
