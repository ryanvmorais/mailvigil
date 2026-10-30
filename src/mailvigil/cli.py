"""
Command-line entry point of MailVigil.

The ``summary`` command wires three calls: ``ingest`` reads the reports, ``summarize`` adds them up
and ``render_summary`` writes the text, in the language of ``--lang``, or ``summary_document`` and
``dumps`` write the JSON with ``--json``, which has no language. The ``verdict`` command shares
everything up to the ``Summary`` and then calls ``judge`` and ``render_verdict`` (or
``verdict_document``, or ``render_html`` with ``--html``, the page of spec 008). This module
counts nothing, judges nothing and lays nothing out; it
decides where the domain and the configuration come from (RF-08) and turns every refusal, and
every answer, into an exit code. The exit codes are a contract (spec 006 RF-04): the code is
decided before the format and the language, so neither ``--json`` nor ``--lang`` can change it.

The ``fetch`` command (spec 009), the one that uses the network, lives in ``cli_fetch``; this
module only adds its subparser and dispatches to ``run_fetch``. The adapter that imports
``imaplib`` and ``ssl`` is loaded inside ``run_fetch`` only, so ``summary`` and ``verdict`` never
load it (RF-09). The exit codes and the printing helpers are in ``cli_common``.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
import tempfile
import traceback
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType

from mailvigil import __version__
from mailvigil.cli_common import (
    EXIT_INTERNAL,
    EXIT_INTERRUPTED,
    EXIT_NOT_READY,
    EXIT_OK,
    EXIT_PIPE_CLOSED,
    EXIT_REFUSED,
    EXIT_TOO_EARLY,
    EXIT_USAGE,
    config_line,
    echo,
    write,
)
from mailvigil.cli_fetch import add_fetch_parser, run_fetch
from mailvigil.config import Config, ConfigError, check_domain, load_config
from mailvigil.messages import ENGLISH, Messages, language_by_code
from mailvigil.render import no_reports_message, render_summary
from mailvigil.render_html import render_html
from mailvigil.render_json import dumps, summary_document, verdict_document
from mailvigil.render_verdict import render_verdict
from mailvigil.reports import IngestionResult, ingest
from mailvigil.summary import summarize
from mailvigil.verdict import Answer, judge

# The file read from the current folder when --config is not given (Resolved decision 10).
DEFAULT_CONFIG = Path("mailvigil.toml")

# Where the line of an internal error sends the reader.
_ISSUES_URL = "https://github.com/ryanvmorais/mailvigil/issues"

# The one place an answer becomes an exit code (spec 005 ADR-6).
_VERDICT_EXIT = {
    Answer.READY: EXIT_OK,
    Answer.TOO_EARLY: EXIT_TOO_EARLY,
    Answer.NOT_READY: EXIT_NOT_READY,
}

# The codes ``--lang`` accepts, as the help writes them; the lookup folds the case (RF-06).
_LANGUAGE_CODES = ("en", "pt-BR")

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


# ---------------------------------------------------------------------------
# Domain and configuration (RF-08)
# ---------------------------------------------------------------------------


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
            raise _Refusal(config_line(error, messages)) from error

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
        raise _Refusal(f"{echo(path)}: {config_line(error, messages)}") from error
    if wanted is not None and wanted != config.domain:
        raise _Refusal(
            messages.refusals.domain_mismatch.format(
                wanted=wanted, domain=config.domain, path=echo(path)
            )
        )
    return config, str(path)


# ---------------------------------------------------------------------------
# Writing (ADR-4)
# ---------------------------------------------------------------------------


def _now() -> datetime:
    """
    Read the clock, the one place the run does.

    Returns:
        datetime: The current moment, timezone-aware (UTC). Tests replace this function.
    """
    return datetime.now(UTC)


def _write_page(path: Path, page: str) -> None:
    """
    Write the HTML page to a file as ASCII bytes, replacing what is there (spec 008, ADR-11).

    The bytes go straight to the file, so no shell, console or code page sits in between. They are
    written to a temporary file in the same folder and moved over ``path`` with ``os.replace``,
    which is atomic: a failure never leaves half a page, and an old file survives it. The folder is
    never created.

    Args:
        path (Path): The file to write.
        page (str): The page; ``render_html`` makes it ASCII, and it ends in a newline.

    Raises:
        OSError: When the folder is missing, ``path`` is a folder or the disk refuses the write;
            the temporary file is removed.
    """
    temporary: str | None = None
    try:
        fd, temporary = tempfile.mkstemp(prefix=".mailvigil-", suffix=".tmp", dir=path.parent)
        with os.fdopen(fd, "wb") as handle:
            handle.write(page.encode("ascii"))
        # ``mkstemp`` makes the file private (0600); a report is made to be read, like the file of
        # a ``>`` redirect, so it gets the permission the umask allows. ``umask`` can only be read
        # by setting it, so it is put back at once.
        umask = os.umask(0)
        os.umask(umask)
        os.chmod(temporary, 0o666 & ~umask)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            with contextlib.suppress(OSError):
                os.unlink(temporary)


# ---------------------------------------------------------------------------
# Parser and entry point
# ---------------------------------------------------------------------------


def _language(code: str) -> Messages:
    """
    Turn the ``--lang`` value into the catalog of that language.

    Args:
        code (str): The code as the user typed it, in any case.

    Returns:
        Messages: The catalog.

    Raises:
        argparse.ArgumentTypeError: For a code that is not one of ``_LANGUAGE_CODES``, so argparse
            ends the run with its usage error and code ``EXIT_USAGE``.
    """
    try:
        return language_by_code(code)
    except ValueError:
        choices = ", ".join(_LANGUAGE_CODES)
        raise argparse.ArgumentTypeError(
            f"invalid language {echo(code)!r} (choose from {choices})"
        ) from None


def build_parser() -> argparse.ArgumentParser:
    """
    Build the argument parser of the ``mailvigil`` command.

    The subcommand is optional at the parser level, so that ``main`` decides what a missing one
    means. ``summary`` and ``verdict`` take what they read and the language from two parent parsers,
    in that order; ``fetch`` takes the language only, so it shares no option with the reading
    commands (spec 009, ADR-7).

    Returns:
        argparse.ArgumentParser: The parser, with ``--version`` and the ``summary``, ``verdict``
            and ``fetch`` subcommands.
    """
    parser = argparse.ArgumentParser(
        prog="mailvigil",
        description="Reads DMARC aggregate reports and says if it is safe to move to p=reject.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    reading = argparse.ArgumentParser(add_help=False)
    reading.add_argument(
        "paths",
        nargs="+",
        type=Path,
        metavar="PATH",
        help="report files (.xml .gz .zip), mail files (.eml .mbox) or folders of them",
    )
    reading.add_argument(
        "--config",
        type=Path,
        metavar="FILE",
        help="TOML file with the domain and the selector map "
        f"(default: {DEFAULT_CONFIG} in the current folder, if there is one)",
    )
    reading.add_argument(
        "--domain",
        metavar="DOMAIN",
        help="the domain the reports are about (required when there is no configuration file)",
    )
    reading.add_argument(
        "--recursive",
        action="store_true",
        help="also search the subfolders of each folder (up to 8 levels, links not followed)",
    )
    reading.add_argument(
        "--json",
        action="store_true",
        help="print one JSON document instead of the text (see docs/json-schema.md)",
    )
    language = argparse.ArgumentParser(add_help=False)
    language.add_argument(
        "--lang",
        type=_language,
        default=ENGLISH,
        metavar="{" + ",".join(_LANGUAGE_CODES) + "}",
        help="language of the text and of the refusal lines (default: en); the JSON has none",
    )

    commands = parser.add_subparsers(dest="command", metavar="COMMAND")
    commands.add_parser(
        "summary",
        parents=[reading, language],
        help="say who sends mail as the domain, from DMARC aggregate reports",
        description="Sum up DMARC aggregate reports per sender and per situation.",
    )
    verdict_parser = commands.add_parser(
        "verdict",
        parents=[reading, language],
        help="say if the domain is ready for p=reject, and why",
        description="Say if the domain is ready for p=reject, from DMARC aggregate reports. "
        f"The exit code is {EXIT_OK} for ready, {EXIT_TOO_EARLY} for too early and "
        f"{EXIT_NOT_READY} for not ready.",
    )
    verdict_parser.add_argument(
        "--html",
        action="store_true",
        help="print one self-contained HTML page instead of the text; redirect it to a file "
        "(mailvigil verdict ... --html > report.html) or write it with --output; not with --json",
    )
    verdict_parser.add_argument(
        "--output",
        type=Path,
        metavar="FILE",
        help="write the --html page to FILE as ASCII, replacing it, instead of printing it "
        "(use it in Windows PowerShell 5.1, whose > writes UTF-16); requires --html",
    )
    add_fetch_parser(commands, language)
    return parser


def _load(
    args: argparse.Namespace, messages: Messages = ENGLISH
) -> tuple[Config, str | None, IngestionResult] | None:
    """
    Resolve the configuration and read the reports, the part both commands share.

    Args:
        args (argparse.Namespace): The parsed arguments: ``paths``, ``config``, ``domain``,
            ``json`` and ``lang``.
        messages (Messages, optional): The language of the refusal lines. Default: English.

    Returns:
        tuple[Config, str | None, IngestionResult] | None: The configuration, the path of the file
            used as it should be shown and what was read; ``None`` when the run was refused, after
            the one line on standard error.
    """
    try:
        config, source = resolve_config(args.config, args.domain, messages)
    except _Refusal as refusal:
        write(sys.stderr, f"mailvigil: {refusal.message}")
        return None

    result = ingest(args.paths, config.domain, _now(), args.recursive)
    if not result.reports:
        write(sys.stderr, no_reports_message(result, config.domain, messages))
        return None
    return config, source, result


def _run_summary(args: argparse.Namespace) -> int:
    """
    Run the ``summary`` command: resolve, ingest, summarize, print.

    Args:
        args (argparse.Namespace): The parsed arguments: ``paths``, ``config``, ``domain``,
            ``json`` and ``lang``.

    Returns:
        int: ``EXIT_OK`` when the summary was printed, ``EXIT_REFUSED`` when it could not be made.
    """
    loaded = _load(args, args.lang)
    if loaded is None:
        return EXIT_REFUSED
    config, source, result = loaded

    summary = summarize(result, config)
    if args.json:
        write(sys.stdout, dumps(summary_document(summary, source)))
    else:
        write(sys.stdout, render_summary(summary, source, args.lang))
    return EXIT_OK


def _run_verdict(args: argparse.Namespace) -> int:
    """
    Run the ``verdict`` command: resolve, ingest, summarize, judge, print.

    Args:
        args (argparse.Namespace): The parsed arguments: ``paths``, ``config``, ``domain``,
            ``json``, ``html`` and ``lang``.

    Returns:
        int: ``EXIT_OK`` for ready, ``EXIT_TOO_EARLY`` for too early, ``EXIT_NOT_READY`` for not
            ready and ``EXIT_REFUSED`` when no verdict could be made.
    """
    loaded = _load(args, args.lang)
    if loaded is None:
        return EXIT_REFUSED
    config, _source, result = loaded

    summary = summarize(result, config)
    verdict = judge(summary, _now())
    if args.json:
        write(sys.stdout, dumps(verdict_document(verdict)))
    elif args.html and args.output is not None:
        try:
            _write_page(args.output, render_html(summary, verdict, args.lang))
        except OSError as error:
            reason = error.strerror or type(error).__name__
            line = args.lang.refusals.output_failed.format(
                path=echo(args.output), reason=echo(reason)
            )
            write(sys.stderr, f"mailvigil: {line}")
            return EXIT_REFUSED
    elif args.html:
        # ``render_html`` ends in a newline already; ``_write`` adds one, so the last is cut.
        write(sys.stdout, render_html(summary, verdict, args.lang).rstrip("\n"))
    else:
        write(sys.stdout, render_verdict(verdict, args.lang))
    return _VERDICT_EXIT[verdict.answer]


def _internal_error_line(error: Exception) -> str:
    """
    Write the one line of an internal error.

    It names the exception class and the file and line where it was raised, never the exception's
    message: the message may carry text from a report, and the line is meant to be pasted into an
    issue.

    Args:
        error (Exception): The exception that escaped the command.

    Returns:
        str: The line, without a trailing newline.
    """
    frames = traceback.extract_tb(error.__traceback__)
    where = f" at {Path(frames[-1].filename).name}:{frames[-1].lineno}" if frames else ""
    return (
        f"mailvigil: internal error ({type(error).__name__}{where}). "
        f"This is a bug; please report it at {_ISSUES_URL}"
    )


def _silence_stdout() -> None:
    """
    Point standard output at the null device after a closed pipe.

    Without it the interpreter tries to flush the broken stream on exit and prints a second error.
    A stream with no file descriptor (a test, a wrapper) is left as it is.
    """
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
    except (OSError, ValueError):
        pass


def _dispatch(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """
    Run the command the arguments name.

    Args:
        args (argparse.Namespace): The parsed arguments.
        parser (argparse.ArgumentParser): Used to end the run with a usage error.

    Returns:
        int: The exit code of the command.
    """
    # A run has one format; argparse cannot make a group across a parent parser and a subparser's
    # own argument, so the pair is refused here, before any work (ADR-6).
    if args.command == "verdict" and args.json and args.html:
        parser.error("argument --html: not allowed with argument --json")
    # The file is the page's: the text and the JSON stay redirects (spec 008, ADR-11).
    if args.command == "verdict" and args.output is not None and not args.html:
        parser.error("argument --output: requires --html")
    if args.command == "summary":
        return _run_summary(args)
    if args.command == "verdict":
        return _run_verdict(args)
    if args.command == "fetch":
        return run_fetch(args, parser)
    parser.print_help(sys.stderr)
    return EXIT_USAGE


def main(argv: Sequence[str] | None = None) -> int:
    """
    Run the ``mailvigil`` command.

    Nothing escapes as a traceback: a bug ends as ``EXIT_INTERNAL`` after one line on standard
    error, Ctrl+C as ``EXIT_INTERRUPTED`` and a closed output pipe (``mailvigil ... | head``) as
    ``EXIT_PIPE_CLOSED``, both without a word. The line of a bug stays in English, as the usage
    errors of argparse do.

    Args:
        argv (Sequence[str] | None): Arguments without the program name; ``None`` reads
            ``sys.argv``.

    Returns:
        int: The process exit code. A usage error or ``--version`` ends the process through
            ``SystemExit``, as argparse does.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return _dispatch(args, parser)
    except KeyboardInterrupt:
        return EXIT_INTERRUPTED
    except BrokenPipeError:
        _silence_stdout()
        return EXIT_PIPE_CLOSED
    except Exception as error:  # the one catch-all: a bug must not look like a refusal
        write(sys.stderr, _internal_error_line(error))
        return EXIT_INTERNAL
