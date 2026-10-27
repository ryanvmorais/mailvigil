"""
PreToolUse hook (project scope) — protects generated files.

Blocks a manual Edit/Write on files that tools GENERATE and that must never be edited by hand:
the next regeneration overwrites the edit or, for ``uv.lock``, corrupts the dependency graph.

Protected files and how to update them correctly:
    - uv.lock  -> uv lock / uv add / uv remove

On a violation it exits with code 2 and writes the guidance to stderr; Claude Code hands that back
to the agent, which then takes the right path instead of editing the file.
"""

from __future__ import annotations

import json
import sys

# Path suffixes that are protected (compared case-insensitively, with "/").
PROTECTED = {
    "uv.lock": "use uv lock / uv add / uv remove; never edit uv.lock by hand.",
}


def main() -> None:
    """Read the tool event from stdin and block edits to protected files."""
    try:
        data = json.load(sys.stdin)
    except Exception:
        return  # invalid input: do not block

    file_path = (data.get("tool_input") or {}).get("file_path", "")
    if not file_path:
        return

    normalized = file_path.replace("\\", "/").lower()
    for target, guidance in PROTECTED.items():
        if normalized.endswith(target):
            sys.stderr.write(f"Edit blocked: '{target}' is a generated file. {guidance}")
            sys.exit(2)


if __name__ == "__main__":
    main()
