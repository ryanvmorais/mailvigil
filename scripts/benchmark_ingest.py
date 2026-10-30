"""
Time the reading of report files: the benchmark behind the cost of cleaning and parsing (issue #70).

Not part of the test run: a timing is no assertion, and a slow machine must not turn a green suite
red. The script writes synthetic reports into a temporary folder, reads them with the same entry
point as the CLI and prints how long that took. Nothing is added to ``pyproject.toml``:

    uv run python scripts/benchmark_ingest.py                  # 300 files of 100 records
    uv run python scripts/benchmark_ingest.py --files 50 --records 200 --repeat 5

It prints the best of ``--repeat`` runs, because the fastest run is the one the least disturbed by
the rest of the machine. Compare two numbers taken on the same machine, one before and one after a
change; one number alone says little. The reports are invented: every domain and address is from a
documentation range.
"""

from __future__ import annotations

import argparse
import gzip
import tempfile
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from mailvigil.reports import ingest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# The domain of every synthetic report; a reserved name (RFC 2606), so no real domain is involved.
DOMAIN = "example.com"

# A fixed "now" a day after the periods below, so the future-end check never fires and two runs read
# the same thing.
_NOW = datetime(2026, 6, 2, tzinfo=UTC)

# The Unix time of 2026-06-01 00:00 UTC, the start of every synthetic period.
_PERIOD_START = 1780272000

# ---------------------------------------------------------------------------
# Synthetic reports
# ---------------------------------------------------------------------------


def _record(number: int) -> str:
    """
    Build one ``<record>`` with the fields a real reporter fills.

    Args:
        number (int): The position of the record, to vary the address.

    Returns:
        str: The XML of the record.
    """
    address = f"192.0.2.{number % 250 + 1}"
    return (
        f"<record><row><source_ip>{address}</source_ip><count>{number % 40 + 1}</count>"
        "<policy_evaluated><disposition>none</disposition><dkim>pass</dkim><spf>pass</spf>"
        "</policy_evaluated></row>"
        f"<identifiers><header_from>{DOMAIN}</header_from></identifiers>"
        "<auth_results>"
        f"<dkim><domain>{DOMAIN}</domain><selector>selector{number % 3}</selector>"
        "<result>pass</result></dkim>"
        f"<spf><domain>{DOMAIN}</domain><result>pass</result></spf>"
        "</auth_results></record>"
    )


def _report(index: int, records: int) -> bytes:
    """
    Build one aggregate report of a day.

    Args:
        index (int): The report number, which sets the reporter, the id and the day.
        records (int): How many records it holds.

    Returns:
        bytes: The document, UTF-8 encoded.
    """
    begin = _PERIOD_START
    body = "".join(_record(number) for number in range(records))
    text = (
        "<feedback><version>1.0</version><report_metadata>"
        f"<org_name>Reporter {index % 10}</org_name><email>reports@mail.example.net</email>"
        f"<report_id>report-{index}</report_id>"
        f"<date_range><begin>{begin}</begin><end>{begin + 86399}</end></date_range>"
        "</report_metadata><policy_published>"
        f"<domain>{DOMAIN}</domain><p>none</p><pct>100</pct></policy_published>"
        f"{body}</feedback>"
    )
    return text.encode("utf-8")


def write_reports(folder: Path, files: int, records: int) -> None:
    """
    Write ``files`` gzipped reports into ``folder``.

    Args:
        folder (Path): An existing folder.
        files (int): How many report files.
        records (int): How many records in each.
    """
    end = _PERIOD_START + 86399
    for index in range(files):
        # The provider name pattern, which is how a folder search recognizes a report.
        name = f"reporter{index % 10}!{DOMAIN}!{_PERIOD_START}!{end}!{index}.xml.gz"
        (folder / name).write_bytes(gzip.compress(_report(index, records), mtime=0))


# ---------------------------------------------------------------------------
# Timing
# ---------------------------------------------------------------------------


def best_time(folder: Path, repeat: int) -> tuple[float, int]:
    """
    Read the folder ``repeat`` times and keep the fastest run.

    Args:
        folder (Path): The folder of reports.
        repeat (int): How many runs.

    Returns:
        tuple[float, int]: The seconds of the fastest run and the number of records it read.
    """
    best = float("inf")
    records = 0
    for _ in range(repeat):
        start = time.perf_counter()
        result = ingest([folder], DOMAIN, now=_NOW)
        best = min(best, time.perf_counter() - start)
        records = sum(len(report.records) for report in result.reports)
    return best, records


def main(argv: Sequence[str] | None = None) -> None:
    """
    Run the benchmark and print one line with the result.

    Args:
        argv (Sequence[str] | None, optional): The arguments; ``None`` reads ``sys.argv``.
    """
    parser = argparse.ArgumentParser(description="Time the reading of synthetic DMARC reports.")
    parser.add_argument("--files", type=int, default=300, help="report files to write (300)")
    parser.add_argument("--records", type=int, default=100, help="records in each file (100)")
    parser.add_argument("--repeat", type=int, default=3, help="runs; the fastest is kept (3)")
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory() as name:
        folder = Path(name)
        write_reports(folder, args.files, args.records)
        seconds, records = best_time(folder, args.repeat)

    print(
        f"{args.files} files, {records} records: {seconds:.2f} s, "
        f"{records / seconds:,.0f} records/s (best of {args.repeat})"
    )


if __name__ == "__main__":
    main()
