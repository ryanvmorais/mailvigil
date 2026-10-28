"""
Helpers shared by the tests that run the commands through ``main(argv)``.

They write synthetic files in a folder the test owns: a configuration that names the selector of
the synthetic reports, and one daily report of ``example.com`` for each day of a window. Domains
and addresses are invented (``example.com``, ``example.net``; ``192.0.2.0/24``; RNF-06).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from mailvigil.verdict import MIN_DAYS_SPANNED, MIN_MESSAGES

# Seconds in a day; the synthetic reports are one per day.
_DAY = 86400

# The first second of the synthetic window.
_START = 1790000000

#: The days a "long" window spans: exactly the minimum the first rule asks for.
LONG = MIN_DAYS_SPANNED

# Messages per daily report that put the whole window over the volume rule with room to spare.
_PER_DAY = -(-MIN_MESSAGES // LONG) + 10

ReportXml = Callable[..., bytes]
RecordXml = Callable[..., str]


def write_config(path: Path) -> Path:
    """
    Write a configuration file that names the selector of the synthetic reports.

    Args:
        path (Path): Where to write the file.

    Returns:
        Path: The file written.
    """
    path.write_text(
        'domain = "example.com"\n\n[senders]\ns1 = "Example Mail"\n',
        encoding="utf-8",
    )
    return path


def write_window(
    folder: Path,
    make_report_xml: ReportXml,
    make_record_xml: RecordXml,
    *,
    days: int,
    count: int = _PER_DAY,
    failing: bool = False,
    policy: str = "none",
) -> Path:
    """
    Write one daily report of ``example.com`` for each day of a window.

    Args:
        folder (Path): The folder to create and fill.
        make_report_xml (ReportXml): The report factory of ``conftest.py``.
        make_record_xml (RecordXml): The record factory of ``conftest.py``.
        days (int): How many consecutive days to cover, one report each.
        count (int, optional): The messages in each report. Default: enough for the volume rule.
        failing (bool, optional): ``True`` makes every message fail the DMARC evaluation while the
            ``s1`` signature itself passes, so the configuration of ``write_config`` recognizes the
            sender. Default: ``False``.
        policy (str, optional): The ``p`` the reports publish. Default: ``none``.

    Returns:
        Path: The folder.
    """
    folder.mkdir()
    result = "fail" if failing else "pass"
    record = make_record_xml(
        count=count,
        dkim_evaluated=result,
        spf_evaluated=result,
        dkim=(("example.com", "s1", "pass"),),
        spf=(("example.com", result),),
    )
    for day in range(days):
        begin = _START + day * _DAY
        end = begin + _DAY - 1
        name = f"example.net!example.com!{begin}!{end}.xml"
        report = make_report_xml(
            report_id=f"r{day}", begin=begin, end=end, records=[record], p=policy
        )
        (folder / name).write_bytes(report)
    return folder
