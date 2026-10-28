"""
The three pictures of the HTML report: the meter, the stacked bar and the timeline (spec 008).

Each one is a pure function from the data and a ``Messages`` to a ``Safe``, built only with
``htmlkit``. The geometry is kept apart as small integer functions, because a picture is only as
right as the numbers under it and a test can call them alone (the project does integer arithmetic,
never floats). Three units are used throughout: tenths of a percent for the width of a meter
(``0..1000``), hundredths of a percent for the width of a bar segment (``0..10000``), and hundredths
of a unit for the plot of the timeline, which is 100 units high (``0..10000``).

Every picture states its figures in words as well: an accessible name with the numbers, the count
next to every swatch, and a table behind the timeline (ADR-9), so no meaning rests on colour alone.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Final

from mailvigil.htmlkit import Safe, el, fragment, text
from mailvigil.messages import Messages
from mailvigil.render import format_share
from mailvigil.render_verdict import measured_text, missing_text, needed_text
from mailvigil.summary import Counts, DayCounts, Period, Summary
from mailvigil.verdict import Rule, RuleId, RuleKind

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: The most columns the timeline draws (ADR-4): a longer period groups its days, never truncates.
MAX_COLUMNS: Final = 90

# The full width of a meter in tenths of a percent: one decimal is all the eye tells apart, and
# integers keep the geometry free of floats.
_TRACK: Final = 1000

# The full width of the stacked bar in hundredths of a percent: two decimals keep a segment of a
# few failures among thousands from rounding to nothing.
_BAR: Final = 10000

# The plot is 100 units high, kept in hundredths so a column of 250 messages and one of 299 differ
# on the page without a float.
_PLOT: Final = 10000

# A column with failing messages shows at least 3 units of them, so two failures among 250 messages
# are still a visible mark (T1).
_MIN_FAILING: Final = 300

# The failing segment of the stacked bar keeps this width however small its share is.
_MIN_FAILING_WIDTH: Final = "5px"

# The paths of the icons, drawn on a 24-unit grid.
_CHECK: Final = "M5 12.5l4.5 4.5L19 7.5"
_CROSS: Final = "M6 6l12 12M18 6L6 18"
_TRIANGLE: Final = "M5 0L10 9H0Z"

# ---------------------------------------------------------------------------
# Numbers as text
# ---------------------------------------------------------------------------


def percent_tenths(tenths: int) -> str:
    """
    Write a width kept in tenths of a percent.

    Args:
        tenths (int): The width, ``0..1000``.

    Returns:
        str: For example ``65.5%``.
    """
    return f"{tenths // 10}.{tenths % 10}%"


def hundredths(value: int) -> str:
    """
    Write a number kept in hundredths, for a coordinate or a width.

    Args:
        value (int): The number times 100, not negative.

    Returns:
        str: For example ``86.03``.
    """
    return f"{value // 100}.{value % 100:02d}"


# ---------------------------------------------------------------------------
# The meter (RF-03, ADR-5)
# ---------------------------------------------------------------------------


def _value_and_limit(rule: Rule) -> tuple[int, int]:
    """
    Put a rule in a unit where its value and its limit can be compared (ADR-5).

    Args:
        rule (Rule): The rule.

    Returns:
        tuple[int, int]: The value and the limit, as integers in a common unit: days, messages, the
            share of the days times 100 against the percent times the days, or the failing messages
            times 1000 against the tenths of a percent times all the messages.
    """
    if rule.id is RuleId.COVERAGE:
        return 100 * rule.measured, rule.needed * rule.whole
    if rule.id is RuleId.UNRECOGNIZED_FAILURES:
        return 1000 * rule.measured, rule.needed * rule.whole
    return rule.measured, rule.needed


def meter_geometry(rule: Rule) -> tuple[int, int]:
    """
    Place the fill and the limit mark of a meter, in tenths of a percent of its width (ADR-5).

    A rule that must reach a limit is drawn on a scale that ends at the larger of the value and the
    limit; a rule that must stay below one puts the limit at the middle, so the zone on its right
    reads as "over" at a glance. The fill can never pass the track.

    Args:
        rule (Rule): The rule.

    Returns:
        tuple[int, int]: The fill and the tick, each ``0..1000``; ``(0, 0)`` when there is
            nothing to measure against.
    """
    value, limit = _value_and_limit(rule)
    scale = max(value, limit) if rule.at_least else max(value, 2 * limit)
    if scale == 0:
        return 0, 0
    return value * _TRACK // scale, limit * _TRACK // scale


def _icon(passed: bool) -> Safe:
    """
    Draw the mark of a pass or a failure, so the result is never only a colour.

    Args:
        passed (bool): Whether the rule passes.

    Returns:
        Safe: A 14-unit SVG: a check or a cross.
    """
    return el(
        "svg",
        el("path", d=_CHECK if passed else _CROSS),
        width="14",
        height="14",
        viewBox="0 0 24 24",
        fill="none",
        stroke="currentColor",
        stroke_width="3.2",
        stroke_linecap="round",
        stroke_linejoin="round",
        aria_hidden="true",
    )


def _result_word(rule: Rule, messages: Messages) -> str:
    """
    Pick the word for the result of a rule, telling the two kinds of failure apart.

    Args:
        rule (Rule): The rule.
        messages (Messages): The language.

    Returns:
        str: The word for a pass, for a failed problem rule or for a failed data rule.
    """
    text_ = messages.verdict
    if rule.passed:
        return text_.result_pass
    return text_.result_fail if rule.kind is RuleKind.PROBLEM else text_.result_too_early


def _measured_phrase(rule: Rule, messages: Messages) -> str:
    """
    Write what a rule measured, with its unit.

    Args:
        rule (Rule): The rule.
        messages (Messages): The language.

    Returns:
        str: The figures of the text format (a share always beside its count), and the unit the text
            format leaves to its table header: messages for rules 3 to 5.
    """
    if rule.id is RuleId.VOLUME:
        return messages.common.message.of(rule.measured)
    if rule.id is RuleId.RECOGNIZED_FAILURES:
        return messages.common.failing_message.of(rule.measured)
    shown = measured_text(rule, messages)
    if rule.id is RuleId.UNRECOGNIZED_FAILURES:
        return f"{shown} {messages.html.of_messages.of(rule.whole)}"
    return shown


def _needed_phrase(rule: Rule, messages: Messages) -> str:
    """
    Say the limit of a rule in words, including which side of it is allowed.

    Args:
        rule (Rule): The rule.
        messages (Messages): The language.

    Returns:
        str: For example ``at least 28 needed``, ``at most 0.5% allowed`` or ``none allowed``.
    """
    if not rule.at_least and rule.needed == 0:
        return messages.html.none_allowed
    # ``needed_text`` already holds the unit and the rounding of the threshold: ">= 28", "<= 0.5%".
    value = needed_text(rule).split(maxsplit=1)[1]
    template = messages.html.at_least if rule.at_least else messages.html.at_most
    return template.format(value=value)


def meter(rule: Rule, messages: Messages) -> Safe:
    """
    Draw one rule as a meter against its limit.

    Args:
        rule (Rule): The rule.
        messages (Messages): The language.

    Returns:
        Safe: A list item: the name and the result as an icon and a word, a track with the fill
            and the limit mark (an image with the figures as its name), and the measure beside the
            limit. A failed data rule also says how much is missing.
    """
    name = messages.verdict.rule_names[rule.id]
    fill, tick = meter_geometry(rule)
    measured = _measured_phrase(rule, messages)
    needed = _needed_phrase(rule, messages)
    head = el(
        "div",
        el("span", text(name), class_="rname"),
        el("span", _icon(rule.passed), text(_result_word(rule, messages)), class_="rstate"),
        class_="mhead",
    )
    track = el(
        "div",
        el("div", class_="fill", style=f"width:{percent_tenths(fill)}"),
        el("div", class_="tick", style=f"left:{percent_tenths(tick)}"),
        class_="track",
        role="img",
        aria_label=messages.html.meter_label.format(name=name, measured=measured, needed=needed),
    )
    foot = [el("span", el("strong", text(measured))), el("span", text(needed))]
    if not rule.passed and rule.kind is RuleKind.DATA:
        foot.append(el("span", text(missing_text(rule, messages))))
    return el(
        "li",
        head,
        track,
        el("div", *foot, class_="mfoot"),
        class_="meter" if rule.passed else "meter fail",
    )


# ---------------------------------------------------------------------------
# The stacked bar (RF-04)
# ---------------------------------------------------------------------------


def _situations(counts: Counts, messages: Messages) -> tuple[tuple[str, str, int], ...]:
    """
    List the four situations of a message, in the order the bar draws them.

    Args:
        counts (Counts): The messages per situation.
        messages (Messages): The language.

    Returns:
        tuple[tuple[str, str, int], ...]: For each: the CSS class, the name and the count.
    """
    html = messages.html
    return (
        ("seg-ok", html.situation_ok, counts.ok),
        ("seg-dkim", html.situation_dkim, counts.dkim_only),
        ("seg-spf", html.situation_spf, counts.spf_only),
        ("seg-bad", html.situation_failing, counts.failing),
    )


def bar_widths(counts: Counts) -> tuple[int, int, int, int]:
    """
    Size the four segments of the stacked bar, in hundredths of a percent of its width.

    Args:
        counts (Counts): The messages per situation.

    Returns:
        tuple[int, int, int, int]: Passing both, DKIM only, SPF only and failing, rounded down so
            they never add up to more than the whole; all zero when there are no messages.
    """
    total = counts.total
    if total == 0:
        return 0, 0, 0, 0
    return (
        counts.ok * _BAR // total,
        counts.dkim_only * _BAR // total,
        counts.spf_only * _BAR // total,
        counts.failing * _BAR // total,
    )


def stacked_bar(counts: Counts, messages: Messages) -> Safe:
    """
    Draw the mix of the messages as one bar and a legend that prints every count and share.

    A situation with no messages takes no space in the bar but is still named in the legend. The
    failing segment keeps a minimum width, so a handful of failures among thousands stays visible.

    Args:
        counts (Counts): The messages per situation.
        messages (Messages): The language.

    Returns:
        Safe: The bar (an image whose name states the figures) followed by the legend.
    """
    total = counts.total
    situations = _situations(counts, messages)
    segments = []
    items = []
    labels = []
    for (css, name, count), width in zip(situations, bar_widths(counts), strict=True):
        share = format_share(count, total)
        if count > 0:
            style = f"width:{hundredths(width)}%"
            if css == "seg-bad":
                style += f";min-width:{_MIN_FAILING_WIDTH}"
            segments.append(el("i", class_=css, style=style))
        items.append(
            el(
                "li",
                el("b", class_=css),
                text(f"{name} "),
                el("strong", text(str(count))),
                text(f" ({share})"),
            )
        )
        labels.append(messages.html.situation_label.format(name=name, count=count, share=share))
    bar = el("div", *segments, class_="stack", role="img", aria_label="; ".join(labels))
    return fragment(bar, el("ul", *items, class_="legend"))


# ---------------------------------------------------------------------------
# The timeline: the columns (ADR-3, ADR-4)
# ---------------------------------------------------------------------------


class ColumnKind(StrEnum):
    """
    What a column of the timeline shows.

    Attributes:
        BARS (str): Reports begin in these days and brought messages: the stacked column.
        COVERED (str): A report covers these days but begins elsewhere: a short dash.
        EMPTY (str): No report touches these days: a dashed ghost column.
    """

    BARS = "bars"
    COVERED = "covered"
    EMPTY = "empty"


@dataclass(frozen=True, slots=True)
class Column:
    """
    One column of the timeline: a day, or a group of consecutive days.

    Attributes:
        first (date): The first day of the column.
        last (date): The last day of the column, the same as ``first`` for a column of one day.
        counts (Counts): The messages of the reports that begin in these days.
        reports (int): How many reports begin in these days.
        kind (ColumnKind): What the column shows.
    """

    first: date
    last: date
    counts: Counts
    reports: int
    kind: ColumnKind


def days_per_column(days_spanned: int) -> int:
    """
    Pick how many days one column holds, so the timeline never has more than ``MAX_COLUMNS``.

    Args:
        days_spanned (int): The days from the first to the last of the period.

    Returns:
        int: ``1`` up to ``MAX_COLUMNS`` days, otherwise the days over the ceiling, rounded up.
    """
    return max(1, -(-days_spanned // MAX_COLUMNS))


def _add(days: list[DayCounts]) -> tuple[Counts, int]:
    """
    Add the messages and the reports of some days.

    Args:
        days (list[DayCounts]): The days to add.

    Returns:
        tuple[Counts, int]: Their messages per situation, and how many reports begin on them.
    """
    counts = Counts(
        ok=sum(day.counts.ok for day in days),
        dkim_only=sum(day.counts.dkim_only for day in days),
        spf_only=sum(day.counts.spf_only for day in days),
        failing=sum(day.counts.failing for day in days),
    )
    return counts, sum(day.reports for day in days)


def plan_columns(
    period: Period,
    days: tuple[DayCounts, ...],
    covered: tuple[tuple[date, date], ...],
) -> tuple[Column, ...]:
    """
    Cut the period into columns and say what each one shows (ADR-3, ADR-4).

    The loop runs over the columns, at most ``MAX_COLUMNS``, never over the days of the period, and
    finds each column's messages by bisecting the sorted days: a period of centuries costs the same
    as a month.

    Args:
        period (Period): The period the reports cover.
        days (tuple[DayCounts, ...]): The messages per day a report begins on, sorted by day.
        covered (tuple[tuple[date, date], ...]): The merged intervals of the days a report touches.

    Returns:
        tuple[Column, ...]: The columns from the first day on, with no hole and no overlap.
    """
    group = days_per_column(period.days_spanned)
    begin = period.first_day.toordinal()
    end = period.last_day.toordinal()
    begins = [day.day.toordinal() for day in days]
    starts = [first.toordinal() for first, _last in covered]
    ends = [last.toordinal() for _first, last in covered]
    columns = []
    for first in range(begin, end + 1, group):
        last = min(first + group - 1, end)
        counts, reports = _add(list(days[bisect_left(begins, first) : bisect_right(begins, last)]))
        if counts.total > 0:
            kind = ColumnKind.BARS
        else:
            # The intervals are sorted and apart: the first one that ends in or after the column is
            # the only one that can touch it.
            index = bisect_left(ends, first)
            touched = index < len(ends) and starts[index] <= last
            kind = ColumnKind.COVERED if touched else ColumnKind.EMPTY
        columns.append(
            Column(date.fromordinal(first), date.fromordinal(last), counts, reports, kind)
        )
    return tuple(columns)


def column_segments(counts: Counts, tallest: int) -> tuple[tuple[str, int, int], ...]:
    """
    Stack the segments of one column from the base up (T1).

    Failing is the base and never shorter than 3 of the 100 units, so a day with two failures among
    250 messages stays visible; the others share the rest of the height by their counts, each edge
    computed from a running total so the rounding never leaves a gap or an overlap.

    Args:
        counts (Counts): The messages of the column.
        tallest (int): The messages of the tallest column, which fills the plot.

    Returns:
        tuple[tuple[str, int, int], ...]: For each segment that has height, from the base up: the
            CSS class, the top edge (``y``) and the height, in hundredths of a unit. Empty for a
            column with no messages.
    """
    total = counts.total
    if total == 0 or tallest <= 0:
        return ()
    failing = max(_MIN_FAILING, counts.failing * _PLOT // tallest) if counts.failing else 0
    # The minimum can make a very short column taller than its share, never taller than the plot.
    height = max(total * _PLOT // tallest, failing)
    rest = height - failing
    others = total - counts.failing
    top = _PLOT
    segments = []
    if failing:
        top -= failing
        segments.append(("seg-bad", top, failing))
    running = 0
    edge = 0
    for css, count in (
        ("seg-spf", counts.spf_only),
        ("seg-dkim", counts.dkim_only),
        ("seg-ok", counts.ok),
    ):
        running += count
        next_edge = rest * running // others if others else 0
        if next_edge > edge:
            top -= next_edge - edge
            segments.append((css, top, next_edge - edge))
        edge = next_edge
    return tuple(segments)


# ---------------------------------------------------------------------------
# The timeline: the markup (RF-04, ADR-9)
# ---------------------------------------------------------------------------


def _marker() -> Safe:
    """Draw the triangle that sits above a column with failing messages."""
    return el(
        "svg",
        el("path", class_="bang", d=_TRIANGLE),
        width="9",
        height="8",
        viewBox="0 0 10 9",
        aria_hidden="true",
    )


def _hatch() -> Safe:
    """
    Define the hatched fill of SPF only.

    The pattern lives in a hidden SVG outside the plot, so the stroke rule of the plot's rectangles
    does not draw lines across the pattern tile.

    Returns:
        Safe: A zero-size SVG holding the pattern ``hatch``.
    """
    pattern = el(
        "pattern",
        el("rect", class_="hatch-bg", width="5", height="5"),
        el("line", class_="hatch-ln", x1="0", y1="0", x2="0", y2="5"),
        id="hatch",
        width="5",
        height="5",
        patternUnits="userSpaceOnUse",
        patternTransform="rotate(45)",
    )
    return el(
        "svg",
        el("defs", pattern),
        width="0",
        height="0",
        style="position:absolute",
        aria_hidden="true",
    )


def _bars(column: Column, index: int, tallest: int) -> list[Safe]:
    """
    Draw the shapes of one column in the plot.

    Args:
        column (Column): The column.
        index (int): Its position from the left; each column is 10 units wide with a 2-unit gap.
        tallest (int): The messages of the tallest column.

    Returns:
        list[Safe]: The stacked rectangles, the short dash or the ghost column.
    """
    x = str(10 * index + 1)
    if column.kind is ColumnKind.COVERED:
        return [el("rect", class_="cov", x=x, y="97", width="8", height="3")]
    if column.kind is ColumnKind.EMPTY:
        return [el("rect", class_="ghost", x=x, y="0", width="8", height="100")]
    shapes = []
    for css, top, height in column_segments(column.counts, tallest):
        extra = {"fill": "url(#hatch)"} if css == "seg-spf" else {}
        shapes.append(
            el(
                "rect",
                class_=css,
                x=x,
                y=hundredths(top),
                width="8",
                height=hundredths(height),
                **extra,
            )
        )
    return shapes


def _row_label(column: Column, messages: Messages) -> str:
    """Name a column by its day, or by its first and last day when it holds several."""
    if column.first == column.last:
        return column.first.isoformat()
    return messages.html.range_label.format(
        first=column.first.isoformat(), last=column.last.isoformat()
    )


def _numbers(columns: tuple[Column, ...], messages: Messages) -> Safe:
    """
    Write the table behind the chart, with the figures of every column (ADR-9).

    Args:
        columns (tuple[Column, ...]): The columns.
        messages (Messages): The language.

    Returns:
        Safe: A ``details`` element that opens a scrollable, focusable table.
    """
    html = messages.html
    names = [name for _css, name, _count in _situations(Counts(), messages)]
    head = el(
        "tr",
        el("th", text(html.col_day), scope="col"),
        *[el("th", text(name), scope="col", class_="n") for name in names],
    )
    rows = [
        el(
            "tr",
            el("th", text(_row_label(column, messages)), scope="row"),
            *[
                el("td", text(str(count)), class_="n")
                for count in (
                    column.counts.ok,
                    column.counts.dkim_only,
                    column.counts.spf_only,
                    column.counts.failing,
                )
            ],
        )
        for column in columns
    ]
    table = el("table", el("thead", head), el("tbody", *rows))
    region = el(
        "div", table, class_="scroll", role="region", aria_label=html.numbers_region, tabindex="0"
    )
    return el("details", el("summary", text(html.show_numbers)), region, class_="nums")


def _key(messages: Messages) -> Safe:
    """Write the key to every mark of the timeline."""
    html = messages.html
    swatches = [
        el("li", el("b", class_=css), text(name))
        for css, name, _count in _situations(Counts(), messages)
    ]
    swatches.append(el("li", _marker(), el("span", text(html.legend_failing_day))))
    swatches.append(el("li", el("b", class_="ghostsw"), text(html.legend_no_report)))
    swatches.append(el("li", el("b", class_="covsw"), text(html.legend_covered)))
    return el("ul", *swatches, class_="legend")


def timeline(summary: Summary, messages: Messages) -> Safe:
    """
    Draw the messages day by day, split by situation, with the table behind it (T1).

    Args:
        summary (Summary): The summary, with its period, days and covered intervals.
        messages (Messages): The language.

    Returns:
        Safe: The caption, the key, the chart (the failure marks, the plot, the date labels), the
            note on the scale and the table. Empty when there is no period to draw.
    """
    period = summary.period
    if period is None:
        return fragment()
    columns = plan_columns(period, summary.days, summary.covered)
    group = days_per_column(period.days_spanned)
    tallest = max(column.counts.total for column in columns)
    failing = sum(1 for column in columns if column.counts.failing > 0)
    first, last = period.first_day, period.last_day
    middle = date.fromordinal(first.toordinal() + period.days_spanned // 2)
    labels = list(dict.fromkeys(day.isoformat() for day in (first, middle, last)))

    flags = el(
        "div",
        *[
            el("span", *([_marker()] if column.counts.failing > 0 else []), class_="fl")
            for column in columns
        ],
        class_="flags",
        aria_hidden="true",
    )
    width = str(10 * len(columns))
    grid = [el("line", class_="grid", x1="0", y1=y, x2=width, y2=y) for y in ("0", "50")]
    shapes = [
        shape for index, column in enumerate(columns) for shape in _bars(column, index, tallest)
    ]
    plot = el(
        "svg",
        *grid,
        *shapes,
        class_="plot",
        viewBox=f"0 0 {width} 100",
        preserveAspectRatio="none",
        role="img",
        aria_label=messages.html.timeline_label.of(
            len(columns), first=first.isoformat(), last=last.isoformat(), failing=failing
        ),
    )
    axis = el("div", *[el("span", text(label)) for label in labels], class_="xl")
    return fragment(
        _hatch(),
        el("p", text(messages.html.column_note.of(group)), class_="sub"),
        _key(messages),
        el("div", flags, plot, axis, class_="chart"),
        el("p", text(messages.html.scale_note.format(tallest=tallest)), class_="note"),
        _numbers(columns, messages),
    )
