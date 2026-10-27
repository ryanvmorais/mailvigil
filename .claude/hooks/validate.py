"""
Stop hook (project scope) — layer 2: whole-project validation.

When Claude ends a turn, validates the project with ruff + mypy using the ``.venv`` Python (managed
by uv). On failure it writes the errors to stderr and exits with code 2; Claude Code hands that
back to the agent, which fixes them before finishing (an automatic quality loop).

pytest is NOT here on purpose (it is heavy and may be legitimately red in the middle of a
feature); it belongs to the pre-commit hook and the CI.

Robustness decisions:
    - Only validates when there is a modified ``.py`` file in src/ or tests/ (via git).
    - Without the ``.venv`` it does not block (an environment problem must not trap the agent).
    - Honors ``stop_hook_active``: it revalidates the fix once and, if it still fails, lets the
      stop through so it never loops forever.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

# <root>/.claude/hooks/validate.py  ->  <root>
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
# Only these trees hold the project's Python; a changed file elsewhere (docs, workflows) does not
# warrant a ruff + mypy run at the end of the turn.
WATCHED = ("src/", "tests/")


def venv_python() -> Path | None:
    """
    Find the ``.venv`` Python (Windows or Unix).

    Returns:
        Path | None: The interpreter, or None if the ``.venv`` does not exist yet.
    """
    for rel in ("Scripts/python.exe", "bin/python"):
        candidate = PROJECT_ROOT / ".venv" / rel
        if candidate.exists():
            return candidate
    return None


def has_python_changes() -> bool:
    """
    Tell whether a ``.py`` file under src/ or tests/ differs from HEAD.

    Returns:
        bool: True if one does, or if git is unavailable (validates to be safe).
    """
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        ).stdout
    except Exception:
        return True

    for line in out.splitlines():
        name = line[3:].strip()
        if name.endswith(".py") and name.startswith(WATCHED):
            return True
    return False


def run(py: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    """
    Run ``python -m <args>`` from the project root.

    Args:
        py (Path): The ``.venv`` interpreter.
        args (list[str]): The module and its arguments.

    Returns:
        subprocess.CompletedProcess[str]: The finished process, output captured as text.
    """
    return subprocess.run(
        [str(py), "-m", *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )


def main() -> None:
    """Validate the project and exit with 2 when ruff or mypy fail."""
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}

    py = venv_python()
    if py is None:
        return  # no venv: do not block
    if not has_python_changes():
        return  # no .py changed: nothing to validate

    problems: list[str] = []
    ruff = run(py, ["ruff", "check", "."])
    if ruff.returncode != 0:
        problems.append("RUFF:\n" + (ruff.stdout or "") + (ruff.stderr or ""))
    mypy = run(py, ["mypy"])
    if mypy.returncode != 0:
        problems.append("MYPY:\n" + (mypy.stdout or "") + (mypy.stderr or ""))

    if not problems:
        return

    report = "\n\n".join(problems)
    if data.get("stop_hook_active"):
        sys.stderr.write("Warning: quality checks still fail after the fix:\n\n" + report)
        return  # avoid an infinite loop
    sys.stderr.write("Quality checks failed. Fix them before finishing:\n\n" + report)
    sys.exit(2)


if __name__ == "__main__":
    main()
