"""
Command-line entry point of MailVigil.

The ``summary`` command wires three calls: ``ingest`` reads the reports, ``summarize`` adds them up
and ``render_summary`` writes the text. This module counts nothing and lays nothing out; it decides
where the domain and the configuration come from (RF-08) and turns every refusal into one line on
standard error and an exit code (RF-10).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from types import MappingProxyType
from typing import TextIO

from mailvigil import __version__
from mailvigil.config import Config, ConfigError, check_domain, load_config
from mailvigil.render import no_reports_message, render_summary
from mailvigil.reports import ingest
from mailvigil.summary import summarize
from mailvigil.text import clean_text

# The file read from the current folder when --config is not given (Resolved decision 10).
DEFAULT_CONFIG = Path("mailvigil.toml")

# Exit codes, provisional until spec 006 (RF-10): 0 is "an answer was printed", not "healthy".
EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_USAGE = 2

# Longest path or domain echoed in a refusal line; it comes from the command line, not a report.
_MAX_ECHO = 200

# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


class _Refusal(Exception):
    """
    A run that cannot start: the message is the one line printed to standard error.

    Attributes:
        message (str): The line, without the program name or a trailing newline.
    """

    def __init__(self, message: str) -> None:
        """
        Build a refusal.

        Args:
            message (str): The line to print.
        """
        super().__init__(message)
        self.message = message


def _echo(value: str | Path) -> str:
    """
    Make a value from the command line safe to print.

    Args:
        value (str | Path): A path or a domain as the user typed it.

    Returns:
        str: The text cleaned of control and format characters, and cut.
    """
    return clean_text(str(value), _MAX_ECHO)


# ---------------------------------------------------------------------------
# Domain and configuration (RF-08)
# ---------------------------------------------------------------------------


def resolve_config(config_path: Path | None, domain: str | None) -> tuple[Config, str | None]:
    """
    Decide the domain and the selector map of a run.

    The order is fixed: the ``--domain`` value is validated first, then the file is chosen
    (``--config``, else ``mailvigil.toml`` in the current folder; no parent and no home directory is
    searched), then the two are compared. With no file the selector map is empty, which is a
    legitimate first run.

    Args:
        config_path (Path | None): The ``--config`` value, ``None`` when not given.
        domain (str | None): The ``--domain`` value, ``None`` when not given.

    Returns:
        tuple[Config, str | None]: The configuration and the path of the file used as it should be
            shown, ``None`` when there is no file.

    Raises:
        _Refusal: For an invalid or conflicting domain, a refused file, or no domain at all.
    """
    wanted: str | None = None
    if domain is not None:
        try:
            wanted = check_domain(domain, key="--domain")
        except ConfigError as error:
            raise _Refusal(str(error)) from error

    # ``exists``, not ``is_file``: a folder with that name is refused as unreadable by the loader
    # instead of being silently ignored.
    path = (
        config_path
        if config_path is not None
        else (DEFAULT_CONFIG if DEFAULT_CONFIG.exists() else None)
    )

    if path is None:
        if wanted is None:
            raise _Refusal("pass --domain or --config (or put a mailvigil.toml in this folder)")
        return Config(wanted, MappingProxyType({})), None

    try:
        config = load_config(path)
    except ConfigError as error:
        raise _Refusal(f"{_echo(path)}: {error}") from error
    if wanted is not None and wanted != config.domain:
        raise _Refusal(
            f"--domain {wanted} does not match the domain {config.domain} of {_echo(path)}"
        )
    return config, str(path)


# ---------------------------------------------------------------------------
# Writing (ADR-4)
# ---------------------------------------------------------------------------


def _write(stream: TextIO, text: str) -> None:
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


# ---------------------------------------------------------------------------
# Parser and entry point
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """
    Build the argument parser of the ``mailvigil`` command.

    The subcommand is optional at the parser level, so that ``main`` decides what a missing one
    means.

    Returns:
        argparse.ArgumentParser: The parser, with ``--version`` and the ``summary`` subcommand.
    """
    parser = argparse.ArgumentParser(
        prog="mailvigil",
        description="Reads DMARC aggregate reports and says if it is safe to move to p=reject.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")

    summary = commands.add_parser(
        "summary",
        help="say who sends mail as the domain, from DMARC aggregate reports",
        description="Sum up DMARC aggregate reports per sender and per situation.",
    )
    summary.add_argument(
        "paths", nargs="+", type=Path, metavar="PATH", help="report files or folders of reports"
    )
    summary.add_argument(
        "--config",
        type=Path,
        metavar="FILE",
        help="TOML file with the domain and the selector map "
        f"(default: {DEFAULT_CONFIG} in the current folder, if there is one)",
    )
    summary.add_argument(
        "--domain",
        metavar="DOMAIN",
        help="the domain the reports are about (required when there is no configuration file)",
    )
    return parser


def _run_summary(args: argparse.Namespace) -> int:
    """
    Run the ``summary`` command: resolve, ingest, summarize, print.

    Args:
        args (argparse.Namespace): The parsed arguments: ``paths``, ``config`` and ``domain``.

    Returns:
        int: ``EXIT_OK`` when the summary was printed, ``EXIT_REFUSED`` when it could not be made.
    """
    try:
        config, source = resolve_config(args.config, args.domain)
    except _Refusal as refusal:
        _write(sys.stderr, f"mailvigil: {refusal.message}")
        return EXIT_REFUSED

    result = ingest(args.paths, config.domain)
    if not result.reports:
        _write(sys.stderr, no_reports_message(result, config.domain))
        return EXIT_REFUSED

    _write(sys.stdout, render_summary(summarize(result, config), source))
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    """
    Run the ``mailvigil`` command.

    Args:
        argv (Sequence[str] | None): Arguments without the program name; ``None`` reads
            ``sys.argv``.

    Returns:
        int: The process exit code. A usage error or ``--version`` ends the process through
            ``SystemExit``, as argparse does.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "summary":
        return _run_summary(args)
    parser.print_help(sys.stderr)
    return EXIT_USAGE
