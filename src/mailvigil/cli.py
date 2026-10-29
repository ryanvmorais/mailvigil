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

The ``fetch`` command (spec 009) is the one that uses the network. It resolves the password (a
prompt or ``--password-file``, never an argument), opens the mailbox, runs the loop of
``mailvigil.fetch`` and writes the outcome or the one line of a refusal. The adapter that imports
``imaplib`` and ``ssl`` is loaded inside ``_run_fetch`` only, so ``summary`` and ``verdict`` never
load it (RF-09).
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
import time
import traceback
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from types import MappingProxyType
from typing import TextIO

from mailvigil import __version__
from mailvigil.config import Config, ConfigError, check_domain, load_config
from mailvigil.fetch.errors import FetchReason, FetchRefused
from mailvigil.fetch.model import DEADLINE_SECONDS, DEFAULT_LIMIT, MAX_LIMIT
from mailvigil.fetch.run import fetch_reports
from mailvigil.fetch.store import Store, tag_of
from mailvigil.messages import ENGLISH, Messages, language_by_code
from mailvigil.render import no_reports_message, render_summary
from mailvigil.render_fetch import refusal_line, render_fetch
from mailvigil.render_html import render_html
from mailvigil.render_json import dumps, summary_document, verdict_document
from mailvigil.render_verdict import render_verdict
from mailvigil.reports import IngestionResult, ingest
from mailvigil.summary import summarize
from mailvigil.text import clean_text
from mailvigil.verdict import Answer, judge

# The file read from the current folder when --config is not given (Resolved decision 10).
DEFAULT_CONFIG = Path("mailvigil.toml")

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

# Longest path or domain echoed in a refusal line; it comes from the command line, not a report.
_MAX_ECHO = 200

# The most a password file is read for: the first line of a file longer than this is not a password.
_PASSWORD_FILE_MAX = 4096

# The port of IMAP over implicit TLS (RFC 8314).
_DEFAULT_PORT = 993

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
            f"invalid language {_echo(code)!r} (choose from {choices})"
        ) from None


def _integer_in(text: str, low: int, high: int) -> int:
    """
    Turn an option value into an integer inside a range.

    Args:
        text (str): The value as the user typed it.
        low (int): The smallest accepted value.
        high (int): The largest accepted value.

    Returns:
        int: The number.

    Raises:
        argparse.ArgumentTypeError: For text that is not a whole number, or outside the range.
    """
    try:
        number = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid number {_echo(text)!r}") from None
    if not low <= number <= high:
        raise argparse.ArgumentTypeError(f"{number} is not between {low} and {high}")
    return number


def _port(text: str) -> int:
    """
    Turn the ``--port`` value into a port number.

    Args:
        text (str): The value as the user typed it.

    Returns:
        int: A port in 1..65535.

    Raises:
        argparse.ArgumentTypeError: For anything else.
    """
    return _integer_in(text, 1, 65535)


def _limit(text: str) -> int:
    """
    Turn the ``--limit`` value into a count of messages.

    Args:
        text (str): The value as the user typed it.

    Returns:
        int: A number in 1..``MAX_LIMIT``.

    Raises:
        argparse.ArgumentTypeError: For anything else.
    """
    return _integer_in(text, 1, MAX_LIMIT)


def _day(text: str) -> date:
    """
    Turn the ``--since`` value into a day.

    Args:
        text (str): The value as the user typed it.

    Returns:
        date: The day.

    Raises:
        argparse.ArgumentTypeError: For text that is not a ``YYYY-MM-DD`` date.
    """
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid date {_echo(text)!r} (use YYYY-MM-DD)") from None


def _folder(text: str) -> str:
    """
    Check the ``--folder`` value.

    A control character is refused because a line break would end the command line that is sent to
    the server and start another one.

    Args:
        text (str): The value as the user typed it.

    Returns:
        str: The same text.

    Raises:
        argparse.ArgumentTypeError: For an empty name or one with a control character.
    """
    if not text or any(ord(char) < 0x20 or ord(char) == 0x7F for char in text):
        raise argparse.ArgumentTypeError("the folder name is empty or has a control character")
    return text


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
        "(mailvigil verdict ... --html > report.html; in Windows PowerShell 5.1 pipe it to "
        "Out-File -Encoding ascii); not with --json",
    )
    fetch_parser = commands.add_parser(
        "fetch",
        parents=[language],
        # ``--password`` must not be read as a short form of ``--password-file``.
        allow_abbrev=False,
        help="download the report messages of a mailbox over IMAP; "
        "the one command that uses the network",
        description="Download the DMARC report messages of a mailbox into a folder, for summary "
        "and verdict to read. This is the one command that connects to a server: always over TLS, "
        "and the certificate is always checked. It only reads: it never changes, moves or deletes "
        "mail and does not mark it as read. The password is asked for on the terminal or read from "
        "--password-file; it is never an argument or an environment variable, and nothing stores "
        f"it. Exit code {EXIT_OK} when the run finished, even with nothing new, {EXIT_REFUSED} "
        "when it was refused.",
    )
    fetch_parser.add_argument("--host", required=True, metavar="HOST", help="the IMAP server")
    fetch_parser.add_argument("--user", required=True, metavar="NAME", help="the login name")
    fetch_parser.add_argument(
        "--to",
        required=True,
        type=Path,
        metavar="DIR",
        help="the folder the messages are saved in (created if missing)",
    )
    fetch_parser.add_argument(
        "--port",
        type=_port,
        default=_DEFAULT_PORT,
        metavar="N",
        help=f"where to connect (default: {_DEFAULT_PORT}); the connection is always TLS",
    )
    fetch_parser.add_argument(
        "--folder",
        type=_folder,
        default="INBOX",
        metavar="NAME",
        help="the mailbox folder to read (default: INBOX)",
    )
    fetch_parser.add_argument(
        "--since",
        type=_day,
        metavar="YYYY-MM-DD",
        help="only messages received on or after this day (default: all)",
    )
    fetch_parser.add_argument(
        "--limit",
        type=_limit,
        default=DEFAULT_LIMIT,
        metavar="N",
        help="the most new messages to download in one run, newest first "
        f"(default: {DEFAULT_LIMIT}, at most {MAX_LIMIT})",
    )
    fetch_parser.add_argument(
        "--password-file",
        type=Path,
        metavar="FILE",
        help="read the password from the first line of this file instead of asking for it",
    )
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
        _write(sys.stdout, dumps(summary_document(summary, source)))
    else:
        _write(sys.stdout, render_summary(summary, source, args.lang))
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
    verdict = judge(summary)
    if args.json:
        _write(sys.stdout, dumps(verdict_document(verdict)))
    elif args.html:
        # ``render_html`` ends in a newline already; ``_write`` adds one, so the last is cut.
        _write(sys.stdout, render_html(summary, verdict, args.lang).rstrip("\n"))
    else:
        _write(sys.stdout, render_verdict(verdict, args.lang))
    return _VERDICT_EXIT[verdict.answer]


# ---------------------------------------------------------------------------
# Fetch (spec 009)
# ---------------------------------------------------------------------------


def _password_from_file(path: Path, messages: Messages) -> str:
    """
    Read the password from the first line of a file.

    At most ``_PASSWORD_FILE_MAX`` bytes are read; the line end (LF or CRLF) is not part of the
    password and later lines are ignored. On POSIX a file that group or others can read adds one
    warning line on standard error and the run goes on.

    Args:
        path (Path): The ``--password-file`` value.
        messages (Messages): The language of the warning.

    Returns:
        str: The password.

    Raises:
        FetchRefused: ``password_file`` when the file cannot be read, is empty or has a first line
            that long; ``password_unusable`` when the line is not UTF-8.
    """
    try:
        mode = path.stat().st_mode
        with path.open("rb") as stream:
            data = stream.read(_PASSWORD_FILE_MAX + 1)
    except OSError:
        raise FetchRefused(FetchReason.PASSWORD_FILE) from None
    line = data.split(b"\n", 1)[0].removesuffix(b"\r")
    if not line or len(line) > _PASSWORD_FILE_MAX:
        raise FetchRefused(FetchReason.PASSWORD_FILE)
    try:
        password = line.decode("utf-8")
    except UnicodeDecodeError:
        raise FetchRefused(FetchReason.PASSWORD_UNUSABLE) from None
    # The mode bits mean nothing on Windows, where access is decided by ACLs.
    if os.name == "posix" and mode & 0o077:
        warning = messages.fetch.password_file_exposed.format(path=_echo(path))
        _write(sys.stderr, f"mailvigil: {warning}")
    return password


def _password(args: argparse.Namespace, parser: argparse.ArgumentParser) -> str:
    """
    Decide where the password comes from and read it: the file, else the terminal.

    Never an argument and never an environment variable (spec 009, RF-02).

    Args:
        args (argparse.Namespace): The parsed arguments: ``password_file`` and ``lang``.
        parser (argparse.ArgumentParser): Used to end the run with a usage error.

    Returns:
        str: The password.

    Raises:
        FetchRefused: When the file or the answer at the prompt cannot be a password.
    """
    if args.password_file is not None:
        return _password_from_file(args.password_file, args.lang)
    if not sys.stdin.isatty():
        parser.error("no terminal: give the password in a file with --password-file")
    password = getpass.getpass()
    if not password:
        raise FetchRefused(FetchReason.PASSWORD_UNUSABLE)
    return password


def _run_fetch(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """
    Run the ``fetch`` command: the password, the connection, the loop, the outcome.

    Args:
        args (argparse.Namespace): The parsed arguments: ``host``, ``port``, ``user``, ``to``,
            ``folder``, ``since``, ``limit``, ``password_file`` and ``lang``.
        parser (argparse.ArgumentParser): Used to end the run with a usage error.

    Returns:
        int: ``EXIT_OK`` when the run finished, even with nothing new; ``EXIT_REFUSED`` when it
            was refused, after one line on standard error.
    """
    # Imported here and nowhere else: it is the one module that loads ``imaplib`` and ``ssl``, and
    # ``summary`` and ``verdict`` must never load them (spec 009, ADR-7, RF-09).
    from mailvigil.fetch import imap

    try:
        password = _password(args, parser)
        clock = time.monotonic
        deadline = clock() + DEADLINE_SECONDS
        try:
            # Looked up on the module at call time, so a test can replace it.
            mailbox = imap.connect(args.host, args.port, args.user, password, clock, deadline)
        except ValueError as error:
            parser.error(f"argument --user: {error}")
        try:
            store = Store(args.to, tag_of(args.host, args.user, args.folder))
            outcome = fetch_reports(
                mailbox, args.folder, args.since, store, args.limit, clock, deadline
            )
        finally:
            mailbox.close()
    except FetchRefused as refusal:
        _write(sys.stderr, refusal_line(refusal, args.lang))
        return EXIT_REFUSED
    _write(sys.stdout, render_fetch(outcome, str(args.to), args.lang))
    return EXIT_OK


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
    if args.command == "summary":
        return _run_summary(args)
    if args.command == "verdict":
        return _run_verdict(args)
    if args.command == "fetch":
        return _run_fetch(args, parser)
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
        _write(sys.stderr, _internal_error_line(error))
        return EXIT_INTERNAL
