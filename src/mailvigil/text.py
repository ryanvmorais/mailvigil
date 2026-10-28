"""
The rules about text and domain names that more than one layer must agree on.

"Which characters can change what a terminal shows" and "when two domains are the same" are security
decisions: the report layer and the configuration layer each need them, and two copies would drift.
The module holds the one definition of each (ADR-4). It does no I/O and imports nothing from the
rest of the package.
"""

from __future__ import annotations

import unicodedata

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Whitespace that XML and TOML allow inside text and that would break a line or move a column on a
# terminal. They become a space, so two words separated with a line break stay two words.
_SPACING = str.maketrans({"\t": " ", "\r": " ", "\n": " "})

# Unicode categories dropped from every text: control (C0 and C1), format (zero-width and the
# bidirectional overrides and isolates), and the line and paragraph separators (ADR-6 of 002).
DROPPED_CATEGORIES = frozenset({"Cc", "Cf", "Zl", "Zp"})

# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------


def clean_text(value: str, limit: int) -> str:
    """
    Make a text from a third party safe to print: inert and short.

    Tab, carriage return and line feed become a space; every character in ``DROPPED_CATEGORIES`` is
    dropped; the result is stripped and cut to ``limit``.

    Args:
        value (str): The text as the XML or TOML parser produced it.
        limit (int): The longest result, in characters.

    Returns:
        str: The cleaned text, possibly empty.
    """
    spaced = value.translate(_SPACING)
    kept = "".join(char for char in spaced if unicodedata.category(char) not in DROPPED_CATEGORIES)
    return kept.strip()[:limit]


def has_dropped_characters(value: str) -> bool:
    """
    Tell whether a text holds a character that ``clean_text`` would remove.

    Tab, carriage return and line feed are control characters, so they count: a name written on
    purpose in a configuration file must not contain a line break.

    Args:
        value (str): The text to check.

    Returns:
        bool: True when any character is in ``DROPPED_CATEGORIES``.
    """
    return any(unicodedata.category(char) in DROPPED_CATEGORIES for char in value)


# ---------------------------------------------------------------------------
# Domains
# ---------------------------------------------------------------------------


def normalize_domain(value: str) -> str:
    """
    Reduce a domain to the form reports use: lower case, no spaces, no trailing dot.

    Args:
        value (str): A domain as a person or a file wrote it.

    Returns:
        str: The normalized domain, empty when ``value`` was blank.
    """
    return value.strip().lower().rstrip(".")


def is_within_domain(candidate: str, parent: str) -> bool:
    """
    Tell whether a name is a domain or one of its subdomains.

    The dot matters: ``notexample.com`` merely ends with the letters of ``example.com`` and is not
    below it (ADR-6).

    Args:
        candidate (str): The name to test, normalized here.
        parent (str): The domain, already normalized.

    Returns:
        bool: True when ``candidate`` equals ``parent`` or ends with a dot plus ``parent``.
    """
    name = normalize_domain(candidate)
    return name == parent or name.endswith("." + parent)
