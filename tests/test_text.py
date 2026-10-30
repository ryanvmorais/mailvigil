"""
Tests of the text and domain rules shared by the report and configuration layers (ADR-4).

Isolation: pure functions called with built strings; nothing touches the disk, the network or an
environment variable. The domains are invented (``example.com`` and friends).
"""

from __future__ import annotations

import unicodedata

import pytest

from mailvigil.text import clean_text, has_dropped_characters, is_within_domain, normalize_domain

# ---------------------------------------------------------------------------
# clean_text (RF-05)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("a\x85b", "ab"),  # C1 control (next line)
        ("a\N{RIGHT-TO-LEFT OVERRIDE}b\N{LEFT-TO-RIGHT ISOLATE}c", "abc"),  # bidi override, isolate
        ("a\N{ZERO WIDTH SPACE}b", "ab"),  # zero-width space (Cf)
        ("a\N{LINE SEPARATOR}b\N{PARAGRAPH SEPARATOR}c", "abc"),  # Zl and Zp
        ("a\nb\rc\td", "a b c d"),  # line breaks and tab become a space
        ("  spaced  ", "spaced"),
        ("", ""),
    ],
    ids=["c1", "bidi", "zero-width", "separators", "whitespace-controls", "strip", "empty"],
)
def test_clean_text_removes_or_replaces_what_can_change_a_terminal(raw: str, expected: str) -> None:
    """Characters that hide text or move the cursor never survive ``clean_text``."""
    assert clean_text(raw, 255) == expected


def test_clean_text_cuts_at_the_given_limit() -> None:
    """The limit is the caller's: 255 for a report field, 100 for a configuration key."""
    assert clean_text("a" * 1000, 255) == "a" * 255
    assert clean_text("a" * 1000, 100) == "a" * 100


def test_clean_text_keeps_ordinary_international_text() -> None:
    """Letters of any script are not touched: only control and format characters go."""
    assert clean_text("Müller Støre 日本語", 255) == "Müller Støre 日本語"


# ---------------------------------------------------------------------------
# has_dropped_characters (RF-05)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    ["a\nb", "a\tb", "a\x85b", "a\N{RIGHT-TO-LEFT OVERRIDE}b", "a\N{ZERO WIDTH SPACE}b"],
    ids=["line-break", "tab", "c1", "bidi", "zero-width"],
)
def test_has_dropped_characters_detects_what_clean_text_would_remove(raw: str) -> None:
    """The check and the cleaning agree on what is dangerous."""
    assert has_dropped_characters(raw)


@pytest.mark.parametrize(
    "raw", ["Müller 日本語", "plain text", ""], ids=["scripts", "ascii", "empty"]
)
def test_has_dropped_characters_is_false_for_ordinary_text(raw: str) -> None:
    """Letters of any script and plain spaces are fine."""
    assert not has_dropped_characters(raw)


# ---------------------------------------------------------------------------
# normalize_domain and is_within_domain (RF-02, RF-06)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Example.COM. ", "example.com"),
        ("example.com", "example.com"),
        ("EXAMPLE.ORG..", "example.org"),
        ("", ""),
    ],
)
def test_normalize_domain_lowercases_and_drops_the_trailing_dot(raw: str, expected: str) -> None:
    """Surrounding spaces, case and trailing dots do not make a different domain."""
    assert normalize_domain(raw) == expected


@pytest.mark.parametrize("candidate", ["example.com", "mail.example.com", "MAIL.Example.com."])
def test_is_within_domain_accepts_the_domain_and_its_subdomains(candidate: str) -> None:
    """The domain itself and any name below it belong to the owner."""
    assert is_within_domain(candidate, "example.com")


@pytest.mark.parametrize(
    "candidate",
    ["notexample.com", "example.com.evil.net", "com", "example.org", ""],
    ids=["look-alike", "suffix-trick", "parent", "sibling", "empty"],
)
def test_is_within_domain_refuses_everything_else(candidate: str) -> None:
    """A name that merely ends with the domain's letters is not a subdomain."""
    assert not is_within_domain(candidate, "example.com")


# ---------------------------------------------------------------------------
# clean_text fast path (issue #70)
# ---------------------------------------------------------------------------


def _clean_by_category(value: str, limit: int) -> str:
    """
    Clean a text the slow way: one category lookup per character, no shortcut.

    Args:
        value (str): The text to clean.
        limit (int): The longest result, in characters.

    Returns:
        str: What ``clean_text`` returned before it had a fast path.
    """
    spaced = value.translate(str.maketrans({"\t": " ", "\r": " ", "\n": " "}))
    kept = "".join(
        char for char in spaced if unicodedata.category(char) not in {"Cc", "Cf", "Zl", "Zp"}
    )
    return kept.strip()[:limit]


@pytest.mark.parametrize("code", range(128))
def test_clean_text_agrees_with_the_slow_walk_on_every_ascii_character(code: int) -> None:
    """The shortcut for printable ASCII changes nothing, whatever the one character is."""
    value = f"a{chr(code)}b"
    assert clean_text(value, 255) == _clean_by_category(value, 255)


@pytest.mark.parametrize(
    "value",
    ["  spaced  ", "x" * 300, " " * 10, "a b  c", "mail.example.net", "é plain", "tab\there"],
    ids=["strip", "long", "blank", "inner-spaces", "domain", "non-ascii", "tab"],
)
def test_clean_text_fast_path_keeps_strip_and_cut(value: str) -> None:
    """Printable ASCII is still stripped and cut to the limit, as the slow walk does."""
    assert clean_text(value, 255) == _clean_by_category(value, 255)
    assert clean_text(value, 5) == _clean_by_category(value, 5)
