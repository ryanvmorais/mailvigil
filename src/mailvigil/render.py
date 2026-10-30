"""
The text of the summary: a frozen ``Summary`` turned into the five sections of the command.

The layout lives here and the words live in ``mailvigil.messages``: every sentence is read from the
``Messages`` the caller passes (English by default), so a second language does not need a second
layout (spec 006, ADR-3 and ADR-4). The limits of 10 and their "and N more" lines are applied here
and never in ``summarize``, which keeps the complete data (ADR-1). The layout is ASCII, 80 columns
at most, with the widths taken from the data (ADR-6) and from the templates, so a longer translation
cannot push a value past the screen; the text is returned without a trailing newline and writing it
is the command's.
"""

from __future__ import annotations

from collections.abc import Sequence
from types import MappingProxyType

from mailvigil.config import Config
from mailvigil.messages import ENGLISH, Messages
from mailvigil.reports import IngestionResult, Reason, SkippedFile
from mailvigil.senders import Outcome
from mailvigil.summary import FailingSource, SenderRow, Summary, summarize
from mailvigil.text import clean_text

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# The widest line of the output (RF-09).
_WIDTH = 80

# Rows of the senders table, failing sources of a group and skipped files shown before "and N more"
# (Resolved decision 12).
_LIMIT = 10

# The label column of the senders table takes what the numbers leave, but not less than the first
# bound, which keeps a short IP readable, nor more than the second, which keeps the numbers close.
# The second is the longest IPv4 address with the longest kind, so a long service name never makes
# the column cut the address of an unrecognized row.
_LABEL_MIN = 10
_LABEL_MAX = len("255.255.255.255 (failing signature)")

# The English phrase of each refusal, under the name the 004 tests know it by. The phrases live in
# the catalog; the code below reads them from the ``Messages`` it is given.
_REASON_PHRASES = ENGLISH.summary.reasons


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def share_tenths(part: int, whole: int) -> int:
    """
    Write a share as tenths of a percent, in integers, rounding half up (ADR-8 of spec 005).

    This is the number under ``format_share``, public so a caller can ask whether a share rounds
    to a limit without reading it back from the text.

    Args:
        part (int): The messages in the share.
        whole (int): All the messages.

    Returns:
        int: ``0`` for no part (or no whole); otherwise ``1000 * part / whole`` rounded half up, so
            ``1000`` for the whole and ``5`` for 0.5%.
    """
    if part <= 0 or whole <= 0:
        return 0
    return (2000 * part + whole) // (2 * whole)


def format_share(part: int, whole: int) -> str:
    """
    Write a share as a percentage that never rounds a small number away (ADR-5).

    The tenths of a percent are computed with integers (round half up), so the text is the same on
    every platform. A float format would print ``0.0%`` for four messages in ten thousand and
    ``100.0%`` for 9997 in ten thousand, the two ways a failing handful of messages disappears.

    Args:
        part (int): The messages in the share.
        whole (int): All the messages.

    Returns:
        str: ``0%`` for no part (or no whole), ``<0.1%`` below one tenth of a percent, ``99.9%``
            rather than ``100.0%`` when the part is short of the whole, ``100%`` only for the whole,
            and one decimal otherwise.
    """
    if part <= 0 or whole <= 0:
        return "0%"
    if part >= whole:
        return "100%"
    tenths = share_tenths(part, whole)
    if tenths == 0:
        return "<0.1%"
    tenths = min(tenths, 999)
    return f"{tenths // 10}.{tenths % 10}%"


def fit(text: str, width: int) -> str:
    """
    Make a text safe to print and no wider than a column.

    Every dynamic string passes through here before it is placed in a line, so a file name, a path
    given to ``--config`` or any other text that did not come from a report or the configuration is
    inert (RF-05, RNF-08). The cleaning comes first, so removed characters take no room.

    Args:
        text (str): The text to print.
        width (int): The most characters it may take.

    Returns:
        str: The cleaned text, cut with ``...`` when it is wider than ``width``.
    """
    cleaned = clean_text(text, len(text))
    if len(cleaned) <= width:
        return cleaned
    if width <= 3:
        return "." * max(width, 0)
    return cleaned[: width - 3] + "..."


def address(source_ip: str, missing: str = ENGLISH.common.no_address) -> str:
    """
    Name a source address, which a report may leave empty.

    Args:
        source_ip (str): The address as the summary holds it.
        missing (str, optional): What to write for an empty address. Default: the English phrase.

    Returns:
        str: The address, or ``missing``.
    """
    return source_ip or missing


def _room(template: str, **blanks: str) -> int:
    """
    Count the columns a template leaves for the value that is cut to fit.

    The width is taken from the template, not typed, so a longer translation of the same sentence
    cannot push the value past the screen.

    Args:
        template (str): The sentence, with one placeholder for the value that gives way.
        **blanks (str): That placeholder, as an empty string.

    Returns:
        int: The screen width less the template's own characters.
    """
    return _WIDTH - len(template.format(**blanks))


def _key_width(*keys: str) -> int:
    """
    Size the key column of a block of ``key  value`` lines.

    Args:
        *keys (str): The keys of the block.

    Returns:
        int: The longest key plus two spaces, so the values line up.
    """
    return max(len(key) for key in keys) + 2


def _label(row: SenderRow, width: int, messages: Messages = ENGLISH) -> str:
    """
    Write the label of a row of the senders table.

    Args:
        row (SenderRow): The row.
        width (int): The widest the label may be.
        messages (Messages, optional): The language. Default: English.

    Returns:
        str: The service name for a recognized sender, otherwise ``ADDRESS (kind)``. When it is too
            wide it is the address that is cut, so the kind stays visible.
    """
    if row.outcome is Outcome.KNOWN:
        return fit(row.service, width)
    text = address(row.source_ip, messages.common.no_address)
    suffix = f" ({messages.common.kinds[row.outcome]})"
    room = width - len(suffix)
    if room < 4:
        return fit(text + suffix, width)
    return fit(text, room) + suffix


def _field(key: str, value: str, key_width: int) -> str:
    """
    Write one ``key  value`` line, indented by two.

    Args:
        key (str): The name of the field.
        value (str): Its text.
        key_width (int): The width the key is padded to.

    Returns:
        str: The line, with the value cut to what is left of the width.
    """
    prefix = f"  {key:<{key_width}}"
    return prefix + fit(value, _WIDTH - len(prefix))


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


def _header(summary: Summary, config_source: str | None, messages: Messages) -> list[str]:
    """
    Write the title and the five facts about the run (RF-03, RF-09).

    Args:
        summary (Summary): The data.
        config_source (str | None): The configuration path as the command resolved it, ``None`` for
            no file.
        messages (Messages): The language.

    Returns:
        list[str]: The lines: config, period, reports, policy and messages, each note on its own
            line below the field it explains.
    """
    text = messages.summary
    common = messages.common
    key_width = _key_width(
        text.key_config, text.key_period, text.key_reports, text.key_policy, text.key_messages
    )
    indent = " " * (2 + key_width)
    domain = fit(summary.domain, _room(text.title, domain=""))
    lines = [text.title.format(domain=domain)]

    if config_source is None:
        lines.append(_field(text.key_config, text.config_none, key_width))
    else:
        suffix = f" ({text.selector.of(summary.selectors_configured)})"
        room = _WIDTH - len(indent) - len(suffix)
        lines.append(_field(text.key_config, fit(config_source, room) + suffix, key_width))
    if summary.selectors_configured == 0:
        lines.append(indent + fit(text.no_selectors, _WIDTH - len(indent)))
        lines.append(indent + fit(text.no_selectors_hint, _WIDTH - len(indent)))

    period = summary.period
    if period is None:
        lines.append(_field(text.key_period, text.no_period, key_width))
    else:
        lines.append(
            _field(
                text.key_period,
                text.period.of(
                    period.days_with_reports,
                    first=period.first_day.isoformat(),
                    last=period.last_day.isoformat(),
                    days=common.day.of(period.days_spanned),
                ),
                key_width,
            )
        )

    reports = text.reports_line.format(
        reports=summary.reports, reporters=text.reporter.of(summary.reporters)
    )
    lines.append(_field(text.key_reports, reports, key_width))

    policy = summary.policy
    if policy is None:
        lines.append(_field(text.key_policy, text.policy_none, key_width))
    else:
        parts = [f"p={policy.p}"]
        if policy.sp:
            parts.append(f"sp={policy.sp}")
        if policy.np:
            parts.append(f"np={policy.np}")
        parts.append(f"pct={policy.pct}")
        lines.append(_field(text.key_policy, ", ".join(parts), key_width))
        if summary.earlier_p:
            earlier = text.policy_changed.format(earlier=", ".join(summary.earlier_p))
            lines.append(indent + fit(earlier, _WIDTH - len(indent)))

    total = summary.totals.total
    lines.append(
        _field(
            text.key_messages,
            text.messages_line.format(
                total=total,
                recognized=summary.recognized_messages,
                share=format_share(summary.recognized_messages, total),
            ),
            key_width,
        )
    )
    return lines


def _situations(summary: Summary, messages: Messages) -> list[str]:
    """
    Write the situations with their exact counts and shares (RF-06).

    Args:
        summary (Summary): The data.
        messages (Messages): The language.

    Returns:
        list[str]: The title and one line for each of ok, fragile and failing.
    """
    text = messages.summary
    totals = summary.totals
    rows = (
        (text.col_ok, totals.ok),
        (text.col_fragile, totals.fragile),
        (text.col_failing, totals.failing),
    )
    shares = [format_share(number, totals.total) for _name, number in rows]
    name_width = max(len(name) for name, _number in rows)
    count_width = max(len(str(number)) for _name, number in rows)
    share_width = max(len(share) for share in shares)
    lines = [text.situations_title]
    for (name, number), share in zip(rows, shares, strict=True):
        lines.append(f"  {name:<{name_width}}  {number:>{count_width}}  {share:>{share_width}}")
    return lines


def _shown_rows(senders: Sequence[SenderRow]) -> tuple[list[SenderRow], list[SenderRow]]:
    """
    Split the rows into those the table prints and those the remainder line sums up.

    Args:
        senders (Sequence[SenderRow]): Every row, in the order of the summary.

    Returns:
        tuple[list[SenderRow], list[SenderRow]]: Every recognized row and the first ``_LIMIT`` of
            the others, in the order of the summary; then the others. Every recognized row is shown
            because their number is the size of the owner's own map.
    """
    shown: list[SenderRow] = []
    hidden: list[SenderRow] = []
    others = 0
    for row in senders:
        if row.outcome is Outcome.KNOWN:
            shown.append(row)
        elif others < _LIMIT:
            others += 1
            shown.append(row)
        else:
            hidden.append(row)
    return shown, hidden


def _senders(summary: Summary, messages: Messages) -> list[str]:
    """
    Write the senders table (RF-02, RF-04).

    Args:
        summary (Summary): The data.
        messages (Messages): The language.

    Returns:
        list[str]: The title, the header, a line per shown row (starting with ``!`` when it has
            failing messages) and, when rows were left out, one line that still counts their
            failing messages.
    """
    text = messages.summary
    common = messages.common
    shown, hidden = _shown_rows(summary.senders)
    if not shown and not hidden:
        return [text.senders_title, "  " + text.no_messages]

    headers = (text.col_ok, text.col_fragile, text.col_failing, text.col_total)
    cells = [
        (
            str(row.counts.ok),
            str(row.counts.fragile),
            str(row.counts.failing),
            str(row.counts.total),
        )
        for row in shown
    ]
    widths = [
        max(len(header), *(len(cell[i]) for cell in cells)) for i, header in enumerate(headers)
    ]

    # The label takes what the numbers leave: two columns for the marker, two spaces per number.
    left = _WIDTH - 2 - sum(2 + width for width in widths)
    labels = [_label(row, _WIDTH, messages) for row in shown]
    longest = max([len(text.col_sender), *(len(label) for label in labels)])
    label_width = max(_LABEL_MIN, min(_LABEL_MAX, left, longest))

    lines = [text.senders_title]
    lines.append(
        "  "
        + text.col_sender.ljust(label_width)
        + "".join(f"  {header:>{width}}" for header, width in zip(headers, widths, strict=True))
    )
    for row, row_cells in zip(shown, cells, strict=True):
        marker = "!" if row.counts.failing else " "
        lines.append(
            f"{marker} "
            + _label(row, label_width, messages).ljust(label_width)
            + "".join(f"  {cell:>{width}}" for cell, width in zip(row_cells, widths, strict=True))
        )
    if hidden:
        lines.append(
            "  "
            + text.senders_more.format(
                sources=common.other_source.of(len(hidden)),
                messages=common.message.of(sum(row.counts.total for row in hidden)),
                failing=sum(row.counts.failing for row in hidden),
            )
        )
    return lines


def _who(source: FailingSource, messages: Messages) -> str:
    """
    Name the sender of a failing source.

    Args:
        source (FailingSource): The source.
        messages (Messages): The language.

    Returns:
        str: The service name for a recognized sender; ``unrecognized, KIND`` for a foreign domain
            or a failing signature, followed by the configured selectors involved (RF-04), so the
            owner can tell a copied selector from a broken one. Not for ``UNKNOWN``, which is
            named by its address.
    """
    if source.outcome is Outcome.KNOWN:
        return source.service
    common = messages.common
    who = messages.summary.unrecognized_who.format(kind=common.kinds[source.outcome])
    if source.selectors:
        names = ", ".join(source.selectors)
        who += f" ({common.selectors_named.of(len(source.selectors), names=names)})"
    return who


def _source_lines(source: FailingSource, messages: Messages) -> list[str]:
    """
    Write the two lines of one failing source.

    Args:
        source (FailingSource): The source.
        messages (Messages): The language.

    Returns:
        list[str]: ``  ! WHO``, then the address, the failing messages, the reason per mechanism and
            the override types the receiver gave. A source that was only unrecognized has no name
            to give, so the address is its ``WHO`` and the second line starts at the messages.
    """
    text = messages.summary
    where = address(source.source_ip, messages.common.no_address)
    detail = text.source_detail.format(
        messages=messages.common.message.of(source.messages),
        dkim="/".join(source.dkim) or text.mechanism_none,
        spf="/".join(source.spf) or text.mechanism_none,
    )
    if source.override_reasons:
        detail += "; " + ", ".join(source.override_reasons)
    if source.outcome is Outcome.UNKNOWN:
        who = where
    else:
        who = _who(source, messages)
        detail = f"{where}  {detail}"
    return ["  ! " + fit(who, _WIDTH - 4), "      " + fit(detail, _WIDTH - 6)]


def _failures(summary: Summary, messages: Messages) -> list[str]:
    """
    Write the failures section (RF-04).

    Args:
        summary (Summary): The data.
        messages (Messages): The language.

    Returns:
        list[str]: The sentence that says there is none; otherwise the title and two groups,
            recognized senders first, each limited to ``_LIMIT`` sources with a remainder line that
            still counts the failing messages it hides. An empty group is not printed.
    """
    text = messages.summary
    common = messages.common
    if not summary.failing:
        return [text.no_failures]
    lines = [
        text.failing_title.format(
            messages=common.message.of(sum(source.messages for source in summary.failing)),
            sources=text.source.of(len(summary.failing)),
        )
    ]
    recognized = [source for source in summary.failing if source.outcome is Outcome.KNOWN]
    unrecognized = [source for source in summary.failing if source.outcome is not Outcome.KNOWN]
    for title, sources in (
        (text.failing_recognized, recognized),
        (text.failing_unrecognized, unrecognized),
    ):
        if not sources:
            continue
        lines.append(f"  {title}")
        for source in sources[:_LIMIT]:
            lines.extend(_source_lines(source, messages))
        rest = sources[_LIMIT:]
        if rest:
            lines.append(
                "  "
                + common.more_failing.format(
                    sources=common.other_source.of(len(rest)),
                    messages=common.failing_message.of(sum(source.messages for source in rest)),
                )
            )
    return lines


def _left_out(
    skipped: Sequence[SkippedFile],
    by_reason: Sequence[tuple[Reason, int]],
    duplicates: int,
    other_domain: int,
    passed_over: int,
    messages: Messages,
) -> list[str]:
    """
    Write what was left out of the numbers (RF-05); it always prints, also at zero.

    Args:
        skipped (Sequence[SkippedFile]): The refused files, in the order to print them.
        by_reason (Sequence[tuple[Reason, int]]): The refusals counted per reason, in the order to
            print them.
        duplicates (int): Reports dropped as already seen.
        other_domain (int): Reports dropped for belonging to another domain.
        passed_over (int): Files a folder search passed over by name.
        messages (Messages): The language.

    Returns:
        list[str]: The skipped count with its reasons, the first ``_LIMIT`` files with their reason
            and a line with how many more, then the duplicates and the other domains, and the files
            passed over by name only when there are some.
    """
    text = messages.summary
    keys = [text.key_skipped, text.key_duplicates, text.key_other_domains]
    if passed_over:
        keys.append(text.key_passed_over)
    key_width = _key_width(*keys)
    reasons = ", ".join(f"{number} {text.reasons[reason]}" for reason, number in by_reason)
    count = str(len(skipped)) + (f" ({reasons})" if reasons else "")
    lines = [_field(text.key_skipped, count, key_width)]
    for file in skipped[:_LIMIT]:
        phrase = text.reasons[file.reason]
        # The phrase is the part that must survive, so it is the name that is cut.
        label = file.path.name or str(file.path)
        if file.part:
            label += " " + file.part
        name = fit(label, _WIDTH - 4 - len(phrase) - 2)
        lines.append(f"    {name}: {phrase}")
    if len(skipped) > _LIMIT:
        lines.append("    " + text.skipped_more.format(n=len(skipped) - _LIMIT))
    lines.append(_field(text.key_duplicates, str(duplicates), key_width))
    lines.append(_field(text.key_other_domains, str(other_domain), key_width))
    # Only when there are some: a clean folder has none, and a line of zeros would be noise.
    if passed_over:
        lines.append(_field(text.key_passed_over, str(passed_over), key_width))
    return lines


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def render_summary(
    summary: Summary, config_source: str | None, messages: Messages = ENGLISH
) -> str:
    """
    Turn a summary into the text of the command.

    Args:
        summary (Summary): The data, complete: the limits are applied here.
        config_source (str | None): The configuration path as the command resolved it, ``None`` for
            no file. It is run metadata, not part of the data.
        messages (Messages, optional): The language. Default: English.

    Returns:
        str: The five sections (header, situations, senders, failures, left out), separated by one
            blank line, without a trailing newline.
    """
    sections = [
        _header(summary, config_source, messages),
        _situations(summary, messages),
        _senders(summary, messages),
        _failures(summary, messages),
        [
            messages.summary.left_out_title,
            *_left_out(
                summary.skipped,
                summary.skipped_by_reason,
                summary.duplicates,
                summary.other_domain,
                summary.passed_over,
                messages,
            ),
        ],
    ]
    return "\n\n".join("\n".join(lines) for lines in sections)


def no_reports_message(result: IngestionResult, domain: str, messages: Messages = ENGLISH) -> str:
    """
    Explain an empty result, for standard error (RF-10).

    The counts of what was refused and filtered make the cause visible: a wrong extension, a report
    of another domain, a folder with nothing in it.

    Args:
        result (IngestionResult): What ``ingest`` returned, with no report kept.
        domain (str): The domain the reports were filtered for.
        messages (Messages, optional): The language. Default: English.

    Returns:
        str: The domain, the skipped files with their reasons, the duplicates and the reports of
            other domains, without a trailing newline.
    """
    text = messages.refusals
    summary = summarize(result, Config(domain, MappingProxyType({})))
    lines = [text.no_reports.format(domain=fit(domain, _room(text.no_reports, domain="")))]
    if not (summary.skipped or summary.duplicates or summary.other_domain):
        # A folder yields only the providers' attachment names, so a renamed file is not "missing
        # from the paths": say how to read it anyway.
        lines.append(text.no_file_found)
        lines.append("  " + text.no_file_hint)
    lines.extend(
        _left_out(
            summary.skipped,
            summary.skipped_by_reason,
            summary.duplicates,
            summary.other_domain,
            summary.passed_over,
            messages,
        )
    )
    return "\n".join(lines)
