"""
Tests of the ignore rules that keep private data out of Git (spec 009, RNF-07).

Isolation: the tests read ``.gitignore`` as text and ask ``git check-ignore`` about paths that do
not exist, so nothing is created and nothing is written. When ``git`` is missing or the tests run
from a source tree with no repository (an sdist), the questions to Git are skipped and the text
checks still run.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

# The repository root, one level above the tests folder.
_ROOT = Path(__file__).resolve().parents[1]
_GITIGNORE = _ROOT / ".gitignore"


def _is_ignored(path: str) -> bool:
    """
    Ask Git whether a path would be ignored.

    Args:
        path (str): A path relative to the repository root; it need not exist.

    Returns:
        bool: ``True`` when an ignore rule matches it and no negation re-includes it.
    """
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is not installed")
    result = subprocess.run(
        [git, "check-ignore", "--quiet", "--", path],
        cwd=_ROOT,
        check=False,
        capture_output=True,
    )
    if result.returncode == 128:
        pytest.skip("not inside a Git repository")
    return result.returncode == 0


def _rules() -> list[str]:
    """Read the active lines of ``.gitignore``, without comments and blank lines."""
    lines = _GITIGNORE.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]


def test_the_file_ignores_saved_messages_and_mailboxes() -> None:
    rules = _rules()
    assert "*.eml" in rules
    assert "*.mbox" in rules


def test_the_negations_keep_the_synthetic_messages_under_tests() -> None:
    rules = _rules()
    assert "!tests/**/*.eml" in rules
    assert "!tests/**/*.mbox" in rules
    # A negation only works after the pattern it undoes.
    assert rules.index("*.eml") < rules.index("!tests/**/*.eml")
    assert rules.index("*.mbox") < rules.index("!tests/**/*.mbox")


@pytest.mark.parametrize(
    "path",
    ["inbox/report.eml", "a1b2c3d4-1-9.eml", "dmarc/export.mbox", "reports/mail/x.eml", "x.eml"],
)
def test_a_message_outside_tests_is_ignored(path: str) -> None:
    assert _is_ignored(path)


@pytest.mark.parametrize(
    "path", ["tests/sample.eml", "tests/data/mail/sample.eml", "tests/data/box.mbox"]
)
def test_a_message_under_tests_is_not_ignored(path: str) -> None:
    assert not _is_ignored(path)
