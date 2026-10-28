"""
Tests of ``htmlkit``, the one module that builds markup (spec 008, RF-06, ADR-1 and ADR-7).

Isolation: nothing touches the disk except the ``mypy`` check, which writes one snippet under
``tmp_path``. The markup is judged twice, as the spec says: the small functions are compared with
exact strings, and the source of every module of the page is read with ``ast`` so that no other
file can build a tag or call ``escape`` (the type is the first defense, the scan is the proof).
"""

from __future__ import annotations

import ast
from html.parser import HTMLParser
from pathlib import Path

import pytest
from mypy import api as mypy_api

from mailvigil.htmlkit import Safe, document, el, finish, fragment, raw, text

# Found from this file, not from the working directory, so the scan runs from any folder.
_SOURCE = Path(__file__).resolve().parent.parent / "src" / "mailvigil"

# ---------------------------------------------------------------------------
# text() and el()
# ---------------------------------------------------------------------------


def test_text_escapes_the_five_characters() -> None:
    assert text("<>&\"'") == "&lt;&gt;&amp;&quot;&#x27;"


def test_text_leaves_plain_text_alone() -> None:
    assert text("example.com 2001:db8::25") == "example.com 2001:db8::25"


def test_el_builds_a_non_void_element() -> None:
    assert el("p", text("a"), text("b"), class_="x") == '<p class="x">ab</p>'


def test_el_builds_a_void_element_with_no_closing_tag() -> None:
    assert el("br") == "<br>"


def test_el_builds_a_childless_svg_shape_self_closed() -> None:
    assert el("path", d="M0 0") == '<path d="M0 0"/>'


def test_el_writes_the_attributes_in_the_order_given() -> None:
    assert el("rect", x="1", y="2") == '<rect x="1" y="2"/>'


def test_el_maps_python_names_to_attribute_names() -> None:
    assert el("div", aria_label="a", class_="b") == '<div aria-label="a" class="b"></div>'


def test_el_keeps_the_camel_case_of_svg_attributes() -> None:
    assert el("svg", viewBox="0 0 1 1") == '<svg viewBox="0 0 1 1"></svg>'


def test_el_escapes_attribute_values() -> None:
    markup = el("div", aria_label='" onmouseover="x\' <b>&')
    assert markup == ('<div aria-label="&quot; onmouseover=&quot;x&#x27; &lt;b&gt;&amp;"></div>')


def test_el_allows_a_fragment_link() -> None:
    assert el("span", href="#main") == '<span href="#main"></span>'


@pytest.mark.parametrize(
    "name",
    [
        "script",
        "iframe",
        "object",
        "embed",
        "form",
        "link",
        "base",
        "meta",
        "style",
        "html",
        "img",
        "input",
        "a",
        "SCRIPT",
        "p onclick=x",
        "",
    ],
)
def test_el_refuses_a_tag_outside_the_allowlist(name: str) -> None:
    with pytest.raises(ValueError, match="tag"):
        el(name)


@pytest.mark.parametrize(
    "attrs",
    [
        {"onclick": "x"},
        {"onerror": "x"},
        {"onload": "x"},
        {"OnClick": "x"},
        {"srcdoc": "x"},
        {"formaction": "x"},
        {"xlink_href": "#a"},
        {"src": "#a"},
        {"src": "https://example.com/a.png"},
        {"href": "https://example.com"},
        {"href": "javascript:alert(1)"},
        {"href": "//example.com"},
        {"href": "#a b"},
        {"href": '#a"'},
        {"href": ""},
        {"unknown": "x"},
    ],
)
def test_el_refuses_an_attribute_outside_the_allowlist(attrs: dict[str, str]) -> None:
    with pytest.raises(ValueError, match="attribute"):
        el("div", **attrs)


def test_fragment_joins_the_parts_in_order() -> None:
    assert fragment(text("a"), el("br"), text("b")) == "a<br>b"


def test_fragment_of_nothing_is_empty() -> None:
    assert fragment() == ""


def test_raw_returns_the_constant_unchanged() -> None:
    assert raw("<path/>") == "<path/>"


# ---------------------------------------------------------------------------
# document() and finish()
# ---------------------------------------------------------------------------


class _Collector(HTMLParser):
    """Collect the start tags and the text of a document, to judge it parsed."""

    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []
        self.chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, data: str) -> None:
        self.chunks.append(data)


def _parse(markup: str) -> _Collector:
    collector = _Collector()
    collector.feed(markup)
    return collector


def _page(**changes: str) -> str:
    """
    Build a small document, changing only the parts a test names.

    Args:
        **changes (str): Replacements for ``lang``, ``title``, ``policy`` or ``body``.

    Returns:
        str: The document.
    """
    values = {
        "lang": "en",
        "title": "MailVigil",
        "policy": "default-src 'none'",
        "body": "ok",
    }
    values.update(changes)
    return document(
        lang=values["lang"],
        title=values["title"],
        policy=values["policy"],
        css=raw("body{margin:0}"),
        body=text(values["body"]),
    )


def test_document_starts_with_the_doctype_and_names_the_language() -> None:
    page = _page(lang="pt-BR")
    assert page.startswith('<!doctype html><html lang="pt-BR">')


def test_document_head_has_the_charset_viewport_policy_and_title() -> None:
    parsed = _parse(_page())
    metas = [attrs for tag, attrs in parsed.tags if tag == "meta"]
    assert {"charset": "utf-8"} in metas
    assert {"name": "viewport", "content": "width=device-width, initial-scale=1"} in metas
    assert {"http-equiv": "Content-Security-Policy", "content": "default-src 'none'"} in metas
    assert "style" in [tag for tag, _ in parsed.tags]


def test_document_escapes_the_title_and_the_policy() -> None:
    page = _page(title="</title><script>x", policy="'\"><script>")
    parsed = _parse(page)
    assert [tag for tag, _ in parsed.tags if tag == "script"] == []
    assert "</title><script>x" in "".join(parsed.chunks)


def test_document_puts_the_body_inside_the_body_element() -> None:
    page = _page(body="hello")
    assert page.endswith("<body>hello</body></html>")


def test_finish_returns_ascii_with_numeric_references() -> None:
    page = finish(text("café \U0001f600"))
    assert page == "caf&#233; &#128512;\n"
    assert page.isascii()


def test_finish_does_not_raise_on_a_lone_surrogate() -> None:
    page = finish(text("a\ud800b"))
    assert page.isascii()
    assert page.startswith("a") and page.endswith("b\n")


def test_finish_ends_in_exactly_one_newline() -> None:
    assert finish(Safe("a")) == "a\n"
    assert finish(Safe("a\n")) == "a\n"


# ---------------------------------------------------------------------------
# The type is the first defense (ADR-1)
# ---------------------------------------------------------------------------


def test_mypy_rejects_a_plain_str_where_markup_is_expected(tmp_path: Path) -> None:
    snippet = tmp_path / "snippet.py"
    snippet.write_text(
        "from mailvigil.htmlkit import el, text\n"
        "good = el('p', text('x'))\n"
        "bad = el('p', 'x')\n",
        encoding="utf-8",
    )
    stdout, _, status = mypy_api.run(
        ["--strict", "--cache-dir", str(tmp_path / "cache"), str(snippet)]
    )
    assert status == 1
    assert "snippet.py:3" in stdout
    assert "snippet.py:2" not in stdout
    assert 'expected "Safe"' in stdout


# ---------------------------------------------------------------------------
# The source guards (RF-06)
# ---------------------------------------------------------------------------


def _page_modules() -> list[Path]:
    paths = [*sorted(_SOURCE.glob("html*.py")), _SOURCE / "render_html.py"]
    return [path for path in paths if path.exists()]


def _outside_the_kit() -> list[Path]:
    return [path for path in _page_modules() if path.name != "htmlkit.py"]


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _called_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def test_the_modules_of_the_page_are_found() -> None:
    names = {path.name for path in _page_modules()}
    assert {"htmlkit.py", "html_style.py"} <= names


@pytest.mark.parametrize("path", _page_modules(), ids=lambda path: path.name)
def test_every_call_to_raw_gets_a_literal_or_a_constant(path: Path) -> None:
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Call) and _called_name(node) == "raw":
            assert len(node.args) == 1 and not node.keywords, (path.name, node.lineno)
            (argument,) = node.args
            literal = isinstance(argument, ast.Constant) and isinstance(argument.value, str)
            constant = isinstance(argument, ast.Name) and argument.id.lstrip("_").isupper()
            assert literal or constant, f"{path.name}:{node.lineno}: raw() got a variable"


@pytest.mark.parametrize("path", _outside_the_kit(), ids=lambda path: path.name)
def test_only_the_kit_makes_a_safe_or_escapes(path: Path) -> None:
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            assert not any(alias.name.split(".")[0] == "html" for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] != "html"
        if isinstance(node, ast.Call):
            assert _called_name(node) not in {"escape", "Safe"}, (path.name, node.lineno)


@pytest.mark.parametrize("path", _outside_the_kit(), ids=lambda path: path.name)
def test_no_other_module_writes_a_tag_as_text(path: Path) -> None:
    tree = _tree(path)
    docstrings = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
    }
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ):
            assert "<" not in node.value, f"{path.name}:{node.lineno}: a tag written as text"
