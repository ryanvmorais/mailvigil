"""
What the command line modules share: the exit codes and the two ways of printing.

``cli.py`` wires ``summary`` and ``verdict`` and assembles the parser; ``cli_fetch.py`` holds the
``fetch`` command. Both need the exit codes and the printing helpers, and neither may import the
other, so they live here. ``cli`` imports what it uses and the exit codes stay one table (spec 006
RF-04).
"""

from __future__ import annotations

from pathlib import Path
from typing import TextIO

from mailvigil.text import clean_text

# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------

# Exit codes, the contract of spec 006 (RF-04): 0 is "an answer was printed", not "healthy".
# This is the one table; the README lists the same eight and a test compares the two. Changing a
# value is a breaking change.
EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_USAGE = 2
# Only ``verdict`` returns these two: a script must tell "wait" from "no" without parsing text
# (spec 005 ADR-6).
EXIT_TOO_EARLY = 3
EXIT_NOT_READY = 4
# A bug and the two ways a run is cut short (spec 006 amendment, 2026-10-29). A bug must not look
# like a refusal (1), so it takes ``EX_SOFTWARE`` of ``sysexits.h``; the other two are the shell
# convention of 128 plus the signal (SIGINT 2, SIGPIPE 13).
EXIT_INTERNAL = 70
EXIT_INTERRUPTED = 130
EXIT_PIPE_CLOSED = 141

# ---------------------------------------------------------------------------
# Printing
# ---------------------------------------------------------------------------


# Longest path or domain echoed in a refusal line; it comes from the command line, not a report.
_MAX_ECHO = 200


def echo(value: str | Path) -> str:
    """
    Make a value from the command line safe to print.

    Args:
        value (str | Path): A path or a domain as the user typed it.

    Returns:
        str: The text cleaned of control and format characters, and cut.
    """
    return clean_text(str(value), _MAX_ECHO)


def write(stream: TextIO, text: str) -> None:
    """
    Write a text and a newline, whatever the stream can encode.

    The text is encoded with the stream's own encoding and ``errors="replace"`` and decoded back, so
    a character a legacy console cannot show becomes ``?`` instead of raising halfway through the
    output. Reconfiguring ``sys.stdout`` would change the whole process, which a test or a wrapper
    calling ``main`` should not suffer.

    Args:
        stream (TextIO): Standard output or standard error.
        text (str): The text, without a trailing newline.
    """
    encoding = getattr(stream, "encoding", None) or "utf-8"
    stream.write(text.encode(encoding, errors="replace").decode(encoding) + "\n")
