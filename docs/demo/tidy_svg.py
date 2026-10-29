"""
Pin the text of the recording's SVG to its character grid.

``svg-term`` places each run of text at a column but lets the browser space the letters, so a
monospace font whose glyphs are narrower or wider than the 0.6 em the tool assumes (Consolas is
0.55 em) shows words with gaps that do not line up. This script gives every ``<text>`` element a
``textLength`` of one cell per character, so any monospace font fills the same grid, and puts the
fonts that match 0.6 em first in the stack. Run it on the SVG that ``svg-term`` wrote:

    uv run python docs/demo/tidy_svg.py docs/images/mailvigil-dmarc-verdict-terminal-demo.svg
"""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


#: The fonts of the page, those closest to 0.6 em first; ``svg-term`` writes Monaco and Consolas.
FONT_STACK = (
    "SFMono-Regular,Menlo,'DejaVu Sans Mono','Liberation Mono','Cascadia Mono',Consolas,monospace"
)

#: A text element with its attributes and its (already escaped) content.
TEXT = re.compile(r"<text([^>]*)>([^<]+)</text>")

#: The font-family attribute that ``svg-term`` puts on the group around every line.
FONT_FAMILY = re.compile(r'font-family="[^"]*"')


# ---------------------------------------------------------------------------
# Rewrite
# ---------------------------------------------------------------------------


def _pin(match: re.Match[str]) -> str:
    """
    Add the grid width to one text element.

    Args:
        match (re.Match[str]): A ``<text>`` element found by ``TEXT``.

    Returns:
        str: The same element with ``textLength`` and ``lengthAdjust`` set.
    """
    attributes, content = match.groups()
    cells = len(html.unescape(content))
    return f'<text{attributes} textLength="{cells}" lengthAdjust="spacing">{content}</text>'


def tidy(svg: str) -> str:
    """
    Pin every text run of the SVG to the grid and replace its font stack.

    Args:
        svg (str): The SVG written by ``svg-term``.

    Returns:
        str: The SVG with the fixed spacing.
    """
    svg = FONT_FAMILY.sub(f'font-family="{FONT_STACK}"', svg)
    return TEXT.sub(_pin, svg)


def main() -> None:
    """Rewrite the SVG named on the command line in place."""
    path = Path(sys.argv[1])
    path.write_text(tidy(path.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")
    print(f"tidied {path}")


if __name__ == "__main__":
    main()
