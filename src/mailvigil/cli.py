"""
Command-line entry point of MailVigil.

Only the skeleton exists for now: the parser answers ``--version``. The real commands arrive with
the specs under ``specs/``.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from mailvigil import __version__


def build_parser() -> argparse.ArgumentParser:
    """
    Build the argument parser of the ``mailvigil`` command.

    Returns:
        argparse.ArgumentParser: The parser, with ``--version`` registered.
    """
    parser = argparse.ArgumentParser(
        prog="mailvigil",
        description="Reads DMARC aggregate reports and says if it is safe to move to p=reject.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """
    Run the ``mailvigil`` command.

    Args:
        argv (Sequence[str] | None): Arguments without the program name; ``None`` reads
            ``sys.argv``.

    Returns:
        int: The process exit code.
    """
    build_parser().parse_args(argv)
    return 0
