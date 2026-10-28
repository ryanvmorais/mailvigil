"""
Tests of ``html_charts``: the meter, the stacked bar and the timeline of the HTML report (spec 008,
RF-03, RF-04, RF-07, ADR-4, ADR-5, ADR-9).

Isolation: pure functions over built values, no disk and no command. The geometry is tested alone,
as integers, because the pictures are only as right as the numbers under them; the markup is tested
by what a reader gets (the figures, the words, the labels) and by counting elements, never by
comparing a whole SVG. ``Rule``, ``Counts`` and ``Summary`` are built by hand here, with invented
dates and counts.
"""

from __future__ import annotations

import itertools
import re
import time
from datetime import UTC, date, datetime, timedelta

import pytest

from mailvigil.html_charts import (
    MAX_COLUMNS,
    Column,
    ColumnKind,
    bar_widths,
    column_segments,
    days_per_column,
    hundredths,
    meter,
    meter_geometry,
    percent_tenths,
    plan_columns,
    stacked_bar,
    timeline,
)
from mailvigil.messages import ENGLISH, PORTUGUESE, Messages
from mailvigil.render import format_share
from mailvigil.summary import Counts, DayCounts, Period, Summary
from mailvigil.verdict import Rule, RuleId, RuleKind

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

_FIRST = date(2026, 9, 1)


def make_rule(
    rule_id: RuleId,
    measured: int,
    whole: int = 0,
    *,
    needed: int | None = None,
    passed: bool = True,
    missing: int = 0,
) -> Rule:
    """
    Build a rule the way ``verdict`` builds it, with the thresholds of the real rules.

    Args:
        rule_id (RuleId): Which of the five rules.
        measured (int): The value found.
        whole (int): The denominator of a share. Default: 0.
        needed (int | None): The threshold; ``None`` takes the real one. Default: ``None``.
        passed (bool): Whether the rule passes. Default: ``True``.
        missing (int): What a failed data rule lacks. Default: 0.

    Returns:
        Rule: The rule.
    """
    real = {
        RuleId.PERIOD: (28, True, RuleKind.DATA),
        RuleId.COVERAGE: (80, True, RuleKind.DATA),
        RuleId.VOLUME: (1000, True, RuleKind.DATA),
        RuleId.RECOGNIZED_FAILURES: (0, False, RuleKind.PROBLEM),
        RuleId.UNRECOGNIZED_FAILURES: (5, False, RuleKind.PROBLEM),
    }
    limit, at_least, kind = real[rule_id]
    return Rule(
        id=rule_id,
        kind=kind,
        measured=measured,
        whole=whole,
        needed=limit if needed is None else needed,
        at_least=at_least,
        passed=passed,
        missing=missing,
    )


def make_summary(
    days: dict[date, Counts],
    *,
    first: date = _FIRST,
    last: date | None = None,
    covered: tuple[tuple[date, date], ...] | None = None,
) -> Summary:
    """
    Build a summary whose reports each begin on one day and last until the end of it.

    Args:
        days (dict[date, Counts]): The messages of the one report that begins on each day.
        first (date): The first day of the period. Default: 2026-09-01.
        last (date | None): The last day of the period; ``None`` is the last day with a report.
            Default: ``None``.
        covered (tuple[tuple[date, date], ...] | None): The merged covered intervals; ``None`` is
            one interval per day with a report. Default: ``None``.

    Returns:
        Summary: The summary, with its period, totals, days and covered intervals.
    """
    last_day = last or max(days)
    intervals = covered if covered is not None else tuple((day, day) for day in sorted(days))
    total = Counts(
        ok=sum(c.ok for c in days.values()),
        dkim_only=sum(c.dkim_only for c in days.values()),
        spf_only=sum(c.spf_only for c in days.values()),
        failing=sum(c.failing for c in days.values()),
    )
    spanned = (last_day - first).days + 1
    period = Period(
        begin=datetime(first.year, first.month, first.day, tzinfo=UTC),
        end=datetime(last_day.year, last_day.month, last_day.day, tzinfo=UTC) + timedelta(days=1),
        first_day=first,
        last_day=last_day,
        days_spanned=spanned,
        days_with_reports=sum((b - a).days + 1 for a, b in intervals),
    )
    return Summary(
        domain="example.com",
        reports=len(days),
        reporters=1,
        period=period,
        totals=total,
        days=tuple(DayCounts(day, 1, days[day]) for day in sorted(days)),
        covered=intervals,
    )


def month(failing_days: frozenset[int] = frozenset({2, 3}), length: int = 29) -> Summary:
    """
    Build a summary with one daily report for each day of a period.

    Args:
        failing_days (frozenset[int]): The days (1-based) whose report has failing messages.
            Default: days 2 and 3.
        length (int): The days of the period. Default: 29.

    Returns:
        Summary: The summary.
    """
    days = {
        _FIRST
        + timedelta(days=index): Counts(
            ok=250, dkim_only=40, failing=6 if index + 1 in failing_days else 0
        )
        for index in range(length)
    }
    return make_summary(days)


def attribute(markup: str, name: str) -> str:
    """The value of the first ``name="..."`` attribute in a piece of markup."""
    found = re.search(rf'{name}="([^"]*)"', markup)
    assert found, f"no {name} in {markup[:200]}"
    return found.group(1)


_BOTH = pytest.mark.parametrize("messages", [ENGLISH, PORTUGUESE], ids=["en", "pt-BR"])

# ---------------------------------------------------------------------------
# The meter: geometry (ADR-5)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rule", "expected"),
    [
        # The numbers of the approved mockup.
        (make_rule(RuleId.PERIOD, 29), (1000, 965)),
        (make_rule(RuleId.UNRECOGNIZED_FAILURES, 48, 7323, passed=False), (655, 500)),
        (make_rule(RuleId.COVERAGE, 29, 29), (1000, 800)),
        (make_rule(RuleId.VOLUME, 7323), (1000, 136)),
        # A value exactly at the limit.
        (make_rule(RuleId.PERIOD, 28), (1000, 1000)),
        (make_rule(RuleId.UNRECOGNIZED_FAILURES, 36, 7200), (500, 500)),
        # A value far above the limit: the fill is capped, the tick is pushed to the left.
        (make_rule(RuleId.UNRECOGNIZED_FAILURES, 7000, 7323, passed=False), (1000, 5)),
        (make_rule(RuleId.VOLUME, 10**15), (1000, 0)),
        # Nothing measured.
        (make_rule(RuleId.PERIOD, 0, passed=False), (0, 1000)),
        (make_rule(RuleId.VOLUME, 0, passed=False), (0, 1000)),
        # Rule 4 allows nothing: any failure fills the bar, the tick sits at the left edge.
        (make_rule(RuleId.RECOGNIZED_FAILURES, 0), (0, 0)),
        (make_rule(RuleId.RECOGNIZED_FAILURES, 3, passed=False), (1000, 0)),
        # No whole to measure against: an empty meter, never a division by zero.
        (make_rule(RuleId.COVERAGE, 0, 0, passed=False), (0, 0)),
        (make_rule(RuleId.UNRECOGNIZED_FAILURES, 0, 0), (0, 0)),
    ],
)
def test_the_meter_geometry_follows_the_table_of_the_design(
    rule: Rule, expected: tuple[int, int]
) -> None:
    assert meter_geometry(rule) == expected


@pytest.mark.parametrize("rule_id", list(RuleId))
@pytest.mark.parametrize("measured", [0, 1, 5, 28, 29, 1000, 10**6, 10**18])
@pytest.mark.parametrize("whole", [0, 1, 28, 7323, 10**9])
def test_the_fill_and_the_tick_never_leave_the_track(
    rule_id: RuleId, measured: int, whole: int
) -> None:
    fill, tick = meter_geometry(make_rule(rule_id, measured, whole))
    assert 0 <= fill <= 1000
    assert 0 <= tick <= 1000


def test_tenths_of_a_percent_are_written_with_one_decimal() -> None:
    assert percent_tenths(0) == "0.0%"
    assert percent_tenths(655) == "65.5%"
    assert percent_tenths(1000) == "100.0%"


def test_hundredths_are_written_with_two_decimals() -> None:
    assert hundredths(0) == "0.00"
    assert hundredths(8603) == "86.03"
    assert hundredths(10000) == "100.00"
    assert hundredths(5) == "0.05"


# ---------------------------------------------------------------------------
# The meter: markup (RF-03, RF-07)
# ---------------------------------------------------------------------------


@_BOTH
def test_a_passing_meter_names_the_rule_the_figures_and_the_limit(messages: Messages) -> None:
    markup = meter(make_rule(RuleId.PERIOD, 29), messages)
    assert messages.verdict.rule_names[RuleId.PERIOD] in markup
    track = re.search(r'<div class="track"[^>]*>', markup)
    assert track
    assert 'role="img"' in track.group(0)
    label = attribute(track.group(0), "aria-label")
    assert "29" in label
    assert "28" in label
    assert 'style="width:100.0%"' in markup
    assert 'style="left:96.5%"' in markup


def test_a_passing_meter_says_pass_with_an_icon_and_a_word_and_is_not_marked_failed() -> None:
    markup = meter(make_rule(RuleId.PERIOD, 29), ENGLISH)
    state = re.search(r'<span class="rstate">(.*?)</span>', markup)
    assert state
    assert "<svg" in state.group(1)
    assert ENGLISH.verdict.result_pass in state.group(1)
    assert 'class="meter"' in markup
    assert "fail" not in attribute(markup, "class")


def test_a_failed_problem_rule_is_marked_failed_with_its_own_word() -> None:
    rule = make_rule(RuleId.UNRECOGNIZED_FAILURES, 48, 7323, passed=False)
    markup = meter(rule, ENGLISH)
    assert 'class="meter fail"' in markup
    assert ENGLISH.verdict.result_fail in markup
    assert 'style="width:65.5%"' in markup
    assert 'style="left:50.0%"' in markup


def test_a_failed_data_rule_says_too_early_and_how_much_is_missing() -> None:
    rule = make_rule(RuleId.PERIOD, 27, passed=False, missing=1)
    markup = meter(rule, ENGLISH)
    assert 'class="meter fail"' in markup
    assert ENGLISH.verdict.result_too_early in markup
    assert "need 1 more day" in markup


def test_a_passing_rule_does_not_say_what_is_missing() -> None:
    assert "more" not in meter(make_rule(RuleId.PERIOD, 29), ENGLISH)


def test_a_stay_below_meter_says_so_in_words() -> None:
    unrecognized = meter(make_rule(RuleId.UNRECOGNIZED_FAILURES, 48, 7323, passed=False), ENGLISH)
    assert "at most 0.5% allowed" in unrecognized
    recognized = meter(make_rule(RuleId.RECOGNIZED_FAILURES, 0), ENGLISH)
    assert "none allowed" in recognized


def test_a_reach_for_meter_says_so_in_words() -> None:
    assert "at least 28 needed" in meter(make_rule(RuleId.PERIOD, 29), ENGLISH)
    assert "at least 80% needed" in meter(make_rule(RuleId.COVERAGE, 29, 29), ENGLISH)
    assert "at least 1000 needed" in meter(make_rule(RuleId.VOLUME, 7323), ENGLISH)


@pytest.mark.parametrize(
    ("rule", "text"),
    [
        (make_rule(RuleId.PERIOD, 29), "29 days"),
        (make_rule(RuleId.COVERAGE, 27, 29, passed=True), "27 of 29"),
        (make_rule(RuleId.VOLUME, 7323), "7323 messages"),
        (make_rule(RuleId.RECOGNIZED_FAILURES, 2, passed=False), "2 failing messages"),
        (
            make_rule(RuleId.UNRECOGNIZED_FAILURES, 48, 7323, passed=False),
            "of 7323 messages",
        ),
    ],
)
def test_every_meter_prints_its_measure_with_the_unit(rule: Rule, text: str) -> None:
    assert text in meter(rule, ENGLISH)


def test_the_share_of_rule_five_is_the_one_of_the_text_format() -> None:
    """A failure that rounds to its own limit never reads as ``0.5%`` beside ``FAIL`` (005)."""
    rule = make_rule(RuleId.UNRECOGNIZED_FAILURES, 37, 7323, passed=False)
    assert "&gt;0.5%" in meter(rule, ENGLISH)


@_BOTH
def test_a_meter_is_a_list_item_with_ascii_markup(messages: Messages) -> None:
    for rule_id in RuleId:
        markup = meter(make_rule(rule_id, 1, 10), messages)
        assert markup.startswith("<li ")
        assert markup.endswith("</li>")
        assert markup.isascii()


def test_the_portuguese_meter_speaks_portuguese() -> None:
    markup = meter(make_rule(RuleId.UNRECOGNIZED_FAILURES, 48, 7323, passed=False), PORTUGUESE)
    assert "maximo permitido" in markup
    assert PORTUGUESE.verdict.result_fail in markup


# ---------------------------------------------------------------------------
# The stacked bar (RF-04)
# ---------------------------------------------------------------------------

_MIX = Counts(ok=6300, dkim_only=975, spf_only=0, failing=48)


def test_the_widths_of_the_bar_are_hundredths_of_a_percent_that_never_pass_the_whole() -> None:
    widths = bar_widths(_MIX)
    assert widths == (8603, 1331, 0, 65)
    assert sum(widths) <= 10000


def test_a_bar_of_nothing_has_no_width() -> None:
    assert bar_widths(Counts()) == (0, 0, 0, 0)


@pytest.mark.parametrize(
    "counts",
    [Counts(ok=1), Counts(failing=1), Counts(ok=3, dkim_only=3, spf_only=3, failing=1), _MIX],
)
def test_the_widths_never_pass_the_whole_for_any_mix(counts: Counts) -> None:
    assert sum(bar_widths(counts)) <= 10000


def test_the_legend_prints_the_count_and_the_share_of_the_text_format() -> None:
    markup = stacked_bar(_MIX, ENGLISH)
    legend = markup[markup.index('<ul class="legend">') :]
    for name, count in (
        (ENGLISH.html.situation_ok, _MIX.ok),
        (ENGLISH.html.situation_dkim, _MIX.dkim_only),
        (ENGLISH.html.situation_spf, _MIX.spf_only),
        (ENGLISH.html.situation_failing, _MIX.failing),
    ):
        assert name in legend
        assert f"<strong>{count}</strong> ({format_share(count, _MIX.total)})" in legend


def test_a_zero_segment_takes_no_space_and_is_still_named_in_the_legend() -> None:
    markup = stacked_bar(_MIX, ENGLISH)
    stack = markup[: markup.index("</div>")]
    assert stack.count("<i ") == 3
    assert "seg-spf" not in stack
    assert f"{ENGLISH.html.situation_spf} <strong>0</strong> (0%)" in markup


def test_a_tiny_failing_share_keeps_a_minimum_width() -> None:
    markup = stacked_bar(Counts(ok=999_999, failing=1), ENGLISH)
    failing = re.search(r'<i class="seg-bad"[^>]*>', markup)
    assert failing
    assert "min-width:5px" in failing.group(0)


def test_only_the_failing_segment_has_a_minimum_width() -> None:
    markup = stacked_bar(_MIX, ENGLISH)
    assert markup.count("min-width") == 1


def test_the_bar_states_the_figures_in_its_accessible_name() -> None:
    markup = stacked_bar(_MIX, ENGLISH)
    label = attribute(markup, "aria-label")
    assert 'role="img"' in markup
    for count in (_MIX.ok, _MIX.dkim_only, _MIX.spf_only, _MIX.failing):
        assert str(count) in label
    assert ENGLISH.html.situation_failing in label


def test_the_four_situations_differ_by_more_than_colour() -> None:
    """The hatched segment is not a hue: a legend swatch has its own class for each."""
    markup = stacked_bar(Counts(ok=1, dkim_only=1, spf_only=1, failing=1), ENGLISH)
    classes = re.findall(r'<b class="([^"]+)"', markup)
    assert classes == ["seg-ok", "seg-dkim", "seg-spf", "seg-bad"]


def test_a_bar_with_no_messages_does_not_divide_by_zero() -> None:
    markup = stacked_bar(Counts(), ENGLISH)
    assert "<i " not in markup
    assert "<strong>0</strong> (0%)" in markup


@_BOTH
def test_the_bar_is_ascii_in_both_languages(messages: Messages) -> None:
    assert stacked_bar(_MIX, messages).isascii()


# ---------------------------------------------------------------------------
# The timeline: columns (ADR-4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("spanned", "group"),
    [(1, 1), (29, 1), (90, 1), (91, 2), (180, 2), (181, 3), (365, 5), (366, 5), (36525, 406)],
)
def test_the_group_is_the_days_spanned_over_the_ceiling_rounded_up(
    spanned: int, group: int
) -> None:
    assert days_per_column(spanned) == group


@pytest.mark.parametrize("spanned", [*range(1, 400), 1000, 3650, 36525, 3_000_000])
def test_there_are_never_more_columns_than_the_ceiling(spanned: int) -> None:
    group = days_per_column(spanned)
    assert -(-spanned // group) <= MAX_COLUMNS


def _span_summary(length: int) -> Summary:
    """
    Build a summary with a report on the first day and one on the last.

    Args:
        length (int): The days of the period.

    Returns:
        Summary: The summary, with the days between them uncovered.
    """
    last = _FIRST + timedelta(days=length - 1)
    days = {_FIRST: Counts(ok=10), last: Counts(ok=20, failing=1)}
    return make_summary(days, last=last, covered=((_FIRST, _FIRST), (last, last)))


def _plan(summary: Summary) -> tuple[Column, ...]:
    """Plan the columns of a summary that has a period."""
    assert summary.period
    return plan_columns(summary.period, summary.days, summary.covered)


def test_a_month_is_one_column_per_day() -> None:
    columns = _plan(month())
    assert len(columns) == 29
    assert all(column.first == column.last for column in columns)
    assert columns[0].first == _FIRST
    assert columns[-1].last == _FIRST + timedelta(days=28)


def test_ninety_days_are_one_column_each_and_ninety_one_are_groups_of_two() -> None:
    assert len(_plan(_span_summary(90))) == 90
    columns = _plan(_span_summary(91))
    assert len(columns) == 46
    assert columns[0].last == columns[0].first + timedelta(days=1)
    assert columns[-1].first == columns[-1].last == _FIRST + timedelta(days=90)


def test_a_year_is_groups_of_five() -> None:
    columns = _plan(_span_summary(365))
    assert len(columns) == 73
    assert all((c.last - c.first).days == 4 for c in columns)


def test_a_century_is_at_most_the_ceiling_in_bounded_time() -> None:
    summary = _span_summary(36525)
    started = time.perf_counter()
    markup = timeline(summary, ENGLISH)
    assert time.perf_counter() - started < 2
    assert len(_plan(summary)) <= MAX_COLUMNS
    # 90 columns of at most four elements, a few lines and a table: never one per day.
    assert markup.count("<") < 6000


def test_the_columns_cover_the_period_without_a_hole_or_an_overlap() -> None:
    for length in (1, 2, 29, 91, 100, 365):
        columns = _plan(_span_summary(length))
        assert columns[0].first == _FIRST
        assert columns[-1].last == _FIRST + timedelta(days=length - 1)
        for before, after in itertools.pairwise(columns):
            assert after.first == before.last + timedelta(days=1)


def test_the_counts_of_the_columns_add_up_to_the_totals() -> None:
    for length in (29, 91, 365):
        summary = month(length=length)
        columns = _plan(summary)
        assert sum(c.counts.ok for c in columns) == summary.totals.ok
        assert sum(c.counts.dkim_only for c in columns) == summary.totals.dkim_only
        assert sum(c.counts.failing for c in columns) == summary.totals.failing
        assert sum(c.reports for c in columns) == summary.reports


def test_a_day_with_a_report_that_begins_there_is_a_bar_column() -> None:
    kinds = [column.kind for column in _plan(month())]
    assert kinds == [ColumnKind.BARS] * 29


def _gap_summary() -> Summary:
    """
    Build five days: a report on day 1 that covers days 1 to 3, nothing on day 4, one on day 5.

    Returns:
        Summary: The summary.
    """
    last = _FIRST + timedelta(days=4)
    return make_summary(
        {_FIRST: Counts(ok=10), last: Counts(ok=10)},
        last=last,
        covered=((_FIRST, _FIRST + timedelta(days=2)), (last, last)),
    )


def test_a_covered_day_is_a_dash_and_a_day_in_no_interval_is_a_ghost() -> None:
    kinds = [column.kind for column in _plan(_gap_summary())]
    assert kinds == [
        ColumnKind.BARS,
        ColumnKind.COVERED,
        ColumnKind.COVERED,
        ColumnKind.EMPTY,
        ColumnKind.BARS,
    ]


def test_a_group_with_a_covered_day_but_no_begin_is_covered() -> None:
    # 100 days: groups of two. The report begins on day 0 and covers days 0 to 3.
    last = _FIRST + timedelta(days=99)
    summary = make_summary(
        {_FIRST: Counts(ok=10), last: Counts(ok=10)},
        last=last,
        covered=((_FIRST, _FIRST + timedelta(days=3)), (last, last)),
    )
    kinds = [column.kind for column in _plan(summary)]
    assert kinds[:3] == [ColumnKind.BARS, ColumnKind.COVERED, ColumnKind.EMPTY]
    assert kinds[-1] == ColumnKind.BARS


def test_a_summary_built_the_old_way_has_only_ghost_columns() -> None:
    summary = make_summary({_FIRST: Counts(ok=1)}, last=_FIRST + timedelta(days=2))
    old = Summary(domain="example.com", period=summary.period)
    assert [c.kind for c in _plan(old)] == [ColumnKind.EMPTY] * 3


# ---------------------------------------------------------------------------
# The timeline: the segments of a column (T1)
# ---------------------------------------------------------------------------


def test_the_failing_segment_is_the_base_and_never_shorter_than_three_units() -> None:
    segments = column_segments(Counts(ok=253, dkim_only=40, failing=6), 299)
    name, y, height = segments[0]
    assert name == "seg-bad"
    assert y + height == 10000
    assert height == 300


def test_a_failing_share_above_three_units_is_drawn_to_scale() -> None:
    segments = column_segments(Counts(ok=50, failing=50), 100)
    assert segments[0] == ("seg-bad", 5000, 5000)


def test_a_column_with_no_failures_has_no_failing_segment() -> None:
    names = [name for name, _y, _h in column_segments(Counts(ok=250, dkim_only=40), 299)]
    assert names == ["seg-dkim", "seg-ok"]


def test_the_segments_stack_from_the_base_in_the_order_failing_spf_dkim_ok() -> None:
    segments = column_segments(Counts(ok=40, dkim_only=30, spf_only=20, failing=10), 100)
    assert [name for name, _y, _h in segments] == ["seg-bad", "seg-spf", "seg-dkim", "seg-ok"]


@pytest.mark.parametrize(
    "counts",
    [
        Counts(ok=253, dkim_only=40, failing=6),
        Counts(ok=1, failing=1),
        Counts(failing=2),
        Counts(ok=7, dkim_only=7, spf_only=7, failing=7),
        Counts(ok=999_999, failing=1),
        Counts(dkim_only=1),
    ],
)
def test_the_segments_are_contiguous_from_the_base_and_never_leave_the_plot(
    counts: Counts,
) -> None:
    tallest = max(counts.total, 1_000_000)
    segments = column_segments(counts, tallest)
    top = 10000
    for _name, y, height in segments:
        assert height > 0
        assert y + height == top
        top = y
    assert top >= 0


def test_the_tallest_column_reaches_the_top() -> None:
    segments = column_segments(Counts(ok=250, dkim_only=49, failing=0), 299)
    assert segments[-1][1] == 0


def test_a_column_taller_than_its_share_because_of_the_minimum_stays_inside_the_plot() -> None:
    segments = column_segments(Counts(failing=1), 1_000_000)
    assert segments == (("seg-bad", 9700, 300),)


def test_a_column_of_nothing_has_no_segments() -> None:
    assert column_segments(Counts(), 299) == ()
    assert column_segments(Counts(ok=5), 0) == ()


# ---------------------------------------------------------------------------
# The timeline: markup (RF-04, RF-07, ADR-9)
# ---------------------------------------------------------------------------


def test_a_month_draws_one_column_per_day_in_a_plot_ten_units_wide_each() -> None:
    markup = timeline(month(), ENGLISH)
    plot = re.search(r'<svg class="plot"[^>]*>', markup)
    assert plot
    assert attribute(plot.group(0), "viewBox") == "0 0 290 100"
    assert len(re.findall(r'<span class="fl">', markup)) == 29


def test_a_triangle_sits_above_exactly_the_columns_with_failures() -> None:
    markup = timeline(month(frozenset({2, 3, 9})), ENGLISH)
    flags = re.findall(r'<span class="fl">(.*?)</span>', markup)
    marked = [index + 1 for index, flag in enumerate(flags) if 'class="bang"' in flag]
    assert marked == [2, 3, 9]


def test_a_month_without_failures_has_no_triangle_above_any_column() -> None:
    flags = re.findall(r'<span class="fl">(.*?)</span>', timeline(month(frozenset()), ENGLISH))
    assert len(flags) == 29
    assert not any("bang" in flag for flag in flags)


def test_spf_only_is_the_hatched_segment_and_the_others_are_solid() -> None:
    days = {_FIRST: Counts(ok=10, dkim_only=5, spf_only=5, failing=1)}
    markup = timeline(make_summary(days), ENGLISH)
    plot = markup[markup.index('<svg class="plot"') : markup.index("</svg>", markup.index("plot"))]
    assert plot.count('fill="url(#hatch)"') == 1
    assert 'class="seg-spf" ' in plot or 'class="seg-spf"' in plot


def test_the_hatch_is_defined_once_in_a_hidden_svg_outside_the_plot() -> None:
    markup = timeline(month(), ENGLISH)
    assert markup.count('id="hatch"') == 1
    assert markup.index('id="hatch"') < markup.index('<svg class="plot"')


def test_a_covered_day_is_a_short_dash_and_a_missing_day_is_a_ghost_column() -> None:
    markup = timeline(_gap_summary(), ENGLISH)
    assert markup.count('<rect class="cov"') == 2
    assert markup.count('<rect class="ghost"') == 1


def test_the_x_labels_are_the_first_the_middle_and_the_last_date() -> None:
    markup = timeline(month(), ENGLISH)
    labels = re.search(r'<div class="xl">(.*?)</div>', markup)
    assert labels
    assert re.findall(r"<span>([^<]*)</span>", labels.group(1)) == [
        "2026-09-01",
        "2026-09-15",
        "2026-09-29",
    ]


def test_a_period_of_one_day_has_one_label() -> None:
    markup = timeline(make_summary({_FIRST: Counts(ok=5)}), ENGLISH)
    labels = re.search(r'<div class="xl">(.*?)</div>', markup)
    assert labels
    assert re.findall(r"<span>([^<]*)</span>", labels.group(1)) == ["2026-09-01"]


def test_the_table_behind_the_chart_has_one_row_per_column_with_the_same_figures() -> None:
    summary = month()
    markup = timeline(summary, ENGLISH)
    table = markup[markup.index("<details") :]
    assert 'class="nums"' in table
    assert ENGLISH.html.show_numbers in table
    rows = re.findall(r"<tbody>(.*?)</tbody>", table)[0].split("</tr>")[:-1]
    assert len(rows) == 29
    first = re.findall(r"<t[hd][^>]*>([^<]*)</t[hd]>", rows[0])
    assert first == ["2026-09-01", "250", "40", "0", "0"]
    second = re.findall(r"<t[hd][^>]*>([^<]*)</t[hd]>", rows[1])
    assert second == ["2026-09-02", "250", "40", "0", "6"]


def test_the_table_of_a_grouped_chart_names_the_range_of_each_column() -> None:
    markup = timeline(_span_summary(91), ENGLISH)
    table = markup[markup.index("<details") :]
    assert "2026-09-01 to 2026-09-02" in table
    assert "2026-11-30" in table


def test_the_table_is_a_focusable_region_with_header_cells_that_have_a_scope() -> None:
    markup = timeline(month(), ENGLISH)
    assert 'role="region"' in markup
    assert 'tabindex="0"' in markup
    assert markup.count('<th scope="col"') == 5
    assert '<th scope="row"' in markup


def test_the_caption_says_how_many_days_a_column_is_and_when_a_report_counts() -> None:
    single = timeline(month(), ENGLISH)
    assert "Each column is one day" in single
    assert "begins" in single
    grouped = timeline(_span_summary(365), ENGLISH)
    assert "Each column is 5 days" in grouped
    assert "begins" in grouped


def test_the_note_names_the_tallest_column() -> None:
    assert "The tallest column had 296" in timeline(month(frozenset({1})), ENGLISH)


def test_the_plot_has_an_accessible_name_with_the_figures() -> None:
    markup = timeline(month(frozenset({2, 3, 9})), ENGLISH)
    plot = re.search(r'<svg class="plot"[^>]*>', markup)
    assert plot
    label = attribute(plot.group(0), "aria-label")
    assert 'role="img"' in plot.group(0)
    assert "2026-09-01" in label
    assert "2026-09-29" in label
    assert "29 columns" in label
    assert "3 with failing messages" in label


def test_the_key_names_every_mark() -> None:
    markup = timeline(month(), ENGLISH)
    for sentence in (
        ENGLISH.html.situation_ok,
        ENGLISH.html.situation_dkim,
        ENGLISH.html.situation_spf,
        ENGLISH.html.situation_failing,
        ENGLISH.html.legend_failing_day,
        ENGLISH.html.legend_no_report,
        ENGLISH.html.legend_covered,
    ):
        assert sentence in markup


def test_no_period_draws_nothing() -> None:
    assert timeline(Summary(domain="example.com"), ENGLISH) == ""


def test_two_calls_give_the_same_markup() -> None:
    assert timeline(month(), ENGLISH) == timeline(month(), ENGLISH)


@_BOTH
def test_the_timeline_is_ascii_in_both_languages(messages: Messages) -> None:
    assert timeline(month(), messages).isascii()


def test_the_portuguese_timeline_speaks_portuguese() -> None:
    markup = timeline(month(), PORTUGUESE)
    assert "Cada coluna e um dia" in markup
    assert PORTUGUESE.html.show_numbers in markup
