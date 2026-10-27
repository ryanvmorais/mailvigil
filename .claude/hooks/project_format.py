"""
PostToolUse hook (project scope) — layer 1: the project's single formatter.

Runs on the file that was just written or edited:
    .py  -> ruff check --fix + black   (from the uv-managed ``.venv``)

Cross-platform: finds the ``.venv`` Python on Windows (Scripts/python.exe) and on Unix
(bin/python). While the ``.venv`` does not exist, it does nothing. It never blocks (always exits
with 0).

Claude Code sends the event as JSON on stdin:
    { "tool_input": { "file_path": "/absolute/path/to/file.ext" } }
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

# <root>/.claude/hooks/project_format.py  ->  <root>
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


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


def format_python(path: Path) -> None:
    """
    Apply ruff's safe fixes and black to one Python file.

    Args:
        path (Path): The file to format.
    """
    py = venv_python()
    if py is None:
        return
    subprocess.run([str(py), "-m", "ruff", "check", "--fix", str(path)], capture_output=True)
    subprocess.run([str(py), "-m", "black", str(path)], capture_output=True)


def main() -> None:
    """Read the tool event from stdin and format the file it touched."""
    try:
        data = json.load(sys.stdin)
    except Exception:
        return

    file_path = data.get("tool_input", {}).get("file_path")
    if not file_path:
        return

    path = Path(file_path)
    if path.exists() and path.suffix.lower() == ".py":
        format_python(path)


if __name__ == "__main__":
    main()
