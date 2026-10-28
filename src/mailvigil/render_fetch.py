"""
The text of ``fetch``: what a run did, and the line of a refused run (spec 009, RF-08).

Plain ASCII, at most 80 columns, with the words of a ``Messages`` catalog. It prints six numbers and
the folder and nothing from a message: no subject, sender or address. The folder is echoed through
``fit`` like every path the user typed, so a name with a control character or a bidirectional
override cannot reach the terminal. The module does no I/O: ``cli.py`` writes what it returns.
"""

from __future__ import annotations

from mailvigil.fetch.errors import FetchRefused
from mailvigil.fetch.model import FetchOutcome
from mailvigil.messages import ENGLISH, Messages
from mailvigil.render import fit

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Columns of one terminal line; every line of the text fits in it.
_WIDTH = 80
# The outcome lines hang under the title.
_INDENT = "  "

# ---------------------------------------------------------------------------
# The outcome
# ---------------------------------------------------------------------------


def render_fetch(outcome: FetchOutcome, directory: str, messages: Messages = ENGLISH) -> str:
    """
    Write what a finished run did.

    Args:
        outcome (FetchOutcome): The six numbers of the run.
        directory (str): The folder the messages were saved in, as the user typed it.
        messages (Messages, optional): The language. Default: English.

    Returns:
        str: The title, the six numbers and the folder, without a trailing newline.
    """
    words = messages.fetch
    rows = [
        (words.key_matched, outcome.matched),
        (words.key_saved, outcome.saved),
        (words.key_already, outcome.already),
        (words.key_too_large, outcome.too_large),
        (words.key_skipped, outcome.skipped),
        (words.key_left, outcome.left),
    ]
    # The labels are padded to the longest one; the numbers are right-aligned under each other.
    key_width = max(len(label) for label, _count in [*rows, (words.key_directory, 0)])
    number_width = max(len(str(count)) for _label, count in rows)
    lines = [fit(words.title, _WIDTH), ""]
    for label, count in rows:
        lines.append(f"{_INDENT}{label.ljust(key_width)} {str(count).rjust(number_width)}")
    prefix = f"{_INDENT}{words.key_directory.ljust(key_width)} "
    lines.append(prefix + fit(directory, _WIDTH - len(prefix)))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The refusal
# ---------------------------------------------------------------------------


def refusal_line(error: FetchRefused, messages: Messages = ENGLISH) -> str:
    """
    Write the lines of a refused run, for standard error.

    The phrase of the reason, then the detail when there is one (``FetchRefused`` has already
    cleaned it). When the run had saved some files before it stopped, a second line says how many,
    because those files are valid.

    Args:
        error (FetchRefused): The refusal.
        messages (Messages, optional): The language. Default: English.

    Returns:
        str: ``mailvigil: <phrase>[: <detail>]``, then the saved count when it is above zero,
            without a trailing newline.
    """
    words = messages.fetch
    line = f"mailvigil: {words.reasons[error.reason]}"
    if error.detail:
        line += f": {error.detail}"
    if error.outcome is not None and error.outcome.saved > 0:
        line += "\n" + words.saved_before_stop.of(error.outcome.saved)
    return line
