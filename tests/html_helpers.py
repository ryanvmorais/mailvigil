"""
Helpers shared by the tests of the HTML report: three invented runs and a small page reader.

The runs are built by hand as frozen values and judged by ``judge``, so no report file is needed;
domains, services and addresses are invented (``example.com``, ``example.net``; ``192.0.2.0/24``,
``198.51.100.0/24``, ``203.0.113.0/24``; RNF-07). ``Page`` reads a finished document with the
standard library's parser, the way the spec asks the markup to be judged: by what a parser finds,
never by comparing whole strings.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path

from mailvigil.reports import PolicyPublished, Reason, SkippedFile
from mailvigil.senders import Outcome
from mailvigil.summary import (
    Counts,
    DayCounts,
    FailingSource,
    Period,
    SenderRow,
    Summary,
)
from mailvigil.verdict import Verdict, judge

# ---------------------------------------------------------------------------
# Three invented runs
# ---------------------------------------------------------------------------

_FIRST = date(2026, 9, 1)


def make_period(first: date, length: int) -> Period:
    """
    Build the period of daily reports, one for each of ``length`` days from ``first``.

    Args:
        first (date): The first day.
        length (int): How many days, at least 1.

    Returns:
        Period: The period, from midnight of the first day to midnight after the last.
    """
    last = first + timedelta(days=length - 1)
    return Period(
        begin=datetime(first.year, first.month, first.day, tzinfo=UTC),
        end=datetime(last.year, last.month, last.day, tzinfo=UTC) + timedelta(days=1),
        first_day=first,
        last_day=last,
        days_spanned=length,
        days_with_reports=length,
    )


def make_days(first: date, length: int, per_day: Counts) -> tuple[DayCounts, ...]:
    """
    Build one report per day, each with the same messages.

    Args:
        first (date): The first day.
        length (int): How many days.
        per_day (Counts): The messages of each report.

    Returns:
        tuple[DayCounts, ...]: The days, sorted.
    """
    return tuple(DayCounts(first + timedelta(days=i), 1, per_day) for i in range(length))


def _scale(counts: Counts, times: int) -> Counts:
    """
    Multiply every count, to get the totals of ``times`` identical days.

    Args:
        counts (Counts): The messages of one day.
        times (int): How many days.

    Returns:
        Counts: The messages of all of them.
    """
    return Counts(
        ok=counts.ok * times,
        dkim_only=counts.dkim_only * times,
        spf_only=counts.spf_only * times,
        failing=counts.failing * times,
    )


def ready_summary() -> Summary:
    """
    Build a month of clean daily reports from one recognized sender: every rule passes.

    Returns:
        Summary: 29 days, 1218 messages, none failing, a few that pass by DKIM only.
    """
    per_day = Counts(ok=40, dkim_only=2)
    totals = _scale(per_day, 29)
    return Summary(
        domain="example.com",
        selectors_configured=1,
        reports=29,
        reporters=1,
        period=make_period(_FIRST, 29),
        policy=PolicyPublished(domain="example.com", p="none"),
        totals=totals,
        recognized_messages=totals.total,
        senders=(SenderRow(Outcome.KNOWN, service="Example Mail", counts=totals),),
        days=make_days(_FIRST, 29, per_day),
        covered=((_FIRST, _FIRST + timedelta(days=28)),),
    )


def early_summary() -> Summary:
    """
    Build five days of reports: not enough evidence yet, and one file that was left out.

    Returns:
        Summary: 5 days, 210 messages, none failing, one skipped file and two duplicates.
    """
    per_day = Counts(ok=40, spf_only=2)
    totals = _scale(per_day, 5)
    return Summary(
        domain="example.com",
        selectors_configured=1,
        reports=5,
        reporters=1,
        period=make_period(_FIRST, 5),
        policy=PolicyPublished(domain="example.com", p="quarantine", pct=50),
        totals=totals,
        recognized_messages=totals.total,
        senders=(SenderRow(Outcome.KNOWN, service="Example Mail", counts=totals),),
        skipped=(SkippedFile(Path("notes.txt"), Reason.NOT_A_REPORT, "not a report"),),
        skipped_by_reason=((Reason.NOT_A_REPORT, 1),),
        duplicates=2,
        other_domain=1,
        days=make_days(_FIRST, 5, per_day),
        covered=((_FIRST, _FIRST + timedelta(days=4)),),
    )


def not_ready_summary() -> Summary:
    """
    Build a month in which a recognized sender fails on two days, and an unknown address too.

    Returns:
        Summary: 29 days, one recognized failing source and two unrecognized ones, the policy
            changed during the period.
    """
    clean = Counts(ok=40, dkim_only=2)
    bad = Counts(ok=36, dkim_only=2, failing=6)
    days = [
        DayCounts(_FIRST + timedelta(days=i), 1, bad if i in (3, 4) else clean) for i in range(29)
    ]
    totals = Counts(
        ok=sum(d.counts.ok for d in days),
        dkim_only=sum(d.counts.dkim_only for d in days),
        failing=sum(d.counts.failing for d in days),
    )
    return Summary(
        domain="example.com",
        selectors_configured=1,
        reports=29,
        reporters=2,
        period=make_period(_FIRST, 29),
        policy=PolicyPublished(domain="example.com", p="none", sp="reject", np="reject"),
        earlier_p=("quarantine",),
        totals=totals,
        recognized_messages=totals.total - 3,
        senders=(
            SenderRow(
                Outcome.KNOWN,
                service="Example Mail",
                counts=Counts(ok=totals.ok, dkim_only=totals.dkim_only, failing=10),
            ),
            SenderRow(Outcome.UNKNOWN, source_ip="203.0.113.7", counts=Counts(failing=2)),
        ),
        failing=(
            FailingSource(
                Outcome.KNOWN,
                "192.0.2.10",
                10,
                service="Example Mail",
                selectors=("s1",),
                dkim=("fail",),
                spf=("softfail",),
                override_reasons=("forwarded",),
            ),
            FailingSource(Outcome.UNKNOWN, "203.0.113.7", 2),
        ),
        days=tuple(days),
        covered=((_FIRST, _FIRST + timedelta(days=28)),),
    )


def judged(summary: Summary) -> tuple[Summary, Verdict]:
    """
    Pair a summary with its verdict, as the command does.

    Args:
        summary (Summary): The summary.

    Returns:
        tuple[Summary, Verdict]: The summary and ``judge`` of it.
    """
    return summary, judge(summary)


# ---------------------------------------------------------------------------
# A page reader
# ---------------------------------------------------------------------------


class Page(HTMLParser):
    """
    A finished document, read with the standard library's parser.

    Attributes:
        elements (list[tuple[str, dict[str, str | None]]]): Every start tag, in order, with its
            attributes.
        headings (list[tuple[int, str]]): The level and the text of every heading, in order.
        texts (list[str]): Every text node, stripped, empty ones left out.
        comments (list[str]): Every comment.
        terms (list[str]): The text of every ``dt``, in order.
        stylesheet (str): The text of the ``style`` element.
    """

    def __init__(self, document: str) -> None:
        """
        Parse a document.

        Args:
            document (str): The whole page.
        """
        super().__init__(convert_charrefs=True)
        self.elements: list[tuple[str, dict[str, str | None]]] = []
        self.headings: list[tuple[int, str]] = []
        self.texts: list[str] = []
        self.comments: list[str] = []
        self.terms: list[str] = []
        self.stylesheet = ""
        self._stack: list[str] = []
        self._heading = ""
        self.feed(document)
        self.close()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Record a start tag."""
        self.elements.append((tag, dict(attrs)))
        self._stack.append(tag)
        if tag in {"h1", "h2", "h3", "h4"}:
            self._heading = ""

    def handle_endtag(self, tag: str) -> None:
        """Close the innermost open element of this tag."""
        if tag in {"h1", "h2", "h3", "h4"}:
            self.headings.append((int(tag[1]), self._heading.strip()))
        if tag in self._stack:
            while self._stack.pop() != tag:
                pass

    def handle_data(self, data: str) -> None:
        """Record a text node, or the stylesheet."""
        if self._stack and self._stack[-1] == "style":
            self.stylesheet += data
            return
        if data.strip():
            self.texts.append(data.strip())
            if self._stack and self._stack[-1] == "dt":
                self.terms.append(data.strip())
        if any(tag in {"h1", "h2", "h3", "h4"} for tag in self._stack):
            self._heading += data

    def handle_comment(self, data: str) -> None:
        """Record a comment."""
        self.comments.append(data)

    def count(self, tag: str) -> int:
        """
        Count the elements of a tag.

        Args:
            tag (str): The tag.

        Returns:
            int: How many start tags it has.
        """
        return sum(1 for name, _attrs in self.elements if name == tag)

    def with_class(self, name: str) -> list[dict[str, str | None]]:
        """
        Find the elements that carry a class.

        Args:
            name (str): The class.

        Returns:
            list[dict[str, str | None]]: Their attributes, in order.
        """
        return [
            attrs for _tag, attrs in self.elements if name in (attrs.get("class") or "").split()
        ]

    @property
    def text(self) -> str:
        """All the visible text, one space between the nodes."""
        return " ".join(self.texts)
