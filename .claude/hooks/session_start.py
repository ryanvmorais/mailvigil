"""
SessionStart hook (project scope) — environment diagnostics.

When a Claude Code session starts, runs light, NON-blocking checks and prints warnings to stdout
(which Claude Code injects as session context). It never fails the session start: any error is
swallowed.

Checks:
    - ``.venv``: exists (without it ``uv run`` has to build the environment on the first call).
    - ``core.hooksPath``: points to ``.githooks``, so the pre-commit quality gate is active.

Why not block: these are environment hygiene reminders, not code errors.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# <root>/.claude/hooks/session_start.py  ->  <root>
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def check_venv() -> list[str]:
    """
    Warn when the uv virtual environment has not been created.

    Returns:
        list[str]: Zero or one warning.
    """
    if (PROJECT_ROOT / ".venv").is_dir():
        return []
    return ["[.venv] missing - run: uv sync"]


def check_hooks_path() -> list[str]:
    """
    Warn when git is not using the versioned hooks directory.

    Returns:
        list[str]: Zero or one warning.
    """
    out = subprocess.run(
        ["git", "config", "core.hooksPath"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if out == ".githooks":
        return []
    return ["[git] pre-commit gate inactive - run: git config core.hooksPath .githooks"]


def main() -> None:
    """Print the warnings found, if any."""
    try:
        warnings = check_venv() + check_hooks_path()
    except Exception:
        return
    if warnings:
        sys.stdout.write(
            "Environment diagnostics (mailvigil):\n" + "\n".join(f"- {w}" for w in warnings) + "\n"
        )


if __name__ == "__main__":
    main()
