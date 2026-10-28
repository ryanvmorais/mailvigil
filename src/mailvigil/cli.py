"""
Command-line entry point of MailVigil.

The ``summary`` command wires three calls: ``ingest`` reads the reports, ``summarize`` adds them up
and ``render_summary`` writes the text, or ``summary_document`` and ``dumps`` write the JSON with
``--json``. The ``verdict`` command shares everything up to the ``Summary`` and then calls ``judge``
and ``render_verdict`` (or ``verdict_document``). This module counts nothing, judges nothing and
lays nothing out; it decides where the domain and the configuration come from (RF-08) and turns
every refusal, and every answer, into an exit code. The exit codes are a contract (spec 006 RF-04):
the code is decided before the format, so ``--json`` cannot change it.
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
from mailvigil.messages import ENGLISH, Messages
from mailvigil.render import no_reports_message, render_summary
from mailvigil.render_json import dumps, summary_document, verdict_document
from mailvigil.render_verdict import render_verdict
from mailvigil.reports import IngestionResult, ingest
from mailvigil.summary import summarize
from mailvigil.text import clean_text
from mailvigil.verdict import Answer, judge

# The file read from the current folder when --config is not given (Resolved decision 10).
DEFAULT_CONFIG = Path("mailvigil.toml")

# Exit codes, the contract of spec 006 (RF-04): 0 is "an answer was printed", not "healthy".
# This is the one table; the README lists the same five and a test compares the two. Changing a
# value is a breaking change.
EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_USAGE = 2
# Only ``verdict`` returns these two: a script must tell "wait" from "no" without parsing text
# (spec 005 ADR-6).
EXIT_TOO_EARLY = 3
EXIT_NOT_READY = 4

# The one place an answer becomes an exit code (spec 005 ADR-6).
_VERDICT_EXIT = {
    Answer.READY: EXIT_OK,
    Answer.TOO_EARLY: EXIT_TOO_EARLY,
    Answer.NOT_READY: EXIT_NOT_READY,
}

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


def _config_line(error: ConfigError, messages: Messages) -> str:
    """
    Write the line of a refused configuration or ``--domain`` value.

    The phrase of the reason, then the key, then the detail only for the reasons the language keeps
    it for: ``config.py`` writes the detail in English, so a translation drops it where the reason
    already says what it said (ADR-5). In English every reason keeps it, so the line is what
    ``str(error)`` has always been.

    Args:
        error (ConfigError): The refusal.
        messages (Messages): The language.

    Returns:
        str: The line, without the path it concerns.
    """
    refusals = messages.refusals
    line = refusals.config_reasons[error.reason]
    if error.key:
        line += f" [{error.key}]"
    if error.detail and error.reason in refusals.config_detail:
        line += f": {error.detail}"
    return line


def resolve_config(
    config_path: Path | None, domain: str | None, messages: Messages = ENGLISH
) -> tuple[Config, str | None]:
    """
    Decide the domain and the selector map of a run.

    The order is fixed: the ``--domain`` value is validated first, then the file is chosen
    (``--config``, else ``mailvigil.toml`` in the current folder; no parent and no home directory is
    searched), then the two are compared. With no file the selector map is empty, which is a
    legitimate first run.

    Args:
        config_path (Path | None): The ``--config`` value, ``None`` when not given.
        domain (str | None): The ``--domain`` value, ``None`` when not given.
        messages (Messages, optional): The language of the refusal lines. Default: English.

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
            raise _Refusal(_config_line(error, messages)) from error

    # ``exists``, not ``is_file``: a folder with that name is refused as unreadable by the loader
    # instead of being silently ignored.
    path = (
        config_path
        if config_path is not None
        else (DEFAULT_CONFIG if DEFAULT_CONFIG.exists() else None)
    )

    if path is None:
        if wanted is None:
            raise _Refusal(messages.refusals.no_domain.format(default=DEFAULT_CONFIG))
        return Config(wanted, MappingProxyType({})), None

    try:
        config = load_config(path)
    except ConfigError as error:
        raise _Refusal(f"{_echo(path)}: {_config_line(error, messages)}") from error
    if wanted is not None and wanted != config.domain:
        raise _Refusal(
            messages.refusals.domain_mismatch.format(
                wanted=wanted, domain=config.domain, path=_echo(path)
            )
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
    means. ``summary`` and ``verdict`` take the same three arguments, defined once in a parent
    parser.

    Returns:
        argparse.ArgumentParser: The parser, with ``--version`` and the ``summary`` and ``verdict``
            subcommands.
    """
    parser = argparse.ArgumentParser(
        prog="mailvigil",
        description="Reads DMARC aggregate reports and says if it is safe to move to p=reject.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument(
        "paths", nargs="+", type=Path, metavar="PATH", help="report files or folders of reports"
    )
    shared.add_argument(
        "--config",
        type=Path,
        metavar="FILE",
        help="TOML file with the domain and the selector map "
        f"(default: {DEFAULT_CONFIG} in the current folder, if there is one)",
    )
    shared.add_argument(
        "--domain",
        metavar="DOMAIN",
        help="the domain the reports are about (required when there is no configuration file)",
    )
    shared.add_argument(
        "--json",
        action="store_true",
        help="print one JSON document instead of the text (see docs/json-schema.md)",
    )

    commands = parser.add_subparsers(dest="command", metavar="COMMAND")
    commands.add_parser(
        "summary",
        parents=[shared],
        help="say who sends mail as the domain, from DMARC aggregate reports",
        description="Sum up DMARC aggregate reports per sender and per situation.",
    )
    commands.add_parser(
        "verdict",
        parents=[shared],
        help="say if the domain is ready for p=reject, and why",
        description="Say if the domain is ready for p=reject, from DMARC aggregate reports. "
        f"The exit code is {EXIT_OK} for ready, {EXIT_TOO_EARLY} for too early and "
        f"{EXIT_NOT_READY} for not ready.",
    )
    return parser


def _load(
    args: argparse.Namespace, messages: Messages = ENGLISH
) -> tuple[Config, str | None, IngestionResult] | None:
    """
    Resolve the configuration and read the reports, the part both commands share.

    Args:
        args (argparse.Namespace): The parsed arguments: ``paths``, ``config``, ``domain`` and
            ``json``.
        messages (Messages, optional): The language of the refusal lines. Default: English.

    Returns:
        tuple[Config, str | None, IngestionResult] | None: The configuration, the path of the file
            used as it should be shown and what was read; ``None`` when the run was refused, after
            the one line on standard error.
    """
    try:
        config, source = resolve_config(args.config, args.domain, messages)
    except _Refusal as refusal:
        _write(sys.stderr, f"mailvigil: {refusal.message}")
        return None

    result = ingest(args.paths, config.domain)
    if not result.reports:
        _write(sys.stderr, no_reports_message(result, config.domain, messages))
        return None
    return config, source, result


def _run_summary(args: argparse.Namespace) -> int:
    """
    Run the ``summary`` command: resolve, ingest, summarize, print.

    Args:
        args (argparse.Namespace): The parsed arguments: ``paths``, ``config``, ``domain`` and
            ``json``.

    Returns:
        int: ``EXIT_OK`` when the summary was printed, ``EXIT_REFUSED`` when it could not be made.
    """
    loaded = _load(args)
    if loaded is None:
        return EXIT_REFUSED
    config, source, result = loaded

    summary = summarize(result, config)
    if args.json:
        _write(sys.stdout, dumps(summary_document(summary, source)))
    else:
        _write(sys.stdout, render_summary(summary, source))
    return EXIT_OK


def _run_verdict(args: argparse.Namespace) -> int:
    """
    Run the ``verdict`` command: resolve, ingest, summarize, judge, print.

    Args:
        args (argparse.Namespace): The parsed arguments: ``paths``, ``config``, ``domain`` and
            ``json``.

    Returns:
        int: ``EXIT_OK`` for ready, ``EXIT_TOO_EARLY`` for too early, ``EXIT_NOT_READY`` for not
            ready and ``EXIT_REFUSED`` when no verdict could be made.
    """
    loaded = _load(args)
    if loaded is None:
        return EXIT_REFUSED
    config, _source, result = loaded

    verdict = judge(summarize(result, config))
    if args.json:
        _write(sys.stdout, dumps(verdict_document(verdict)))
    else:
        _write(sys.stdout, render_verdict(verdict))
    return _VERDICT_EXIT[verdict.answer]


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
    if args.command == "verdict":
        return _run_verdict(args)
    parser.print_help(sys.stderr)
    return EXIT_USAGE
