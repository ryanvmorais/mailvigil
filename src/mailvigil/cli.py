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
from mailvigil.config import (
    MAX_DOMAINS,
    Config,
    ConfigError,
    ConfigReason,
    check_domain,
    load_configs,
)
from mailvigil.messages import ENGLISH, Messages, language_by_code
from mailvigil.render import join_blocks, no_reports_message, render_summary
from mailvigil.render_html import render_html
from mailvigil.render_json import (
    dumps,
    summaries_document,
    summary_document,
    verdict_document,
    verdicts_document,
)
from mailvigil.render_verdict import render_tally, render_verdict
from mailvigil.reports import IngestionResult, ingest_many
from mailvigil.summary import summarize
from mailvigil.verdict import Answer, judge, worst_answer

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


def resolve_configs(
    config_path: Path | None, domains: Sequence[str] | None, messages: Messages = ENGLISH
) -> tuple[tuple[Config, ...], str | None]:
    """
    Decide the domains and the selector maps of a run (spec 010, ADR-9).

    The order is fixed: every ``--domain`` value is validated first, then the file is chosen
    (``--config``, else ``mailvigil.toml`` in the current folder; no parent and no home directory is
    searched), then the two are compared. ``--domain`` selects: with a file it narrows the run to
    the listed domains of the file, in the order of the file, and a value the file does not have is
    refused. With no file each distinct value is a domain with an empty selector map, which is a
    legitimate first run, in the order given.

    Args:
        config_path (Path | None): The ``--config`` value, ``None`` when not given.
        domains (Sequence[str] | None): The ``--domain`` values, ``None`` when not given.
        messages (Messages, optional): The language of the refusal lines. Default: English.

    Returns:
        tuple[tuple[Config, ...], str | None]: One configuration per domain of the run, and the path
            of the file used as it should be shown, ``None`` when there is no file.

    Raises:
        _Refusal: For an invalid, conflicting or too many ``--domain`` values, a refused file, or no
            domain at all.
    """
    wanted: list[str] = []
    try:
        for value in domains or ():
            name = check_domain(value, key="--domain")
            if name not in wanted:
                wanted.append(name)
        if len(wanted) > MAX_DOMAINS:
            raise ConfigError(
                ConfigReason.TOO_MANY_DOMAINS, "--domain", f"more than {MAX_DOMAINS} domains"
            )
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
        if not wanted:
            raise _Refusal(messages.refusals.no_domain.format(default=DEFAULT_CONFIG))
        return tuple(Config(name, MappingProxyType({})) for name in wanted), None

    try:
        configs = load_configs(path)
    except ConfigError as error:
        raise _Refusal(f"{echo(path)}: {config_line(error, messages)}") from error
    if not wanted:
        return configs, str(path)
    listed = {config.domain for config in configs}
    for name in wanted:
        if name in listed:
            continue
        # A file of one domain keeps the sentence it always had; the list is for several.
        if len(configs) == 1:
            raise _Refusal(
                messages.refusals.domain_mismatch.format(
                    wanted=name, domain=configs[0].domain, path=echo(path)
                )
            )
        raise _Refusal(messages.refusals.domain_not_listed.format(wanted=name, path=echo(path)))
    return tuple(config for config in configs if config.domain in wanted), str(path)


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


def _top(text: str) -> int:
    """
    Turn the ``--top`` value into a count of list entries.

    Args:
        text (str): The value as the user typed it.

    Returns:
        int: A whole number of 1 or more.

    Raises:
        argparse.ArgumentTypeError: For text that is not a whole number of 1 or more.
    """
    try:
        number = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid number {echo(text)!r}") from None
    if number < 1:
        raise argparse.ArgumentTypeError(f"{number} is less than 1")
    return number


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
        action="append",
        metavar="DOMAIN",
        help="a domain the reports are about; repeat it for several (required when there is no "
        "configuration file; with one, it picks the domains of the file to cover)",
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
    reading.add_argument(
        "--top",
        type=_top,
        metavar="N",
        help="with --json, keep only the N worst entries of each list and say what was left "
        "out; with --html, show N rows of the senders table instead of 50; needs one of them",
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
) -> tuple[tuple[Config, ...], str | None, dict[str, IngestionResult]] | None:
    """
    Resolve the configurations and read the reports, the part both commands share.

    The reports are read once for all the domains of the run (spec 010, ADR-3). The run is refused
    only when no domain kept a report: a domain that has none among others gets a result that says
    so (ADR-11).

    Args:
        args (argparse.Namespace): The parsed arguments: ``paths``, ``config``, ``domain``,
            ``json`` and ``lang``.
        messages (Messages, optional): The language of the refusal lines. Default: English.

    Returns:
        tuple[tuple[Config, ...], str | None, dict[str, IngestionResult]] | None: The
            configurations in the order of the run, the path of the file used as it should be shown
            and what was read for each domain; ``None`` when the run was refused, after the one line
            on standard error.
    """
    try:
        configs, source = resolve_configs(args.config, args.domain, messages)
    except _Refusal as refusal:
        write(sys.stderr, f"mailvigil: {refusal.message}")
        return None

    # The page of several domains is built in the stage that follows (spec 010, stage 6); until
    # then a run that asks for it is refused, not answered with the page of one domain.
    if len(configs) > 1 and getattr(args, "html", False):
        write(sys.stderr, "mailvigil: --html does not cover several domains yet")
        return None

    domains = [config.domain for config in configs]
    results = ingest_many(args.paths, domains, _now(), args.recursive)
    if not any(result.reports for result in results.values()):
        # What was refused or passed over is shared, so any one result tells it.
        write(sys.stderr, no_reports_message(results[domains[0]], domains, messages))
        return None
    return configs, source, results


def _run_summary(args: argparse.Namespace) -> int:
    """
    Run the ``summary`` command: resolve, ingest, summarize, print.

    Args:
        args (argparse.Namespace): The parsed arguments: ``paths``, ``config``, ``domain``,
            ``json``, ``top`` and ``lang``.

    Returns:
        int: ``EXIT_OK`` when the summary was printed, ``EXIT_REFUSED`` when it could not be made.
    """
    loaded = _load(args, args.lang)
    if loaded is None:
        return EXIT_REFUSED
    configs, source, results = loaded

    summaries = [summarize(results[config.domain], config) for config in configs]
    if args.json:
        # One domain prints the document of today; the envelope exists for two or more (ADR-7).
        document = (
            summary_document(summaries[0], source, args.top)
            if len(summaries) == 1
            else summaries_document(summaries, source, args.top)
        )
        write(sys.stdout, dumps(document))
    else:
        blocks = [render_summary(summary, source, args.lang) for summary in summaries]
        write(sys.stdout, join_blocks(blocks))
    return EXIT_OK


def _run_verdict(args: argparse.Namespace) -> int:
    """
    Run the ``verdict`` command: resolve, ingest, summarize, judge, print.

    Args:
        args (argparse.Namespace): The parsed arguments: ``paths``, ``config``, ``domain``,
            ``json``, ``html``, ``top`` and ``lang``.

    Returns:
        int: ``EXIT_OK`` for ready, ``EXIT_TOO_EARLY`` for too early, ``EXIT_NOT_READY`` for not
            ready and ``EXIT_REFUSED`` when no verdict could be made. With several domains it is
            the worst answer (spec 010, ADR-6).
    """
    loaded = _load(args, args.lang)
    if loaded is None:
        return EXIT_REFUSED
    configs, _source, results = loaded

    now = _now()
    summaries = [summarize(results[config.domain], config) for config in configs]
    verdicts = [judge(summary, now) for summary in summaries]
    if args.json:
        document = (
            verdict_document(verdicts[0], args.top)
            if len(verdicts) == 1
            else verdicts_document(verdicts, args.top)
        )
        write(sys.stdout, dumps(document))
    elif args.html and args.output is not None:
        try:
            _write_page(args.output, render_html(summaries[0], verdicts[0], args.lang, args.top))
        except OSError as error:
            reason = error.strerror or type(error).__name__
            line = args.lang.refusals.output_failed.format(
                path=echo(args.output), reason=echo(reason)
            )
            write(sys.stderr, f"mailvigil: {line}")
            return EXIT_REFUSED
    elif args.html:
        # ``render_html`` ends in a newline already; ``_write`` adds one, so the last is cut.
        page = render_html(summaries[0], verdicts[0], args.lang, args.top)
        write(sys.stdout, page.rstrip("\n"))
    else:
        blocks = [render_verdict(verdict, args.lang) for verdict in verdicts]
        if len(verdicts) > 1:
            blocks.append(render_tally(verdicts, args.lang))
        write(sys.stdout, join_blocks(blocks))
    return _VERDICT_EXIT[worst_answer(verdicts)]


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
    # Only the two structured formats have a list to trim (spec 006, ADR-8).
    if args.command in ("summary", "verdict") and args.top is not None and not args.json:
        if args.command == "summary":
            parser.error("argument --top: requires --json")
        if not args.html:
            parser.error("argument --top: requires --json or --html")
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
