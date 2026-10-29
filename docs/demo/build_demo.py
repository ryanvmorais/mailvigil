"""
Build the README demo: invented reports, a real run of the CLI and the recording of it.

The script writes two folders of synthetic aggregate reports for ``example.com`` (a period that is
NOT READY for ``p=reject`` and a later one that is READY), runs ``mailvigil verdict`` on each and
writes ``verdict.cast`` (asciinema v2) from what the CLI really printed. Nothing here is a real
report: the names are invented and every address is from a documentation range.

The picture files are made from the output of this script with two tools that are not part of the
project (nothing is added to ``pyproject.toml``):

    uv run python docs/demo/build_demo.py WORKDIR
    npx svg-term-cli --in docs/demo/verdict.cast --out docs/images/<name>.svg \\
        --window --no-cursor --width 80 --height 29
    uv run python docs/demo/tidy_svg.py docs/images/<name>.svg    # pins the letters to the grid

The page captures come from WORKDIR/before, with an absolute path for ``--screenshot``:

    uv run mailvigil verdict --config mailvigil.toml reports/ --html > report.html
    chrome --headless=new --screenshot=/abs/light.png --window-size=1280,1278 \\
        file:///.../report.html

For the dark one, copy ``report.html`` with ``@media (prefers-color-scheme:dark)`` replaced by
``@media all`` (the page picks its palette by that query alone) and capture the copy the same way.
"""

from __future__ import annotations

import gzip
import json
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


DOMAIN = "example.com"

#: The configuration both runs read: two recognized senders, named from their DKIM selectors.
CONFIG = f"""domain = "{DOMAIN}"

[senders]
newsletter = "Example Mailer (newsletters)"
mailbox = "Example Mail (staff mailboxes)"
"""

#: Relative traffic by weekday (Monday first), so the day-by-day chart is not flat.
WEEKDAY_WEIGHTS = (100, 110, 105, 115, 95, 40, 30)

#: The first day of each period; the earlier one is NOT READY, the later one is READY.
BEFORE_FIRST = date(2026, 8, 20)
AFTER_FIRST = date(2026, 9, 18)

#: Seconds between two typed characters, and the pause before the output of a command appears.
TYPING_STEP = 0.035
RUN_PAUSE = 0.7

# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


def _spread(total: int, weights: list[int]) -> list[int]:
    """
    Split a total over days in proportion to weights, keeping the sum exact.

    Args:
        total (int): The sum the result must have.
        weights (list[int]): One non-negative weight per day.

    Returns:
        list[int]: One count per day, summing to ``total``.
    """
    whole = sum(weights)
    counts = [total * weight // whole for weight in weights]
    # The remainder goes to days that have weight, so a day with none stays at zero.
    weighted = [index for index, weight in enumerate(weights) if weight]
    for turn in range(total - sum(counts)):
        counts[weighted[turn % len(weighted)]] += 1
    return counts


def _record(ip: str, count: int, dkim: tuple[str, str], spf: str) -> str:
    """
    Build one ``<record>`` element for a source.

    Args:
        ip (str): The sending address.
        count (int): The number of messages.
        dkim (tuple[str, str]): The DKIM selector and result.
        spf (str): The SPF result.

    Returns:
        str: The XML of the record.
    """
    selector, result = dkim
    return (
        f"<record><row><source_ip>{ip}</source_ip><count>{count}</count><policy_evaluated>"
        f"<disposition>none</disposition><dkim>{result}</dkim><spf>{spf}</spf>"
        "</policy_evaluated></row>"
        f"<identifiers><header_from>{DOMAIN}</header_from></identifiers><auth_results>"
        f"<dkim><domain>{DOMAIN}</domain><selector>{selector}</selector><result>{result}</result>"
        f"</dkim><spf><domain>{DOMAIN}</domain><result>{spf}</result></spf></auth_results>"
        "</record>"
    )


def _write_period(folder: Path, first: date, days: int, plan: dict[str, list[int]]) -> None:
    """
    Write one report per day, named the way providers name them.

    Args:
        folder (Path): The folder that receives the ``.xml.gz`` files.
        first (date): The first day covered.
        days (int): How many days to write.
        plan (dict[str, list[int]]): Messages per day for each source key.
    """
    folder.mkdir(parents=True, exist_ok=True)
    for index in range(days):
        day = first + timedelta(days=index)
        begin = int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp())
        end = begin + 86399
        records = [
            _record("198.51.100.10", plan["newsletter"][index], ("newsletter", "pass"), "pass"),
            _record("198.51.100.50", plan["mailbox"][index], ("mailbox", "pass"), "fail"),
        ]
        if plan["sender_fail"][index]:
            fail = ("k1.v2", "fail")
            records.append(_record("203.0.113.5", plan["sender_fail"][index], fail, "fail"))
        if plan["sender_pass"][index]:
            ok = ("k1.v2", "pass")
            records.append(_record("203.0.113.5", plan["sender_pass"][index], ok, "pass"))
        if plan["stray"][index]:
            records.append(_record("192.0.2.77", plan["stray"][index], ("x", "none"), "fail"))
        xml = (
            "<feedback><report_metadata><org_name>Example Receiver</org_name>"
            f"<email>reports@receiver.example.net</email><report_id>{day.isoformat()}</report_id>"
            f"<date_range><begin>{begin}</begin><end>{end}</end></date_range></report_metadata>"
            f"<policy_published><domain>{DOMAIN}</domain><p>none</p><sp>none</sp><pct>100</pct>"
            f"</policy_published>{''.join(records)}</feedback>"
        )
        name = f"receiver.example.net!{DOMAIN}!{begin}!{end}.xml.gz"
        (folder / name).write_bytes(gzip.compress(xml.encode("utf-8"), mtime=0))


def _weights(first: date, days: int) -> list[int]:
    """
    Give each day its weekday weight.

    Args:
        first (date): The first day covered.
        days (int): How many days.

    Returns:
        list[int]: One weight per day.
    """
    return [WEEKDAY_WEIGHTS[(first + timedelta(days=i)).weekday()] for i in range(days)]


def build_reports(workdir: Path) -> None:
    """
    Write the two folders of invented reports and the configuration next to each.

    Args:
        workdir (Path): The folder that receives ``before/`` and ``after/``.
    """
    # Before: 29 days, 7056 messages, an unrecognized source that fails 56 of them (0.8%).
    days = 29
    weights = _weights(BEFORE_FIRST, days)
    fails = [1 if index % 3 == 0 else 0 for index in range(days)]  # about one day in three
    _write_period(
        workdir / "before" / "reports",
        BEFORE_FIRST,
        days,
        {
            "newsletter": _spread(6300, weights),
            "mailbox": _spread(700, weights),
            "sender_fail": _spread(56, fails),
            "sender_pass": [0] * days,
            "stray": [0] * days,
        },
    )
    # After: 31 days, the same sender now signs correctly, two stray failures remain (0.03%).
    days = 31
    weights = _weights(AFTER_FIRST, days)
    _write_period(
        workdir / "after" / "reports",
        AFTER_FIRST,
        days,
        {
            "newsletter": _spread(6700, weights),
            "mailbox": _spread(760, weights),
            "sender_fail": [0] * days,
            "sender_pass": _spread(120, weights),
            "stray": [2 if index == 11 else 0 for index in range(days)],
        },
    )
    for case in ("before", "after"):
        (workdir / case / "mailvigil.toml").write_text(CONFIG, encoding="utf-8")


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------


def _run(case: Path, args: list[str]) -> tuple[str, int]:
    """
    Run the CLI in a case folder, as the user would.

    Args:
        case (Path): The folder with ``reports/`` and ``mailvigil.toml``.
        args (list[str]): The arguments after ``mailvigil``.

    Returns:
        tuple[str, int]: What the command printed on standard output, and its exit code.
    """
    # The package has no ``__main__``, so the entry point is called the way the script does.
    entry = "import sys; from mailvigil.cli import main; sys.exit(main())"
    done = subprocess.run(
        [sys.executable, "-c", entry, *args],
        cwd=case,
        capture_output=True,
        text=True,
        check=False,
    )
    return done.stdout, done.returncode


class Cast:
    """
    An asciinema v2 recording being written.

    Attributes:
        events (list[tuple[float, str]]): The ``(time, text)`` pairs written so far.
        clock (float): The time of the last event, in seconds.
    """

    PROMPT = "\x1b[32m$\x1b[0m "

    def __init__(self) -> None:
        """Start an empty recording."""
        self.events: list[tuple[float, str]] = []
        self.clock = 0.4

    def write(self, text: str, after: float = 0.0) -> None:
        """
        Add one event.

        Args:
            text (str): What the terminal receives.
            after (float, optional): Seconds since the previous event.
        """
        self.clock += after
        self.events.append((round(self.clock, 3), text))

    def type_command(self, command: str) -> None:
        """
        Show a prompt and type a command one character at a time, then press Enter.

        Args:
            command (str): The text typed.
        """
        self.write(self.PROMPT)
        for char in command:
            self.write(char, TYPING_STEP)
        self.write("\r\n", 0.35)

    def print_output(self, text: str) -> None:
        """
        Show the output of a command, one line at a time.

        Args:
            text (str): What the command printed.
        """
        self.clock += RUN_PAUSE
        for line in text.rstrip("\n").split("\n"):
            self.write(line + "\r\n", 0.03)

    def clear(self) -> None:
        """Clear the screen, as ``clear`` does."""
        self.type_command("clear")
        self.write("\x1b[H\x1b[2J", 0.05)

    def dump(self, width: int, height: int) -> str:
        """
        Render the recording as the text of a ``.cast`` file.

        Args:
            width (int): Columns of the terminal.
            height (int): Rows of the terminal.

        Returns:
            str: The header and one JSON line per event.
        """
        header = {"version": 2, "width": width, "height": height, "title": "mailvigil verdict"}
        lines = [json.dumps(header)]
        lines += [json.dumps([time, "o", text]) for time, text in self.events]
        return "\n".join(lines) + "\n"


def record(workdir: Path) -> str:
    """
    Run both periods through ``verdict`` and write the recording of the two answers.

    Args:
        workdir (Path): The folder that holds ``before/`` and ``after/``.

    Returns:
        str: The text of the ``.cast`` file.
    """
    verdict = ["verdict", "--config", "mailvigil.toml", "reports/"]
    cast = Cast()
    for case, comment in (
        ("before", None),
        ("after", "# the sender fixed its DKIM key; a month of newer reports later"),
    ):
        if comment:
            cast.clear()
            cast.type_command(comment)
        cast.type_command("mailvigil " + " ".join(verdict))
        out, code = _run(workdir / case, verdict)
        cast.print_output(out)
        cast.type_command("echo $?")
        cast.print_output(str(code))
        cast.write(Cast.PROMPT, 0.2)
        cast.write("", 4.0)
    return cast.dump(width=80, height=29)


def main() -> None:
    """Build the reports in the folder named on the command line and write ``verdict.cast``."""
    workdir = Path(sys.argv[1])
    build_reports(workdir)
    target = Path(__file__).with_name("verdict.cast")
    target.write_text(record(workdir), encoding="utf-8", newline="\n")
    print(f"reports in {workdir}, recording in {target}")


if __name__ == "__main__":
    main()
