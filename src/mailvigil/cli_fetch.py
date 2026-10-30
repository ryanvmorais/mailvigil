"""
The ``fetch`` command of MailVigil, as the command line sees it (spec 009).

It holds what only ``fetch`` needs: the option types, the subparser, the password helpers and
``run_fetch``. ``fetch`` is the one command that uses the network. It resolves the password (a
prompt or ``--password-file``, never an argument), opens the mailbox, runs the loop of
``mailvigil.fetch`` and writes the outcome or the one line of a refusal. The adapter that imports
``imaplib`` and ``ssl`` is loaded inside ``run_fetch`` only, so ``summary`` and ``verdict`` never
load it (RF-09); keep it that way, ``tests/test_offline_isolation.py`` guards it.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
import time
from datetime import date
from pathlib import Path

from mailvigil.cli_common import EXIT_OK, EXIT_REFUSED, echo, write
from mailvigil.fetch.errors import FetchReason, FetchRefused
from mailvigil.fetch.model import DEADLINE_SECONDS, DEFAULT_LIMIT, MAX_LIMIT
from mailvigil.fetch.run import fetch_reports
from mailvigil.fetch.store import Store, tag_of
from mailvigil.messages import Messages
from mailvigil.render_fetch import refusal_line, render_fetch

# The most a password file is read for: the first line of a file longer than this is not a password.
_PASSWORD_FILE_MAX = 4096

# The port of IMAP over implicit TLS (RFC 8314).
_DEFAULT_PORT = 993

# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------


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
        raise argparse.ArgumentTypeError(f"invalid number {echo(text)!r}") from None
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
        raise argparse.ArgumentTypeError(f"invalid date {echo(text)!r} (use YYYY-MM-DD)") from None


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


def add_fetch_parser(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
    language: argparse.ArgumentParser,
) -> None:
    """
    Add the ``fetch`` subcommand to the parser of the ``mailvigil`` command.

    Args:
        commands (argparse._SubParsersAction[argparse.ArgumentParser]): The subcommands of the main
            parser.
        language (argparse.ArgumentParser): The parent parser that holds ``--lang``; ``fetch``
            shares no other option with the reading commands (spec 009, ADR-7).
    """
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
    fetch_parser.add_argument(
        "--cafile",
        type=Path,
        metavar="FILE",
        help="a PEM file with a certificate authority to trust besides the system's, for a server "
        "behind a private one; the certificate is still checked",
    )


# ---------------------------------------------------------------------------
# Run
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
        warning = messages.fetch.password_file_exposed.format(path=echo(path))
        write(sys.stderr, f"mailvigil: {warning}")
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


def run_fetch(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """
    Run the ``fetch`` command: the password, the connection, the loop, the outcome.

    Args:
        args (argparse.Namespace): The parsed arguments: ``host``, ``port``, ``user``, ``to``,
            ``folder``, ``since``, ``limit``, ``password_file``, ``cafile`` and ``lang``.
        parser (argparse.ArgumentParser): Used to end the run with a usage error.

    Returns:
        int: ``EXIT_OK`` when the run finished, even with nothing new; ``EXIT_REFUSED`` when it
            was refused, after one line on standard error.
    """
    # Imported here and nowhere else: it is the one module that loads ``imaplib`` and ``ssl``, and
    # ``summary`` and ``verdict`` must never load them (spec 009, ADR-7, RF-09).
    from mailvigil.fetch import imap

    try:
        # Read the authority file first, so a bad one is told before the password is asked for.
        imap.build_context(args.cafile)
        password = _password(args, parser)
        clock = time.monotonic
        deadline = clock() + DEADLINE_SECONDS
        try:
            # Looked up on the module at call time, so a test can replace it.
            mailbox = imap.connect(
                args.host, args.port, args.user, password, clock, deadline, cafile=args.cafile
            )
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
        write(sys.stderr, refusal_line(refusal, args.lang))
        return EXIT_REFUSED
    write(sys.stdout, render_fetch(outcome, str(args.to), args.lang))
    return EXIT_OK
