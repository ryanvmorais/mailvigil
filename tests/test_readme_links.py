"""
Tests that the README links resolve outside the repository (release 1.0.0, issue #83).

The README is also the long description on PyPI, where a link to ``docs/stack.md`` points at
nothing and ``twine check`` does not notice. Every link target is therefore either an absolute URL
or an anchor inside the page. Isolation: the only file read is ``README.md``; when the tests run
from a tree that has none, they are skipped.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# The repository root, one level above the tests folder.
_README = Path(__file__).resolve().parents[1] / "README.md"

# A Markdown link or image target: the text between "](" and the closing parenthesis.
_TARGET = re.compile(r"\]\(([^)\s]+)\)")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _targets() -> list[str]:
    """
    Collect the target of every Markdown link and image in the README.

    Returns:
        list[str]: The targets in the order they appear.
    """
    return _TARGET.findall(_README.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _README.is_file(), reason="README.md is not in this source tree")
def test_readme_links_are_absolute_or_anchors() -> None:
    relative = [t for t in _targets() if not t.startswith(("https://", "#"))]

    assert relative == []


@pytest.mark.skipif(not _README.is_file(), reason="README.md is not in this source tree")
def test_readme_has_links_to_check() -> None:
    # Guards the test above against a regex that stops matching and passes on an empty list.
    assert len(_targets()) > 10
