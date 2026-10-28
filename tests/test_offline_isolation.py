"""
Tests that the offline commands stay offline (spec 009, RF-09, ADR-7).

Isolation: each case runs a fresh ``python -I`` interpreter, because ``sys.modules`` of the test
process already holds whatever other tests imported. The report is synthetic (built by the
``conftest.py`` factories in ``tmp_path``) and the ``fetch`` case never opens a socket: it stops at
the user name, which the adapter checks before it connects. ``ssl`` and ``socket`` are not asserted,
because other standard library modules may load them.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tests.cli_helpers import LONG, RecordXml, ReportXml, write_config, write_window

# The modules that mean "this process can reach a mail server".
_NETWORK = ("imaplib", "mailvigil.fetch.imap")

# Runs the commands given as JSON lists in argv[1:], and prints which network modules were loaded
# before the first one and after each, as the last line of standard output.
_SCRIPT = f"""
import json, sys
import mailvigil.cli

network = {_NETWORK!r}


def loaded():
    return [name for name in network if name in sys.modules]


report = {{"after_import": loaded(), "after": []}}
for text in sys.argv[1:]:
    try:
        mailvigil.cli.main(json.loads(text))
    except SystemExit:
        pass
    report["after"].append(loaded())
print(json.dumps(report))
"""


def _run(*commands: list[str]) -> dict[str, list[str]]:
    """
    Run the commands one after the other in a fresh isolated interpreter.

    Args:
        *commands (list[str]): The arguments of each ``main`` call.

    Returns:
        dict[str, list[str]]: The network modules loaded after the import (``after_import``) and
            after each command (``after``, one entry per command).
    """
    done = subprocess.run(
        [sys.executable, "-I", "-c", _SCRIPT, *[json.dumps(command) for command in commands]],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    last_line = done.stdout.strip().splitlines()[-1]
    report: dict[str, list[str]] = json.loads(last_line)
    return report


def test_importing_the_cli_and_reading_reports_loads_no_network_code(
    tmp_path: Path, make_report_xml: ReportXml, make_record_xml: RecordXml
) -> None:
    """``import mailvigil.cli``, ``summary`` and ``verdict`` leave ``imaplib`` unloaded."""
    folder = write_window(tmp_path / "reports", make_report_xml, make_record_xml, days=LONG)
    config = str(write_config(tmp_path / "config.toml"))

    report = _run(
        ["summary", str(folder), "--config", config],
        ["verdict", str(folder), "--config", config],
        ["verdict", str(folder), "--config", config, "--json"],
    )

    assert report["after_import"] == []
    assert report["after"] == [[], [], []]


def test_fetch_loads_the_network_code_only_when_it_runs(tmp_path: Path) -> None:
    """The adapter is imported by ``fetch`` and by nothing before it."""
    secret = tmp_path / "secret.txt"
    secret.write_text("invented-password\n", encoding="ascii")
    secret.chmod(0o600)
    fetch = [
        "fetch",
        "--host",
        "imap.example.invalid",
        "--user",
        "bad\nuser",
        "--to",
        str(tmp_path / "mail"),
        "--password-file",
        str(secret),
    ]

    report = _run(fetch)

    assert report["after_import"] == []
    assert sorted(report["after"][0]) == sorted(_NETWORK)
