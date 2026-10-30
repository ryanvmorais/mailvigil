"""
Tests of the ``fetch`` command through ``main(argv)`` (spec 009, RF-02, RF-08, RF-09, ADR-7).

Isolation: ``mailvigil.fetch.imap.connect`` is replaced by a function that records its arguments and
returns a ``FakeMailbox`` (or raises a scripted refusal), so no test opens a socket. The host ends
in ``.invalid``, the user and the password are invented, and the password is a canary that must
appear in no output (RNF-02). Every test runs from an empty working folder and the messages are the
synthetic ones of ``tests/fetch_helpers.py`` (RNF-06).
"""

from __future__ import annotations

import getpass
import json
import os
import re
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.fetch_helpers import TEST_CA_PEM, FakeMailbox, build_message
from tests.help_golden import SUMMARY_HELP, VERDICT_HELP

from mailvigil import cli_fetch
from mailvigil.cli import EXIT_INTERNAL, EXIT_OK, EXIT_REFUSED, EXIT_USAGE, main
from mailvigil.fetch import imap as fetch_imap
from mailvigil.fetch.errors import FetchReason, FetchRefused
from mailvigil.fetch.model import DEADLINE_SECONDS, MAX_LIMIT, MAX_MESSAGE_BYTES

# The password of every test; it is searched for in everything the command prints.
CANARY = "canary-Pa55-w0rd"

# ``.invalid`` is reserved (RFC 2606), so no test can reach a real server.
_HOST = "imap.example.invalid"

# What the replaced ``connect`` was called with, by name.
type _Call = dict[str, object]


class _Connect:
    """
    The stand-in for ``mailvigil.fetch.imap.connect``.

    Attributes:
        mailbox (FakeMailbox): What the call returns.
        refusal (FetchRefused | None): Raised instead of returning, when set.
        error (Exception | None): Raised instead of returning, when set (a usage error).
        calls (list[_Call]): The arguments of every call.
    """

    def __init__(self, mailbox: FakeMailbox) -> None:
        """
        Build the stand-in.

        Args:
            mailbox (FakeMailbox): The mailbox to hand back.
        """
        self.mailbox = mailbox
        self.refusal: FetchRefused | None = None
        self.error: Exception | None = None
        self.calls: list[_Call] = []

    def __call__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        clock: Callable[[], float],
        deadline: float,
        cafile: Path | None = None,
    ) -> FakeMailbox:
        """
        Record the call and answer as scripted.

        Args:
            host (str): The server.
            port (int): The port.
            user (str): The login.
            password (str): The password.
            clock (Callable[[], float]): The clock.
            deadline (float): The deadline.
            cafile (Path | None, optional): The authority file. Default: ``None``.

        Returns:
            FakeMailbox: The scripted mailbox.

        Raises:
            FetchRefused: When ``refusal`` is set.
            Exception: When ``error`` is set.
        """
        self.calls.append(
            {
                "host": host,
                "port": port,
                "user": user,
                "password": password,
                "clock": clock,
                "deadline": deadline,
                "cafile": cafile,
            }
        )
        if self.refusal is not None:
            raise self.refusal
        if self.error is not None:
            raise self.error
        return self.mailbox


@pytest.fixture(autouse=True)
def empty_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """
    Run every test from an empty folder.

    Args:
        tmp_path (Path): The test's own folder.
        monkeypatch (pytest.MonkeyPatch): Used to change the working directory.

    Returns:
        Path: The empty working directory.
    """
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    return cwd


@pytest.fixture
def mailbox() -> FakeMailbox:
    """
    Build the mailbox the command will talk to, with two messages.

    Returns:
        FakeMailbox: UIDs 1 and 2, each a small synthetic message.
    """
    return FakeMailbox(bodies={1: build_message("one"), 2: build_message("two")}, validity=7)


@pytest.fixture
def connect(monkeypatch: pytest.MonkeyPatch, mailbox: FakeMailbox) -> _Connect:
    """
    Replace ``connect`` at the one place the command looks it up.

    Args:
        monkeypatch (pytest.MonkeyPatch): Used to replace the attribute of the module.
        mailbox (FakeMailbox): What the replacement hands back.

    Returns:
        _Connect: The replacement, to read the calls from.
    """
    replacement = _Connect(mailbox)
    monkeypatch.setattr(fetch_imap, "connect", replacement)
    return replacement


@pytest.fixture
def password_file(tmp_path: Path) -> Path:
    """
    Write a password file that only its owner can read.

    Args:
        tmp_path (Path): The test's own folder.

    Returns:
        Path: The file, holding the canary and a newline.
    """
    path = tmp_path / "secret.txt"
    path.write_text(CANARY + "\n", encoding="ascii")
    path.chmod(0o600)
    return path


def _args(tmp_path: Path, password: Path | None, *extra: str) -> list[str]:
    """
    Build the arguments of a ``fetch`` run.

    Args:
        tmp_path (Path): The test's own folder; the messages go to ``tmp_path / "mail"``.
        password (Path | None): The password file, or ``None`` to leave the option out.
        *extra (str): More arguments, after the common ones.

    Returns:
        list[str]: The arguments, command included.
    """
    args = ["fetch", "--host", _HOST, "--user", "reports", "--to", str(tmp_path / "mail")]
    if password is not None:
        args += ["--password-file", str(password)]
    return [*args, *extra]


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    """
    Run the command and collect everything it printed.

    Args:
        argv (list[str]): The arguments.
        capsys (pytest.CaptureFixture[str]): The capture.

    Returns:
        tuple[int, str, str]: The exit code, standard output and standard error. The canary must
            be in neither.
    """
    code = main(argv)
    captured = capsys.readouterr()
    assert CANARY not in captured.out
    assert CANARY not in captured.err
    return code, captured.out, captured.err


def _numbers(out: str) -> dict[str, int]:
    """
    Read the six numbers of the outcome text by their labels.

    Args:
        out (str): Standard output of a finished run.

    Returns:
        dict[str, int]: The label without its colon, and the number.
    """
    found = re.findall(r"^  (.+?): +(\d+)$", out, flags=re.MULTILINE)
    return {label: int(number) for label, number in found}


def _usage_error(argv: list[str], capsys: pytest.CaptureFixture[str]) -> str:
    """
    Run a command that argparse refuses and return what it said.

    Args:
        argv (list[str]): The arguments.
        capsys (pytest.CaptureFixture[str]): The capture.

    Returns:
        str: Standard error, which holds the usage line and the reason.
    """
    with pytest.raises(SystemExit) as exit_info:
        main(argv)
    captured = capsys.readouterr()
    assert exit_info.value.code == EXIT_USAGE
    assert captured.out == ""
    assert CANARY not in captured.err
    return captured.err


def _saved(tmp_path: Path) -> list[Path]:
    """
    List the messages the run wrote.

    Args:
        tmp_path (Path): The test's own folder.

    Returns:
        list[Path]: The ``.eml`` files of ``tmp_path / "mail"``, sorted.
    """
    return sorted((tmp_path / "mail").glob("*.eml"))


# ---------------------------------------------------------------------------
# A run that finishes (RF-08)
# ---------------------------------------------------------------------------


def test_new_messages_are_saved_and_counted(
    tmp_path: Path,
    password_file: Path,
    connect: _Connect,
    mailbox: FakeMailbox,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Two new messages: exit 0, the six numbers, two files, the mailbox closed."""
    code, out, err = _run(_args(tmp_path, password_file), capsys)

    assert code == EXIT_OK
    assert err == ""
    assert _numbers(out) == {
        "Matched": 2,
        "Saved": 2,
        "Already saved": 0,
        "Too large": 0,
        "Skipped": 0,
        "Left for later": 0,
    }
    assert "Saved in:" in out
    assert len(_saved(tmp_path)) == 2
    assert mailbox.closed == 1
    assert mailbox.called("select") == [("select", "INBOX")]


def test_the_connection_gets_the_arguments_the_user_gave(
    tmp_path: Path, password_file: Path, connect: _Connect, capsys: pytest.CaptureFixture[str]
) -> None:
    """Host, default port, user, the password from the file and a deadline from the clock."""
    _run(_args(tmp_path, password_file), capsys)

    (call,) = connect.calls
    assert call["host"] == _HOST
    assert call["port"] == 993
    assert call["user"] == "reports"
    assert call["password"] == CANARY
    clock = call["clock"]
    assert callable(clock)
    assert isinstance(call["deadline"], float)
    # A tolerance for float rounding: with a coarse clock, (x + 1800) - x is a few ulps over 1800.
    assert 0 < call["deadline"] - clock() <= DEADLINE_SECONDS + 1e-6


def test_the_cafile_reaches_the_connection(
    tmp_path: Path, password_file: Path, connect: _Connect, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--cafile`` is passed on; without it the connection gets none."""
    authority = tmp_path / "ca.pem"
    authority.write_text(TEST_CA_PEM, encoding="ascii")

    assert _run(_args(tmp_path, password_file, "--cafile", str(authority)), capsys)[0] == EXIT_OK
    assert _run(_args(tmp_path, password_file), capsys)[0] == EXIT_OK

    assert [call["cafile"] for call in connect.calls] == [authority, None]


def test_an_unusable_cafile_is_told_before_the_password_is_asked_for(
    tmp_path: Path,
    connect: _Connect,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A missing authority file is a refusal (exit 1) with no prompt and no connection."""
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(getpass, "getpass", _forbidden)

    code, out, err = _run(_args(tmp_path, None, "--cafile", str(tmp_path / "missing.pem")), capsys)

    assert code == EXIT_REFUSED
    assert out == ""
    assert err == "mailvigil: could not read a certificate authority from the --cafile file\n"
    assert connect.calls == []


def test_the_options_reach_the_mailbox(
    tmp_path: Path,
    password_file: Path,
    connect: _Connect,
    mailbox: FakeMailbox,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--port``, ``--folder``, ``--since`` and ``--limit`` are used."""
    argv = _args(
        tmp_path,
        password_file,
        *["--port", "143", "--folder", "Reports", "--since", "2026-10-01", "--limit", "1"],
    )

    code, out, _err = _run(argv, capsys)

    assert code == EXIT_OK
    assert connect.calls[0]["port"] == 143
    assert mailbox.called("select") == [("select", "Reports")]
    assert mailbox.called("search") == [("search", date(2026, 10, 1))]
    assert len(_saved(tmp_path)) == 1
    assert _numbers(out)["Left for later"] == 1


def test_nothing_new_is_still_a_success(
    tmp_path: Path, password_file: Path, connect: _Connect, capsys: pytest.CaptureFixture[str]
) -> None:
    """A second run saves nothing, counts both as already saved and exits 0."""
    _run(_args(tmp_path, password_file), capsys)

    code, out, err = _run(_args(tmp_path, password_file), capsys)

    assert code == EXIT_OK
    assert err == ""
    assert "Saved:" in out
    assert _numbers(out)["Already saved"] == 2
    assert len(_saved(tmp_path)) == 2


def test_the_text_in_portuguese_is_ascii(
    tmp_path: Path, password_file: Path, connect: _Connect, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--lang pt-BR`` changes the words and keeps the output ASCII."""
    code, out, _err = _run(_args(tmp_path, password_file, "--lang", "pt-BR"), capsys)

    assert code == EXIT_OK
    assert "Salvas:" in out
    assert out.isascii()


def test_json_prints_the_six_numbers_as_one_document(
    tmp_path: Path, password_file: Path, connect: _Connect, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--json``: exit 0, one ASCII document and a newline on standard output, nothing else."""
    code, out, err = _run(_args(tmp_path, password_file, "--json"), capsys)

    assert code == EXIT_OK
    assert err == ""
    assert out.isascii()
    assert out.endswith("}\n")
    assert json.loads(out) == {
        "schema_version": 1,
        "command": "fetch",
        "matched": 2,
        "saved": 2,
        "already": 0,
        "too_large": 0,
        "skipped": 0,
        "left": 0,
    }
    assert len(_saved(tmp_path)) == 2


def test_json_holds_no_folder_host_or_user(
    tmp_path: Path, password_file: Path, connect: _Connect, capsys: pytest.CaptureFixture[str]
) -> None:
    """The document is numbers: what the user typed is not echoed into it."""
    _code, out, _err = _run(_args(tmp_path, password_file, "--json"), capsys)

    assert str(tmp_path) not in out
    assert _HOST not in out
    assert "reports" not in json.loads(out)


def test_json_and_the_text_report_the_same_numbers(
    tmp_path: Path, password_file: Path, connect: _Connect, capsys: pytest.CaptureFixture[str]
) -> None:
    """A second run, once as text and once as JSON: both say two messages were already saved."""
    _run(_args(tmp_path, password_file), capsys)

    _code, text, _err = _run(_args(tmp_path, password_file), capsys)
    _code, out, _err = _run(_args(tmp_path, password_file, "--json"), capsys)

    assert _numbers(text)["Already saved"] == json.loads(out)["already"] == 2


def test_json_does_not_depend_on_the_language(
    tmp_path: Path, password_file: Path, connect: _Connect, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--lang`` is accepted with ``--json`` and changes nothing (006, ADR-6)."""
    _code, english, _err = _run(_args(tmp_path, password_file, "--json"), capsys)
    arguments = _args(tmp_path, password_file, "--json", "--lang", "pt-BR")
    _code, portuguese, _err = _run(arguments, capsys)

    assert json.loads(english)["saved"] == 2
    assert json.loads(portuguese) == {**json.loads(english), "saved": 0, "already": 2}


@pytest.mark.parametrize("reason", list(FetchReason))
def test_json_does_not_change_a_refusal(
    reason: FetchReason,
    tmp_path: Path,
    password_file: Path,
    connect: _Connect,
    mailbox: FakeMailbox,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A refused run prints no document: standard output is empty and the one line is on stderr."""
    mailbox.failures["search"] = FetchRefused(reason)

    code, out, err = _run(_args(tmp_path, password_file, "--json"), capsys)

    assert code == EXIT_REFUSED
    assert out == ""
    assert err.startswith("mailvigil: ")
    assert len(err.splitlines()) == 1


# ---------------------------------------------------------------------------
# A run that is refused (RF-08)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("reason", list(FetchReason))
def test_every_refusal_is_one_line_and_exit_one(
    reason: FetchReason,
    tmp_path: Path,
    password_file: Path,
    connect: _Connect,
    mailbox: FakeMailbox,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A refusal after the connection: nothing on standard output, one line, the mailbox closed."""
    mailbox.failures["search"] = FetchRefused(reason)

    code, out, err = _run(_args(tmp_path, password_file), capsys)

    assert code == EXIT_REFUSED
    assert out == ""
    assert err.startswith("mailvigil: ")
    assert len(err.splitlines()) == 1
    assert mailbox.closed == 1


@pytest.mark.parametrize("reason", list(FetchReason))
def test_every_refusal_of_the_connection_is_exit_one(
    reason: FetchReason,
    tmp_path: Path,
    password_file: Path,
    connect: _Connect,
    mailbox: FakeMailbox,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A refusal while connecting: the same line, and there is no mailbox to close."""
    connect.refusal = FetchRefused(reason, "server said no")

    code, out, err = _run(_args(tmp_path, password_file), capsys)

    assert code == EXIT_REFUSED
    assert out == ""
    assert err.endswith(": server said no\n")
    assert mailbox.closed == 0


def test_a_refusal_after_some_work_says_how_many_files_are_valid(
    tmp_path: Path,
    password_file: Path,
    connect: _Connect,
    mailbox: FakeMailbox,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The newest is saved, the next one fails: exit 1 and the saved count on a second line."""
    mailbox.message_failures[1] = FetchRefused(FetchReason.TIMEOUT)

    code, out, err = _run(_args(tmp_path, password_file), capsys)

    assert code == EXIT_REFUSED
    assert out == ""
    assert err.splitlines() == [
        "mailvigil: the server took too long to answer",
        "1 message was saved before it stopped.",
    ]
    assert len(_saved(tmp_path)) == 1
    assert mailbox.closed == 1


def test_a_refusal_in_portuguese_is_ascii(
    tmp_path: Path,
    password_file: Path,
    connect: _Connect,
    mailbox: FakeMailbox,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The refusal line follows ``--lang`` and stays ASCII."""
    mailbox.failures["select"] = FetchRefused(FetchReason.FOLDER_NOT_FOUND)

    code, _out, err = _run(_args(tmp_path, password_file, "--lang", "pt-BR"), capsys)

    assert code == EXIT_REFUSED
    assert err == "mailvigil: a pasta nao foi encontrada\n"


# ---------------------------------------------------------------------------
# Usage errors (exit 2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("missing", ["--host", "--user", "--to"])
def test_a_missing_required_option_is_a_usage_error(
    missing: str,
    tmp_path: Path,
    password_file: Path,
    connect: _Connect,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--host``, ``--user`` and ``--to`` are required."""
    argv = _args(tmp_path, password_file)
    at = argv.index(missing)
    del argv[at : at + 2]

    err = _usage_error(argv, capsys)

    assert missing in err
    assert connect.calls == []


@pytest.mark.parametrize(
    ("extra", "word"),
    [
        (["--since", "yesterday"], "date"),
        (["--since", "2026-13-40"], "date"),
        (["--limit", "0"], "--limit"),
        (["--limit", str(MAX_LIMIT + 1)], "--limit"),
        (["--limit", "many"], "--limit"),
        (["--port", "0"], "--port"),
        (["--port", "70000"], "--port"),
        (["--folder", "In\nbox"], "--folder"),
        (["--folder", ""], "--folder"),
    ],
)
def test_a_bad_value_is_a_usage_error(
    extra: list[str],
    word: str,
    tmp_path: Path,
    password_file: Path,
    connect: _Connect,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A value out of its range is refused by the parser, before any connection."""
    err = _usage_error(_args(tmp_path, password_file, *extra), capsys)

    assert word in err
    assert connect.calls == []


def test_the_limit_and_the_port_accept_their_edges(
    tmp_path: Path, password_file: Path, connect: _Connect, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--limit`` 1 to ``MAX_LIMIT`` and ``--port`` 1 to 65535 are valid."""
    for extra in (["--limit", str(MAX_LIMIT), "--port", "65535"], ["--limit", "1", "--port", "1"]):
        code, _out, _err = _run(_args(tmp_path, password_file, *extra), capsys)
        assert code == EXIT_OK


def test_a_user_that_is_not_printable_ascii_is_a_usage_error(
    tmp_path: Path,
    password_file: Path,
    connect: _Connect,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The adapter raises ``ValueError`` for the user; the command turns it into exit 2."""
    connect.error = ValueError("the user name is empty or has a control character")

    err = _usage_error(_args(tmp_path, password_file), capsys)

    assert "--user" in err


def test_the_real_connect_refuses_a_bad_user_before_any_connection(
    tmp_path: Path, password_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Without the stand-in: a user with a line break ends in exit 2 and opens no socket."""
    argv = _args(tmp_path, password_file)
    argv[argv.index("--user") + 1] = "re\nports"

    err = _usage_error(argv, capsys)

    assert "--user" in err


def test_no_terminal_and_no_password_file_is_a_usage_error(
    tmp_path: Path,
    connect: _Connect,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """It does not wait for input: it says how to give the password."""
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(getpass, "getpass", _forbidden)

    err = _usage_error(_args(tmp_path, None), capsys)

    assert "--password-file" in err
    assert connect.calls == []


def _forbidden(*_args: object, **_kwargs: object) -> str:
    """
    Stand in for a call that must not happen.

    Raises:
        AssertionError: Always.
    """
    raise AssertionError("the password must not be asked for here")


# ---------------------------------------------------------------------------
# Where the password comes from (RF-02)
# ---------------------------------------------------------------------------


def test_the_password_is_asked_for_on_a_terminal(
    tmp_path: Path,
    connect: _Connect,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """With a terminal and no file, ``getpass`` is used and nothing else reads the password."""
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(getpass, "getpass", lambda *_a, **_k: CANARY)

    code, _out, _err = _run(_args(tmp_path, None), capsys)

    assert code == EXIT_OK
    assert connect.calls[0]["password"] == CANARY


def test_an_empty_answer_at_the_prompt_is_a_refusal(
    tmp_path: Path,
    connect: _Connect,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Enter with nothing typed is ``password_unusable`` (exit 1), without connecting."""
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(getpass, "getpass", lambda *_a, **_k: "")

    code, _out, err = _run(_args(tmp_path, None), capsys)

    assert code == EXIT_REFUSED
    assert err.startswith("mailvigil: the password is empty")
    assert connect.calls == []


def test_the_file_wins_over_the_terminal(
    tmp_path: Path,
    password_file: Path,
    connect: _Connect,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--password-file`` is used even when there is a terminal, and nothing is asked."""
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(getpass, "getpass", _forbidden)

    code, _out, _err = _run(_args(tmp_path, password_file), capsys)

    assert code == EXIT_OK
    assert connect.calls[0]["password"] == CANARY


@pytest.mark.parametrize(
    "content",
    [CANARY, CANARY + "\n", CANARY + "\r\n", CANARY + "\nsecond line\n", CANARY + "\r\nmore"],
    ids=["no-newline", "lf", "crlf", "second-line-ignored", "crlf-then-more"],
)
def test_the_password_is_the_first_line_without_its_line_end(
    content: str,
    tmp_path: Path,
    connect: _Connect,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A trailing newline, of either kind, is not part of the password; later lines are ignored."""
    path = tmp_path / "pw.txt"
    path.write_bytes(content.encode("ascii"))
    path.chmod(0o600)

    code, _out, _err = _run(_args(tmp_path, path), capsys)

    assert code == EXIT_OK
    assert connect.calls[0]["password"] == CANARY


def test_spaces_inside_the_password_are_kept(
    tmp_path: Path, connect: _Connect, capsys: pytest.CaptureFixture[str]
) -> None:
    """Only the line end is removed, so a password with spaces arrives whole."""
    path = tmp_path / "pw.txt"
    path.write_text("a b c \n", encoding="ascii")
    path.chmod(0o600)

    _run(_args(tmp_path, path), capsys)

    assert connect.calls[0]["password"] == "a b c "


@pytest.mark.parametrize("content", [b"", b"\n", b"\r\n", b"\nsecret\n"], ids=repr)
def test_an_empty_first_line_is_a_refusal(
    content: bytes,
    tmp_path: Path,
    connect: _Connect,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An empty file, or one whose first line is empty, is ``password_file`` (exit 1)."""
    path = tmp_path / "pw.txt"
    path.write_bytes(content)
    path.chmod(0o600)

    code, out, err = _run(_args(tmp_path, path), capsys)

    assert code == EXIT_REFUSED
    assert out == ""
    assert err == "mailvigil: could not read a password from the file\n"
    assert connect.calls == []


def test_a_missing_password_file_is_a_refusal(
    tmp_path: Path, connect: _Connect, capsys: pytest.CaptureFixture[str]
) -> None:
    """A path that does not exist is ``password_file``, without a stack trace."""
    code, _out, err = _run(_args(tmp_path, tmp_path / "nowhere.txt"), capsys)

    assert code == EXIT_REFUSED
    assert err == "mailvigil: could not read a password from the file\n"
    assert connect.calls == []


def test_a_folder_as_password_file_is_a_refusal(
    tmp_path: Path, connect: _Connect, capsys: pytest.CaptureFixture[str]
) -> None:
    """A path that is a folder cannot be read; it is ``password_file`` too."""
    code, _out, err = _run(_args(tmp_path, tmp_path), capsys)

    assert code == EXIT_REFUSED
    assert err == "mailvigil: could not read a password from the file\n"


def test_a_first_line_over_four_kib_is_not_a_password(
    tmp_path: Path, connect: _Connect, capsys: pytest.CaptureFixture[str]
) -> None:
    """A file that is not a password file is refused instead of being sent whole to the server."""
    path = tmp_path / "pw.txt"
    path.write_bytes(b"x" * 5000 + b"\n")
    path.chmod(0o600)

    code, _out, err = _run(_args(tmp_path, path), capsys)

    assert code == EXIT_REFUSED
    assert err == "mailvigil: could not read a password from the file\n"
    assert connect.calls == []


def test_a_password_with_a_control_character_is_a_refusal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The real ``connect`` refuses it before it opens any connection (exit 1)."""
    path = tmp_path / "pw.txt"
    path.write_bytes(b"sen\x01ha\n")
    path.chmod(0o600)

    code, _out, err = _run(_args(tmp_path, path), capsys)

    assert code == EXIT_REFUSED
    assert err.startswith("mailvigil: the password is empty, has a line break")


def test_a_password_outside_ascii_reaches_the_connection(
    tmp_path: Path, connect: _Connect, capsys: pytest.CaptureFixture[str]
) -> None:
    """The command no longer judges it: the adapter decides by the server (ADR-9)."""
    path = tmp_path / "pw.txt"
    path.write_bytes("sença\n".encode())
    path.chmod(0o600)

    code, _out, _err = _run(_args(tmp_path, path), capsys)

    assert code == EXIT_OK
    assert connect.calls[0]["password"] == "sença"


def test_a_file_that_is_not_text_is_a_refusal(
    tmp_path: Path, connect: _Connect, capsys: pytest.CaptureFixture[str]
) -> None:
    """Bytes that are not even UTF-8 are ``password_unusable`` as well."""
    path = tmp_path / "pw.txt"
    path.write_bytes(b"\xff\xfe\x00\x00\n")
    path.chmod(0o600)

    code, _out, err = _run(_args(tmp_path, path), capsys)

    assert code == EXIT_REFUSED
    assert err.startswith("mailvigil: the password is empty, has a line break")


def test_a_file_others_can_read_adds_a_warning_and_still_works(
    tmp_path: Path,
    password_file: Path,
    connect: _Connect,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Group or other permission bits: one warning line on standard error, the run goes on."""
    # Windows reports 0o666 for every file; saying "posix" lets the check run there too.
    monkeypatch.setattr(cli_fetch, "os", SimpleNamespace(name="posix"))
    password_file.chmod(0o644)

    code, out, err = _run(_args(tmp_path, password_file), capsys)

    assert code == EXIT_OK
    assert "Saved:" in out
    assert err.startswith("mailvigil: warning: ")
    assert "chmod 600" in err
    assert len(err.splitlines()) == 1


@pytest.mark.skipif(os.name != "posix", reason="file modes are a POSIX idea")
def test_a_private_file_adds_no_warning(
    tmp_path: Path, password_file: Path, connect: _Connect, capsys: pytest.CaptureFixture[str]
) -> None:
    """Owner-only permission: standard error stays empty."""
    _code, _out, err = _run(_args(tmp_path, password_file), capsys)

    assert err == ""


def test_the_password_is_not_an_option(
    tmp_path: Path, password_file: Path, connect: _Connect, capsys: pytest.CaptureFixture[str]
) -> None:
    """There is no ``--password`` and no ``--insecure``: argparse refuses both."""
    for option in (["--password", "x"], ["--insecure"], ["--no-verify"]):
        err = _usage_error(_args(tmp_path, password_file, *option), capsys)
        assert "unrecognized arguments" in err


# ---------------------------------------------------------------------------
# The mailbox is always closed
# ---------------------------------------------------------------------------


def test_the_mailbox_is_closed_when_the_loop_fails_unexpectedly(
    tmp_path: Path,
    password_file: Path,
    connect: _Connect,
    mailbox: FakeMailbox,
) -> None:
    """Even an exception that is not a refusal passes through the ``finally``."""
    mailbox.on_message = _explode

    code = main(_args(tmp_path, password_file))

    assert code == EXIT_INTERNAL
    assert mailbox.closed == 1


def _explode(_uid: int) -> None:
    """
    Fail in a way the command does not expect.

    Raises:
        RuntimeError: Always.
    """
    raise RuntimeError("not a refusal")


def test_a_message_over_the_cap_is_counted_not_saved(
    tmp_path: Path,
    password_file: Path,
    connect: _Connect,
    mailbox: FakeMailbox,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The numbers the loop returns reach the text: one saved, one too large."""
    mailbox.announced[2] = MAX_MESSAGE_BYTES + 1

    code, out, _err = _run(_args(tmp_path, password_file), capsys)

    assert code == EXIT_OK
    assert _numbers(out)["Too large"] == 1
    assert len(_saved(tmp_path)) == 1


# ---------------------------------------------------------------------------
# The help (RF-08, RF-09, ADR-7)
# ---------------------------------------------------------------------------


@pytest.fixture
def wide_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Fix the width ``argparse`` wraps at, so a help text can be compared byte for byte.

    Args:
        monkeypatch (pytest.MonkeyPatch): Used to set ``COLUMNS``.
    """
    monkeypatch.setenv("COLUMNS", "80")


def _help(argv: list[str], capsys: pytest.CaptureFixture[str]) -> str:
    """
    Run ``--help`` and return what it printed.

    Args:
        argv (list[str]): The arguments, ending in ``--help``.
        capsys (pytest.CaptureFixture[str]): The capture.

    Returns:
        str: Standard output.
    """
    with pytest.raises(SystemExit) as exit_info:
        main(argv)
    assert exit_info.value.code == 0
    return capsys.readouterr().out


@pytest.mark.usefixtures("wide_terminal")
def test_the_help_of_summary_and_verdict_did_not_change(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Splitting the shared parser (ADR-7) leaves both texts byte-identical to the recorded ones."""
    assert _help(["summary", "--help"], capsys) == SUMMARY_HELP
    assert _help(["verdict", "--help"], capsys) == VERDICT_HELP


@pytest.mark.usefixtures("wide_terminal")
def test_the_help_of_fetch_says_what_it_does_with_the_network_and_the_password(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """It connects, it only reads, the password is not stored and the certificate is checked."""
    text = " ".join(_help(["fetch", "--help"], capsys).split())

    assert "connects to a server" in text
    assert "only reads" in text
    assert "never changes, moves or deletes" in text
    assert "does not mark" in text
    assert "asked for on the terminal or read from --password-file" in text
    assert "never an argument" in text
    assert "certificate is always checked" in text
    assert "--lang" in text


@pytest.mark.usefixtures("wide_terminal")
def test_the_top_level_help_calls_fetch_the_one_command_that_uses_the_network(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """RF-09: the list of commands says which one is online."""
    text = " ".join(_help(["--help"], capsys).split())

    assert "fetch" in text
    assert "the one command that uses the network" in text


@pytest.mark.usefixtures("wide_terminal")
@pytest.mark.parametrize("command", ["summary", "verdict"])
def test_the_offline_commands_have_no_network_option(
    command: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """RF-09: no host, user, password, port or fetch option on ``summary`` or ``verdict``."""
    text = _help([command, "--help"], capsys)

    for word in ("--host", "--user", "--password", "--port", "--to", "--since", "--folder"):
        assert word not in text


# ---------------------------------------------------------------------------
# The [fetch] table of --config (spec 009 ADR-12)
# ---------------------------------------------------------------------------

_FILE_FETCH = (
    'domain = "example.com"\n'
    "[fetch]\n"
    'host = "imap.file.invalid"\n'
    'user = "from-file"\n'
    "port = 143\n"
    'folder = "Reports"\n'
)


def _config(tmp_path: Path, text: str = _FILE_FETCH) -> Path:
    """
    Write a configuration file next to the test's other files.

    Args:
        tmp_path (Path): The test's own folder.
        text (str, optional): The content. Default: a ``[fetch]`` table with the four keys.

    Returns:
        Path: The file.
    """
    path = tmp_path / "mailvigil.toml"
    path.write_text(text, encoding="utf-8")
    return path


def _only_to(tmp_path: Path, password: Path, *extra: str) -> list[str]:
    """
    Build the arguments of a run that leaves the server settings to the file.

    Args:
        tmp_path (Path): The test's own folder.
        password (Path): The password file.
        *extra (str): More arguments.

    Returns:
        list[str]: ``fetch`` with ``--to`` and ``--password-file`` only, then ``extra``.
    """
    return [
        "fetch",
        "--to",
        str(tmp_path / "mail"),
        "--password-file",
        str(password),
        *extra,
    ]


def test_the_table_gives_the_connection_and_the_folder(
    tmp_path: Path,
    password_file: Path,
    connect: _Connect,
    mailbox: FakeMailbox,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """With no flag for them, host, user, port and folder come from ``[fetch]``."""
    argv = _only_to(tmp_path, password_file, "--config", str(_config(tmp_path)))

    code, _out, _err = _run(argv, capsys)

    assert code == EXIT_OK
    (call,) = connect.calls
    assert (call["host"], call["user"], call["port"]) == ("imap.file.invalid", "from-file", 143)
    assert mailbox.called("select") == [("select", "Reports")]
    assert len(_saved(tmp_path)) == 2


def test_a_flag_wins_over_the_table(
    tmp_path: Path,
    password_file: Path,
    connect: _Connect,
    mailbox: FakeMailbox,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Each flag replaces only its own key; the others still come from the file."""
    flags = ["--host", _HOST, "--port", "10993"]
    argv = _only_to(tmp_path, password_file, "--config", str(_config(tmp_path)), *flags)

    _run(argv, capsys)

    (call,) = connect.calls
    assert (call["host"], call["user"], call["port"]) == (_HOST, "from-file", 10993)
    assert mailbox.called("select") == [("select", "Reports")]


def test_the_defaults_fill_what_neither_gives(
    tmp_path: Path,
    password_file: Path,
    connect: _Connect,
    mailbox: FakeMailbox,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A table with only a host and a user leaves port 993 and ``INBOX``."""
    text = 'domain = "example.com"\n[fetch]\nhost = "h.invalid"\nuser = "u"\n'
    argv = _only_to(tmp_path, password_file, "--config", str(_config(tmp_path, text)))

    _run(argv, capsys)

    assert connect.calls[0]["port"] == 993
    assert mailbox.called("select") == [("select", "INBOX")]


def test_the_messages_of_the_same_mailbox_get_the_same_names_from_flag_or_file(
    tmp_path: Path, password_file: Path, connect: _Connect, capsys: pytest.CaptureFixture[str]
) -> None:
    """The file name tag comes from host, user and folder, wherever they were written."""
    from_flags = ["--host", "imap.file.invalid", "--user", "from-file", "--folder", "Reports"]
    _run(_only_to(tmp_path, password_file, *from_flags), capsys)
    first = [path.name for path in _saved(tmp_path)]

    _run(_only_to(tmp_path, password_file, "--config", str(_config(tmp_path))), capsys)

    assert [path.name for path in _saved(tmp_path)] == first
    assert len(first) == 2


@pytest.mark.parametrize("missing", ["host", "user"])
def test_a_host_or_user_that_nothing_gives_is_a_usage_error(
    missing: str,
    tmp_path: Path,
    password_file: Path,
    connect: _Connect,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Neither the flag nor the table: exit 2, and the message says where it can go."""
    kept = "user" if missing == "host" else "host"
    text = f'domain = "example.com"\n[fetch]\n{kept} = "x.invalid"\n'
    argv = _only_to(tmp_path, password_file, "--config", str(_config(tmp_path, text)))

    err = _usage_error(argv, capsys)

    assert f"--{missing} is required" in err
    assert "[fetch]" in err
    assert connect.calls == []


def test_a_file_in_the_current_folder_is_not_searched_for(
    tmp_path: Path,
    empty_cwd: Path,
    password_file: Path,
    connect: _Connect,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Unlike ``summary``, ``fetch`` reads a file only when ``--config`` names it (ADR-12)."""
    (empty_cwd / "mailvigil.toml").write_text(_FILE_FETCH, encoding="utf-8")

    err = _usage_error(_only_to(tmp_path, password_file), capsys)

    assert "--host is required" in err
    assert connect.calls == []


def test_a_file_without_a_table_leaves_the_flags_in_charge(
    tmp_path: Path, password_file: Path, connect: _Connect, capsys: pytest.CaptureFixture[str]
) -> None:
    """A file made for ``summary`` may be passed to ``fetch``; the table is optional."""
    config = _config(tmp_path, 'domain = "example.com"\n')

    code, _out, _err = _run(_args(tmp_path, password_file, "--config", str(config)), capsys)

    assert code == EXIT_OK
    assert connect.calls[0]["host"] == _HOST


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            'domain = "example.com"\n[fetch]\npassword = "x"\n',
            "password_not_allowed [fetch.password]",
        ),
        ('domain = "example.com"\n[fetch]\nport = 0\n', "invalid_fetch_value [fetch.port]"),
        ('domain = "example.com"\n[fetch]\nhots = "x"\n', "unknown_key [fetch.hots]"),
        ('[fetch]\nhost = "x"\n', "missing_domain [domain]"),
    ],
)
def test_a_refused_file_is_one_line_and_exit_one_before_the_password(
    text: str,
    expected: str,
    tmp_path: Path,
    connect: _Connect,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The reason and the key, the path first, no prompt and no connection."""
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(getpass, "getpass", _forbidden)
    path = _config(tmp_path, text)

    code, out, err = _run(_only_to(tmp_path, tmp_path / "unused", "--config", str(path)), capsys)

    assert code == EXIT_REFUSED
    assert out == ""
    assert err.startswith(f"mailvigil: {path}: {expected}")
    assert len(err.splitlines()) == 1
    assert connect.calls == []


def test_a_refused_file_in_portuguese_is_ascii(
    tmp_path: Path, connect: _Connect, capsys: pytest.CaptureFixture[str]
) -> None:
    """The refusal of the table follows ``--lang`` like any other."""
    text = 'domain = "example.com"\n[fetch]\npassword = "x"\n'
    argv = _only_to(tmp_path, tmp_path / "unused", "--config", str(_config(tmp_path, text)))

    code, _out, err = _run([*argv, "--lang", "pt-BR"], capsys)

    assert code == EXIT_REFUSED
    assert "a senha nunca fica no arquivo" in err
    assert err.isascii()


def test_a_missing_config_file_is_one_line_and_exit_one(
    tmp_path: Path, connect: _Connect, capsys: pytest.CaptureFixture[str]
) -> None:
    """An unreadable path is a refusal like for ``summary``, not a traceback."""
    missing = tmp_path / "absent.toml"

    code, _out, err = _run(
        _only_to(tmp_path, tmp_path / "unused", "--config", str(missing)), capsys
    )

    assert code == EXIT_REFUSED
    assert err.startswith(f"mailvigil: {missing}: unreadable")
    assert connect.calls == []
