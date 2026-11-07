"""
Tests that what is versioned speaks to whoever cloned the repository, not to one person.

Two rules are guarded. The maintainer's first name appears only where authorship says it (the
license and the package metadata), and the files written for an AI assistant (``CLAUDE.md`` and
``.claude/``) describe the project and do not point at tools only one machine has.

Isolation: the tests ask ``git ls-files`` which files are versioned and read them as text, so
nothing is created and nothing is written. When ``git`` is missing or the tests run from a source
tree with no repository (an sdist), they are skipped.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# The repository root, one level above the tests folder.
_ROOT = Path(__file__).resolve().parents[1]

# The first name as a whole word: a URL such as ``github.com/ryanvmorais`` is lower case and one
# word, so it does not match.
_NAME = re.compile(r"\bRyan\b")

# Authorship and this file, which has to spell the name to look for it.
_NAME_ALLOWED = frozenset({"LICENSE", "pyproject.toml", "tests/test_impersonality.py"})

# Commands of personal skills, and the personal configuration folder. A slash command is a name
# after a slash that no word, dot or slash precedes, so ``docs/stack.md`` is not one.
_PERSONAL_TOOLS = re.compile(
    r"(?<![\w/.~-])/(?:idioma|spec|estilo-arquivos|fechar-sessao|atualizar-docs|"
    r"revisar-dependabot|nova-interface|stack|novo-projeto|atualizar-dependencias|"
    r"preparar-release|atualizar-ferramentas|qualidade-python|limpar-branches|"
    r"enxugar-memoria|auditoria-[a-z]+)(?![\w/.-])|~/\.claude"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _versioned_files() -> list[str]:
    """
    List the versioned files, as paths with ``/`` relative to the repository root.

    Returns:
        list[str]: The paths Git tracks; the test is skipped when Git cannot list them.
    """
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is not installed")
    result = subprocess.run(
        [git, "ls-files", "-z"],
        cwd=_ROOT,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        pytest.skip("not a Git repository")
    return [name for name in result.stdout.decode("utf-8").split("\0") if name]


def _read_text(name: str) -> str | None:
    """
    Read a versioned file as text.

    Args:
        name (str): A path relative to the repository root.

    Returns:
        str | None: The text, or ``None`` for a file that is gone from the working tree or is not
            UTF-8 (an image).
    """
    try:
        return (_ROOT / name).read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


# ---------------------------------------------------------------------------
# The rules
# ---------------------------------------------------------------------------


def test_the_name_of_the_maintainer_is_only_in_authorship() -> None:
    """No versioned file but the license and the package metadata names the maintainer."""
    found: list[str] = []
    for name in _versioned_files():
        if name == "uv.lock" or name in _NAME_ALLOWED:
            continue
        text = _read_text(name)
        if text is not None and _NAME.search(text):
            found.append(name)
    assert found == []


def test_assistant_files_do_not_point_at_personal_tools() -> None:
    """``CLAUDE.md`` and ``.claude/`` name no personal skill and no personal configuration."""
    found: list[str] = []
    for name in _versioned_files():
        if name != "CLAUDE.md" and not name.startswith(".claude/"):
            continue
        text = _read_text(name)
        if text is not None and _PERSONAL_TOOLS.search(text):
            found.append(name)
    assert found == []
