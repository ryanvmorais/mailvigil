"""
Tests that ``docs/json-schema.md`` says what the code does (spec 006, RF-03 and Risk 1).

Two things are checked: the examples on the page are the real output for the values of
``tests/schema_examples.py``, field by field, and the keys of every object, at every level, are
exactly the ones in the page's tables, in order, so an undocumented key fails the suite. The page
is the only file read from the repository.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from tests.schema_examples import CONFIG_SOURCE, example_fetch, example_summary, example_verdict

from mailvigil.render_json import fetch_document, summary_document, verdict_document

_PAGE = Path(__file__).resolve().parent.parent / "docs" / "json-schema.md"

# Which documented object each key of an object holds; a list means "a list of those".
_CHILDREN: dict[str, dict[str, str | list[str]]] = {
    "summary": {
        "config": "summary.config",
        "reports": "summary.reports",
        "period": "period",
        "policy": "policy",
        "totals": "counts",
        "senders": ["sender"],
        "failing": ["source"],
        "skipped": ["skipped"],
        "skipped_by_reason": ["skipped_by_reason"],
    },
    "sender": {"counts": "counts"},
    "verdict": {
        "rules": ["rule"],
        "recognized_failing": ["source"],
        "unrecognized_failing": ["source"],
        "notes": ["note"],
        "left_out": "left_out",
    },
}


def _page() -> str:
    """
    Read the page.

    Returns:
        str: The Markdown text.
    """
    return _PAGE.read_text(encoding="utf-8")


def _documented_keys() -> dict[str, list[str]]:
    """
    Read the first table under each ``### `name``` heading of the page.

    Returns:
        dict[str, list[str]]: For each object name, the keys of its table, in order.
    """
    keys: dict[str, list[str]] = {}
    for name, body in re.findall(r"^### `([^`]+)`\n(.*?)(?=^#{1,3} |\Z)", _page(), re.S | re.M):
        table = re.search(r"^\| Key \|.*?\n(?:\|.*\n?)+", body, re.M)
        if table is not None:
            keys[name] = re.findall(r"^\| `([^`]+)` \|", table.group(0), re.M)
    return keys


def _example(title: str) -> dict[str, object]:
    """
    Read the JSON block under a heading of the examples.

    Args:
        title (str): The heading, for example ``A summary``.

    Returns:
        dict[str, object]: The parsed document.
    """
    match = re.search(rf"^### {title}\n\n```json\n(.*?)\n```", _page(), re.S | re.M)
    assert match is not None, f"no example under '### {title}'"
    loaded = json.loads(match.group(1))
    assert isinstance(loaded, dict)
    return loaded


def _walk(value: object, name: str, documented: dict[str, list[str]], seen: set[str]) -> None:
    """
    Check the keys of an object and of everything under it against the page.

    Args:
        value (object): The object, as parsed from the document.
        name (str): The documented name of that object.
        documented (dict[str, list[str]]): The keys per object name, from the page.
        seen (set[str]): Filled with every name reached.
    """
    assert isinstance(value, dict), name
    seen.add(name)
    assert list(value) == documented[name], name
    for key, child in _CHILDREN.get(name, {}).items():
        if isinstance(child, list):
            items = value[key]
            assert isinstance(items, list), key
            for item in items:
                _walk(item, child[0], documented, seen)
        elif value[key] is not None:
            _walk(value[key], child, documented, seen)


def test_the_summary_example_is_the_real_output() -> None:
    """The page shows what ``summary_document`` writes for the example values."""
    real = summary_document(example_summary(), CONFIG_SOURCE)

    assert _example("A summary") == json.loads(json.dumps(real))


def test_the_verdict_example_is_the_real_output() -> None:
    """The page shows what ``verdict_document`` writes for the example values."""
    real = verdict_document(example_verdict())

    assert _example("A verdict") == json.loads(json.dumps(real))


def test_the_fetch_example_is_the_real_output() -> None:
    """The page shows what ``fetch_document`` writes for the example values."""
    real = fetch_document(example_fetch())

    assert _example("A fetch") == json.loads(json.dumps(real))


def test_every_key_of_the_summary_document_is_documented_in_order() -> None:
    """No key can reach the summary document, at any level, without a row on the page."""
    documented = _documented_keys()
    seen: set[str] = set()

    _walk(summary_document(example_summary(), CONFIG_SOURCE), "summary", documented, seen)

    assert seen == {
        "summary",
        "summary.config",
        "summary.reports",
        "period",
        "policy",
        "counts",
        "sender",
        "source",
        "skipped",
        "skipped_by_reason",
    }


def test_every_key_of_the_verdict_document_is_documented_in_order() -> None:
    """No key can reach the verdict document, at any level, without a row on the page."""
    documented = _documented_keys()
    seen: set[str] = set()

    _walk(verdict_document(example_verdict()), "verdict", documented, seen)

    assert seen == {"verdict", "rule", "source", "note", "left_out"}


def test_every_key_of_the_fetch_document_is_documented_in_order() -> None:
    """No key can reach the fetch document without a row on the page."""
    documented = _documented_keys()
    seen: set[str] = set()

    _walk(fetch_document(example_fetch()), "fetch", documented, seen)

    assert seen == {"fetch"}


def test_the_page_documents_nothing_the_documents_do_not_use() -> None:
    """Every table of the page describes an object that exists; none is left over."""
    documented = set(_documented_keys())

    assert documented == {
        "summary",
        "summary.config",
        "summary.reports",
        "period",
        "policy",
        "counts",
        "sender",
        "source",
        "skipped",
        "skipped_by_reason",
        "verdict",
        "rule",
        "note",
        "left_out",
        "fetch",
    }


def test_the_exit_code_table_of_the_page_is_the_readme_one() -> None:
    """The page repeats the table of the README; the two must list the same codes."""
    page = re.findall(r"^\| `(\d)` \|", _page(), re.M)
    readme = re.findall(
        r"^\| `(\d)` \|", (_PAGE.parent.parent / "README.md").read_text(encoding="utf-8"), re.M
    )

    assert page == readme == ["0", "1", "2", "3", "4"]
