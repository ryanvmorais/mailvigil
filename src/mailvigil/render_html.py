"""
The HTML report: a ``Summary`` and a ``Verdict`` turned into one self-contained page (spec 008).

This is a third way of printing what the other two renderers print, and it follows their rule: the
command decides the exit code first and this module only lays out. ``render_html`` is a pure
function. It reads no clock, no environment and no file, and it shows no path and no file name, so
a page e-mailed to a manager carries nothing of the machine it was made on.

Every sentence is read from the ``Messages`` it is given, and the ones the text format already says
(the reason, the next step, the figures, the notes, what was left out) come from the helpers of
``render_verdict`` and the catalog, never retyped here (ADR-2). Every piece of markup is built with
``htmlkit``, so a text that came from a report cannot become an element (ADR-1); the dynamic
strings also pass through ``fit``, as in the other formats, so a control character or a very long
run never reaches the page.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from mailvigil import __version__
from mailvigil.html_charts import meter, stacked_bar, timeline
from mailvigil.html_style import CONTENT_SECURITY_POLICY, STYLESHEET
from mailvigil.htmlkit import Safe, document, el, finish, fragment, raw, text
from mailvigil.messages import ENGLISH, Messages
from mailvigil.render import address, fit
from mailvigil.render_verdict import (
    answer_phrase,
    left_out_parts,
    next_sentence,
    note_sentence,
    reason_sentence,
)
from mailvigil.senders import Outcome
from mailvigil.summary import FailingSource, SenderRow, Summary
from mailvigil.verdict import Answer, Rule, RuleId, RuleKind, Verdict

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# How much of a third party's text the page shows: the domain is the longest legal name, an address
# the longest IPv6 one, and a service, a selector or a policy value stays short enough for a line.
_DOMAIN_MAX = 253
_ADDRESS_MAX = 45
_NAME_MAX = 60
_VALUE_MAX = 30

# Failing sources shown in a group before the line that still counts the others (the summary's
# limit); the senders table shows every row (RF-05).
_LIMIT = 10

# The paths of the icons, drawn on a 24-unit grid.
_SHIELD: Final = "M12 2.5l8 3v6c0 5-3.4 8.7-8 10-4.6-1.3-8-5-8-10v-6z"
_CHECK: Final = "M5 12.5l4.5 4.5L19 7.5"
_CROSS: Final = "M6 6l12 12M18 6L6 18"
_CLOCK: Final = "M12 6.5V12l3.5 2"

# What the mark of the banner draws for each answer, and the class that colours the banner.
_MARK: Final = {Answer.READY: _CHECK, Answer.NOT_READY: _CROSS, Answer.TOO_EARLY: _CLOCK}
_TONE: Final = {
    Answer.READY: "verdict ready",
    Answer.NOT_READY: "verdict",
    Answer.TOO_EARLY: "verdict early",
}

# ---------------------------------------------------------------------------
# Small pieces
# ---------------------------------------------------------------------------


def _icon(path: str, size: int, width: str) -> Safe:
    """
    Draw one icon: a single stroked path on the 24-unit grid.

    Args:
        path (str): The path data, a constant of this module.
        size (int): The side in pixels.
        width (str): The stroke width.

    Returns:
        Safe: An SVG that is hidden from screen readers; the words beside it carry the meaning.
    """
    return el(
        "svg",
        el("path", d=path),
        width=str(size),
        height=str(size),
        viewBox="0 0 24 24",
        fill="none",
        stroke="currentColor",
        stroke_width=width,
        stroke_linecap="round",
        stroke_linejoin="round",
        aria_hidden="true",
    )


def _clean(value: str, width: int) -> Safe:
    """
    Escape a text from a third party after cleaning and cutting it.

    Args:
        value (str): The text.
        width (int): The most characters it may take.

    Returns:
        Safe: The text of a node.
    """
    return text(fit(value, width))


def _chip(label: str, *, bad: bool = False) -> Safe:
    """
    Write a small label beside a name.

    Args:
        label (str): The words.
        bad (bool, optional): Whether it marks a failure. Default: ``False``.

    Returns:
        Safe: The chip; a failure is told by its word as well as by its colour.
    """
    return el("span", text(label), class_="chip bad" if bad else "chip")


def _section(heading: str, key: str, *children: Safe, level: str = "h2") -> Safe:
    """
    Wrap content in a section that its heading names.

    Args:
        heading (str): The title.
        key (str): A short id for the heading, unique on the page.
        *children (Safe): The content.
        level (str, optional): The heading element. Default: ``h2``.

    Returns:
        Safe: A card with the heading and the content.
    """
    return el(
        "section",
        el(level, text(heading), id=key),
        *children,
        class_="card",
        aria_labelledby=key,
    )


def _rule(verdict: Verdict, rule_id: RuleId) -> Rule:
    """
    Pick one rule of a verdict.

    Args:
        verdict (Verdict): The verdict.
        rule_id (RuleId): The rule wanted.

    Returns:
        Rule: The rule with that id.
    """
    return next(rule for rule in verdict.rules if rule.id is rule_id)


# ---------------------------------------------------------------------------
# Header and banner (RF-02)
# ---------------------------------------------------------------------------


def _header(summary: Summary, messages: Messages) -> Safe:
    """
    Write the header: the name of the tool and what the page is about.

    Args:
        summary (Summary): The summary.
        messages (Messages): The language.

    Returns:
        Safe: The domain, the period and the reports, in one line.
    """
    words = messages.summary
    period = summary.period
    if period is None:
        when = words.no_period
    else:
        when = words.period.of(
            period.days_with_reports,
            first=period.first_day.isoformat(),
            last=period.last_day.isoformat(),
            days=messages.common.day.of(period.days_spanned),
        )
    reports = words.reports_line.format(
        reports=summary.reports, reporters=words.reporter.of(summary.reporters)
    )
    meta = " \u00b7 ".join([fit(summary.domain, _DOMAIN_MAX), when, reports])
    brand = el("div", _icon(_SHIELD, 24, "2"), el("span", text("MailVigil")), class_="brand")
    return el("header", brand, el("p", text(meta), class_="meta"), class_="top")


def _policy_box(summary: Summary, messages: Messages) -> Safe:
    """
    Write the published policy: ``p``, then ``sp`` and ``np`` when present, then ``pct``.

    Args:
        summary (Summary): The summary.
        messages (Messages): The language.

    Returns:
        Safe: The box; nothing when the reports gave no policy.
    """
    policy = summary.policy
    if policy is None:
        return fragment()
    pairs = [("p", policy.p), ("sp", policy.sp), ("np", policy.np), ("pct", str(policy.pct))]
    # The name goes on a group around the list: a ``role`` on the ``dl`` itself would take the
    # terms and definitions out of a list, which the audit reports as a serious fault.
    terms = el(
        "dl",
        *[
            el("div", el("dt", text(key)), el("dd", _clean(value, _VALUE_MAX)))
            for key, value in pairs
            if value
        ],
        class_="policy",
    )
    return el("div", terms, role="group", aria_label=messages.html.policy_label)


def _banner(summary: Summary, verdict: Verdict, messages: Messages) -> Safe:
    """
    Write the verdict banner: the answer first and large, why, what to do next, the policy.

    Args:
        summary (Summary): The summary.
        verdict (Verdict): The verdict.
        messages (Messages): The language.

    Returns:
        Safe: The banner, coloured by the answer.
    """
    phrase = answer_phrase(verdict, messages)
    body = [
        el("p", text(messages.html.eyebrow), class_="eyebrow"),
        el("h1", text(phrase[:1].upper() + phrase[1:]), id="answer"),
        el("p", text(reason_sentence(verdict, messages)), class_="why"),
    ]
    if verdict.answer is Answer.TOO_EARLY and _rule(verdict, RuleId.PERIOD).measured == 0:
        body.append(el("p", text(messages.verdict.no_report_kept), class_="why"))
    following = next_sentence(verdict, messages)
    if following:
        label = messages.verdict.next_label
        body.append(el("p", el("strong", text(label)), text(f" {following}"), class_="next"))
    return el(
        "section",
        el("div", _icon(_MARK[verdict.answer], 28, "3"), class_="vmark"),
        el("div", *body, class_="vbody"),
        _policy_box(summary, messages),
        class_=_TONE[verdict.answer],
        aria_labelledby="answer",
    )


# ---------------------------------------------------------------------------
# The rules, the mix and the days (RF-03, RF-04)
# ---------------------------------------------------------------------------


def _rules(verdict: Verdict, messages: Messages) -> Safe:
    """
    Write the five rules, as meters, in the two groups of the design.

    Args:
        verdict (Verdict): The verdict.
        messages (Messages): The language.

    Returns:
        Safe: The section: the data rules, the problem rules and what the dark mark is.
    """
    html = messages.html
    groups = (
        (html.group_data, RuleKind.DATA, "grp-data"),
        (html.group_problem, RuleKind.PROBLEM, "grp-problem"),
    )
    parts = []
    for title, kind, key in groups:
        meters = [meter(rule, messages) for rule in verdict.rules if rule.kind is kind]
        parts.append(el("h3", text(title), id=key, class_="grp"))
        parts.append(el("ul", *meters, class_="meters", aria_labelledby=key))
    parts.append(el("div", el("i"), el("span", text(html.meter_legend)), class_="tickkey"))
    return _section(html.rules_title, "h-rules", *parts)


def _mix(summary: Summary, messages: Messages) -> Safe:
    """
    Write the mix of messages: the stacked bar and its legend.

    Args:
        summary (Summary): The summary.
        messages (Messages): The language.

    Returns:
        Safe: The section; nothing when no message was counted.
    """
    total = summary.totals.total
    if total == 0:
        return fragment()
    title = messages.html.mix_title.of(total)
    return _section(title, "h-mix", stacked_bar(summary.totals, messages))


def _days(summary: Summary, messages: Messages) -> Safe:
    """
    Write the timeline: the messages day by day.

    Args:
        summary (Summary): The summary.
        messages (Messages): The language.

    Returns:
        Safe: The section; nothing when there is no period to draw.
    """
    if summary.period is None:
        return fragment()
    return _section(messages.html.days_title, "h-days", timeline(summary, messages))


# ---------------------------------------------------------------------------
# The senders (RF-05)
# ---------------------------------------------------------------------------


def _sender_cell(row: SenderRow, messages: Messages) -> Safe:
    """
    Write the first cell of a sender: its name, or its address and what kind of source it is.

    Args:
        row (SenderRow): The row.
        messages (Messages): The language.

    Returns:
        Safe: The row header, with a chip for an unrecognized source and one for a failing one.
    """
    if row.outcome is Outcome.KNOWN:
        parts = [_clean(row.service, _NAME_MAX)]
    else:
        where = address(row.source_ip, messages.common.no_address)
        parts = [_clean(where, _ADDRESS_MAX), _chip(messages.common.kinds[row.outcome])]
    if row.counts.failing:
        parts.append(_chip(messages.summary.col_failing, bad=True))
    return el("th", *parts, scope="row")


def _senders(summary: Summary, messages: Messages) -> Safe:
    """
    Write the senders table, with a total row.

    Args:
        summary (Summary): The summary.
        messages (Messages): The language.

    Returns:
        Safe: The section; a sentence instead of the table when no message was counted.
    """
    words = messages.summary
    title = words.senders_title
    if not summary.senders:
        return _section(title, "h-senders", el("p", text(words.no_messages), class_="sub"))
    columns = (words.col_ok, words.col_fragile, words.col_failing, words.col_total)
    head = el(
        "tr",
        el("th", text(words.col_sender), scope="col"),
        *[el("th", text(name), scope="col", class_="n") for name in columns],
    )
    rows = [
        el(
            "tr",
            _sender_cell(row, messages),
            *[
                el("td", text(str(number)), class_="n")
                for number in (
                    row.counts.ok,
                    row.counts.fragile,
                    row.counts.failing,
                    row.counts.total,
                )
            ],
        )
        for row in summary.senders
    ]
    totals = summary.totals
    foot = el(
        "tr",
        el("th", text(words.col_total.capitalize()), scope="row"),
        *[
            el("td", text(str(number)), class_="n")
            for number in (totals.ok, totals.fragile, totals.failing, totals.total)
        ],
    )
    table = el("table", el("thead", head), el("tbody", *rows), el("tfoot", foot))
    box = el(
        "div",
        table,
        class_="scroll",
        role="region",
        aria_label=messages.html.senders_region,
        tabindex="0",
    )
    return _section(title, "h-senders", box)


# ---------------------------------------------------------------------------
# Failing sources, notes and what was left out (RF-05)
# ---------------------------------------------------------------------------


def _source(source: FailingSource, messages: Messages) -> Safe:
    """
    Write one failing source: who it is, where it is, and what failed.

    Args:
        source (FailingSource): The source.
        messages (Messages): The language.

    Returns:
        Safe: A list item: the name (the service, or the address of an unrecognized source with its
            kind and the configured selectors involved), then the address, the messages, the result
            per mechanism and the override types the receiver gave.
    """
    common = messages.common
    where = address(source.source_ip, common.no_address)
    detail = messages.summary.source_detail.format(
        messages=common.message.of(source.messages),
        dkim=fit("/".join(source.dkim), _NAME_MAX) or messages.summary.mechanism_none,
        spf=fit("/".join(source.spf), _NAME_MAX) or messages.summary.mechanism_none,
    )
    if source.override_reasons:
        detail += "; " + fit(", ".join(source.override_reasons), _NAME_MAX)
    if source.outcome is Outcome.KNOWN:
        head = [el("strong", _clean(source.service, _NAME_MAX))]
        detail = f"{fit(where, _ADDRESS_MAX)} \u00b7 {detail}"
    else:
        head = [el("strong", _clean(where, _ADDRESS_MAX))]
        if source.outcome is not Outcome.UNKNOWN:
            kind = common.kinds[source.outcome]
            if source.selectors:
                names = ", ".join(fit(s, _NAME_MAX) for s in source.selectors)
                kind += f" ({common.selectors_named.of(len(source.selectors), names=names)})"
            head.append(_chip(kind))
    return el("li", el("div", *head, class_="fhead"), el("p", text(detail), class_="fwhy"))


def _group(title: str, sources: Sequence[FailingSource], messages: Messages) -> Safe:
    """
    Write a group of failing sources: the first ones and a line that still counts the others.

    Args:
        title (str): The title of the group.
        sources (Sequence[FailingSource]): The sources, the worst first.
        messages (Messages): The language.

    Returns:
        Safe: The title and the list; nothing for an empty group.
    """
    if not sources:
        return fragment()
    items = [_source(source, messages) for source in sources[:_LIMIT]]
    rest = sources[_LIMIT:]
    if rest:
        common = messages.common
        more = common.more_failing.format(
            sources=common.other_source.of(len(rest)),
            messages=common.failing_message.of(sum(source.messages for source in rest)),
        )
        items.append(el("li", el("p", text(more), class_="fwhy")))
    return fragment(el("h3", text(title), class_="grp"), el("ul", *items, class_="fails"))


def _failing(verdict: Verdict, messages: Messages) -> Safe:
    """
    Write the failing sources, the recognized ones first.

    Args:
        verdict (Verdict): The verdict, which holds them split by whether the sender is recognized.
        messages (Messages): The language.

    Returns:
        Safe: The card; a sentence that says there is none, with no list, when nothing fails.
    """
    words = messages.summary
    title = messages.html.failing_heading
    if not verdict.recognized_failing and not verdict.unrecognized_failing:
        return _section(title, "h-failing", el("p", text(words.no_failures), class_="sub"))
    intro = fragment()
    if verdict.answer is Answer.READY:
        intro = el("p", text(messages.verdict.still_failing), class_="sub")
    return _section(
        title,
        "h-failing",
        intro,
        _group(words.failing_recognized, verdict.recognized_failing, messages),
        _group(words.failing_unrecognized, verdict.unrecognized_failing, messages),
    )


def _notes(verdict: Verdict, messages: Messages) -> Safe:
    """
    Write the notes of the verdict, none of which changes the answer.

    Args:
        verdict (Verdict): The verdict.
        messages (Messages): The language.

    Returns:
        Safe: The card; nothing when there are no notes.
    """
    if not verdict.notes:
        return fragment()
    items = [el("li", text(note_sentence(note, messages))) for note in verdict.notes]
    return _section(messages.verdict.notes_title, "h-notes", el("ul", *items, class_="notes"))


def _left_out(verdict: Verdict, messages: Messages) -> Safe:
    """
    Say what the summary did not count: the files skipped, the duplicates, the other domains.

    Args:
        verdict (Verdict): The verdict.
        messages (Messages): The language.

    Returns:
        Safe: The card, with counts and no file name; nothing when every count is zero.
    """
    parts = left_out_parts(verdict, messages)
    if not parts:
        return fragment()
    items = [el("li", text(part)) for part in parts]
    return el(
        "section",
        el("h2", text(messages.summary.left_out_title), id="h-left"),
        el("ul", *items, class_="notes"),
        class_="card quiet",
        aria_labelledby="h-left",
    )


def _columns(verdict: Verdict, messages: Messages) -> Safe:
    """
    Lay the failing sources beside the notes and what was left out.

    Args:
        verdict (Verdict): The verdict.
        messages (Messages): The language.

    Returns:
        Safe: Two columns, or one when there are no notes and nothing was left out.
    """
    side = [block for block in (_notes(verdict, messages), _left_out(verdict, messages)) if block]
    children = [_failing(verdict, messages)]
    if side:
        children.append(el("div", *side, class_="stackcol"))
    return el("div", *children, class_="cols")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def render_html(summary: Summary, verdict: Verdict, messages: Messages = ENGLISH) -> str:
    """
    Turn a summary and its verdict into one HTML page.

    Args:
        summary (Summary): What the reports say.
        verdict (Verdict): What ``judge`` made of the summary.
        messages (Messages, optional): The language. Default: English.

    Returns:
        str: The whole document, ASCII only (numeric character references for the rest), ending in
            a newline. The header, the answer with its reason and next step, the five rules, the mix
            of messages, the timeline, the senders, the failing sources with the notes and what was
            left out, and the footer, in this order.
    """
    main = el(
        "main",
        _banner(summary, verdict, messages),
        _rules(verdict, messages),
        _mix(summary, messages),
        _days(summary, messages),
        _senders(summary, messages),
        _columns(verdict, messages),
    )
    footer = el("footer", text(messages.html.footer.format(version=__version__)))
    title = messages.html.page_title.format(domain=fit(summary.domain, _DOMAIN_MAX))
    page = document(
        lang=messages.html.lang,
        title=title,
        policy=CONTENT_SECURITY_POLICY,
        css=raw(STYLESHEET),
        body=el("div", _header(summary, messages), main, footer, class_="page"),
    )
    return finish(page)
