"""
The text of the summary: a frozen ``Summary`` turned into the five sections of the command.

Everything the command says in English lives here, so spec 006 replaces one module (language,
``--json``) without touching the computation (RNF-03). The limits of 10 and their "and N more" lines
are applied here and never in ``summarize``, which keeps the complete data (ADR-1). The layout is
ASCII, 80 columns at most, with the widths taken from the data (ADR-6); the text is returned without
a trailing newline and writing it is the command's.
"""

from __future__ import annotations

from collections.abc import Sequence
from types import MappingProxyType

from mailvigil.config import Config
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
_LABEL_MIN = 10
_LABEL_MAX = 30

# Keys of the header and of the "left out" section are padded to the longest key of their block plus
# two spaces, so the values line up.
_HEADER_KEY = 10
_LEFT_OUT_KEY = 15

# How a row that was not recognized is described. ``KNOWN`` has no entry: it prints its service.
_KIND_NOTES = {
    Outcome.UNKNOWN: "unrecognized",
    Outcome.FOREIGN_DOMAIN: "foreign domain",
    Outcome.FAILING_SIGNATURE: "failing signature",
}

# One phrase per refusal. A test iterates ``Reason``, so a reason added by a later spec cannot reach
# the output as a bare key.
_REASON_PHRASES = {
    Reason.UNSUPPORTED_EXTENSION: "unsupported file type",
    Reason.UNREADABLE: "could not be read",
    Reason.FILE_TOO_LARGE: "too large",
    Reason.DECOMPRESSED_TOO_LARGE: "too large once decompressed",
    Reason.NOT_AN_ARCHIVE: "not a valid archive",
    Reason.NO_XML_MEMBER: "no XML file inside",
    Reason.MULTIPLE_XML_MEMBERS: "more than one XML file inside",
    Reason.FORBIDDEN_DECLARATION: "unsafe XML (DOCTYPE or ENTITY)",
    Reason.MALFORMED_XML: "malformed XML",
    Reason.NOT_A_REPORT: "not a DMARC report",
    Reason.UNSUPPORTED_VERSION: "unsupported report version",
    Reason.INVALID_FIELD: "invalid value in the report",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
    tenths = (2000 * part + whole) // (2 * whole)
    if tenths == 0:
        return "<0.1%"
    tenths = min(tenths, 999)
    return f"{tenths // 10}.{tenths % 10}%"


def _fit(text: str, width: int) -> str:
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


def _count(number: int, singular: str, plural: str = "") -> str:
    """
    Write a count with its noun.

    Args:
        number (int): The count.
        singular (str): The noun for one.
        plural (str, optional): The noun for any other number. Default: the singular plus ``s``.

    Returns:
        str: For example ``1 day`` or ``28 days``.
    """
    return f"{number} {singular if number == 1 else plural or singular + 's'}"


def _address(source_ip: str) -> str:
    """
    Name a source address, which a report may leave empty.

    Args:
        source_ip (str): The address as the summary holds it.

    Returns:
        str: The address, or ``no address``.
    """
    return source_ip or "no address"


def _label(row: SenderRow, width: int) -> str:
    """
    Write the label of a row of the senders table.

    Args:
        row (SenderRow): The row.
        width (int): The widest the label may be.

    Returns:
        str: The service name for a recognized sender, otherwise ``ADDRESS (kind)``. When it is too
            wide it is the address that is cut, so the kind stays visible.
    """
    if row.outcome is Outcome.KNOWN:
        return _fit(row.service, width)
    address = _address(row.source_ip)
    suffix = f" ({_KIND_NOTES[row.outcome]})"
    room = width - len(suffix)
    if room < 4:
        return _fit(address + suffix, width)
    return _fit(address, room) + suffix


def _field(key: str, value: str, key_width: int = _HEADER_KEY) -> str:
    """
    Write one ``key  value`` line, indented by two.

    Args:
        key (str): The name of the field.
        value (str): Its text.
        key_width (int, optional): The width the key is padded to. Default: the header's.

    Returns:
        str: The line, with the value cut to what is left of the width.
    """
    prefix = f"  {key:<{key_width}}"
    return prefix + _fit(value, _WIDTH - len(prefix))


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


def _header(summary: Summary, config_source: str | None) -> list[str]:
    """
    Write the title and the five facts about the run (RF-03, RF-09).

    Args:
        summary (Summary): The data.
        config_source (str | None): The configuration path as the command resolved it, ``None`` for
            no file.

    Returns:
        list[str]: The lines: ``config``, ``period``, ``reports``, ``policy`` and ``messages``, each
            note on its own line below the field it explains.
    """
    indent = " " * (2 + _HEADER_KEY)
    lines = [f"MailVigil summary for {_fit(summary.domain, _WIDTH - 22)}"]

    if config_source is None:
        lines.append(_field("config", "none"))
    else:
        suffix = f" ({_count(summary.selectors_configured, 'selector')})"
        room = _WIDTH - len(indent) - len(suffix)
        lines.append(_field("config", _fit(config_source, room) + suffix))
    if summary.selectors_configured == 0:
        lines.append(indent + "no selectors are configured, so every sender is unrecognized")
        lines.append(indent + "(see the Configuration section of the README)")

    period = summary.period
    if period is None:
        lines.append(_field("period", "no reports"))
    else:
        verb = "has" if period.days_with_reports == 1 else "have"
        days = _count(period.days_spanned, "day")
        lines.append(
            _field(
                "period",
                f"{period.first_day.isoformat()} to {period.last_day.isoformat()} "
                f"({period.days_with_reports} of {days} {verb} a report)",
            )
        )

    lines.append(
        _field("reports", f"{summary.reports} from {_count(summary.reporters, 'reporter')}")
    )

    policy = summary.policy
    if policy is None:
        lines.append(_field("policy", "none"))
    else:
        parts = [f"p={policy.p}"]
        if policy.sp:
            parts.append(f"sp={policy.sp}")
        if policy.np:
            parts.append(f"np={policy.np}")
        parts.append(f"pct={policy.pct}")
        lines.append(_field("policy", ", ".join(parts)))
        if summary.earlier_p:
            earlier = ", ".join(summary.earlier_p)
            lines.append(
                indent + _fit(f"changed during the period, earlier p: {earlier}", _WIDTH - 12)
            )

    total = summary.totals.total
    share = format_share(summary.recognized_messages, total)
    lines.append(
        _field(
            "messages", f"{total} ({summary.recognized_messages} from recognized senders, {share})"
        )
    )
    return lines


def _situations(summary: Summary) -> list[str]:
    """
    Write the situations with their exact counts and shares (RF-06).

    Args:
        summary (Summary): The data.

    Returns:
        list[str]: The title and one line for each of ``ok``, ``fragile`` and ``failing``.
    """
    totals = summary.totals
    rows = (("ok", totals.ok), ("fragile", totals.fragile), ("failing", totals.failing))
    shares = [format_share(number, totals.total) for _name, number in rows]
    count_width = max(len(str(number)) for _name, number in rows)
    share_width = max(len(share) for share in shares)
    lines = ["Situations"]
    for (name, number), share in zip(rows, shares, strict=True):
        lines.append(f"  {name:<7}  {number:>{count_width}}  {share:>{share_width}}")
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


def _senders(summary: Summary) -> list[str]:
    """
    Write the senders table (RF-02, RF-04).

    Args:
        summary (Summary): The data.

    Returns:
        list[str]: The title, the header, a line per shown row (starting with ``!`` when it has
            failing messages) and, when rows were left out, one line that still counts their
            failing messages.
    """
    shown, hidden = _shown_rows(summary.senders)
    if not shown and not hidden:
        return ["Senders", "  no messages counted"]

    headers = ("ok", "fragile", "failing", "total")
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
    labels = [_label(row, _WIDTH) for row in shown]
    longest = max([len("sender"), *(len(label) for label in labels)])
    label_width = max(_LABEL_MIN, min(_LABEL_MAX, left, longest))

    lines = ["Senders"]
    lines.append(
        "  "
        + "sender".ljust(label_width)
        + "".join(f"  {header:>{width}}" for header, width in zip(headers, widths, strict=True))
    )
    for row, row_cells in zip(shown, cells, strict=True):
        marker = "!" if row.counts.failing else " "
        lines.append(
            f"{marker} "
            + _label(row, label_width).ljust(label_width)
            + "".join(f"  {cell:>{width}}" for cell, width in zip(row_cells, widths, strict=True))
        )
    if hidden:
        messages = sum(row.counts.total for row in hidden)
        failing = sum(row.counts.failing for row in hidden)
        lines.append(
            f"  ... and {_count(len(hidden), 'other source')}: "
            f"{_count(messages, 'message')}, {failing} failing"
        )
    return lines


def _who(source: FailingSource) -> str:
    """
    Name the sender of a failing source.

    Args:
        source (FailingSource): The source.

    Returns:
        str: The service name for a recognized sender; ``unrecognized`` otherwise, followed for a
            foreign domain and a failing signature by the kind and the configured selectors involved
            (RF-04), so the owner can tell a copied selector from a broken one.
    """
    if source.outcome is Outcome.KNOWN:
        return source.service
    who = "unrecognized"
    if source.outcome is not Outcome.UNKNOWN:
        who += f", {_KIND_NOTES[source.outcome]}"
        if source.selectors:
            noun = "selector" if len(source.selectors) == 1 else "selectors"
            who += f" ({noun} {', '.join(source.selectors)})"
    return who


def _source_lines(source: FailingSource) -> list[str]:
    """
    Write the two lines of one failing source.

    Args:
        source (FailingSource): The source.

    Returns:
        list[str]: ``  ! WHO``, then the address, the failing messages, the reason per mechanism and
            the override types the receiver gave.
    """
    dkim = "/".join(source.dkim) or "none"
    spf = "/".join(source.spf) or "none"
    detail = (
        f"{_address(source.source_ip)}  {_count(source.messages, 'message')}  "
        f"dkim: {dkim}, spf: {spf}"
    )
    if source.override_reasons:
        detail += "; " + ", ".join(source.override_reasons)
    return ["  ! " + _fit(_who(source), _WIDTH - 4), "      " + _fit(detail, _WIDTH - 6)]


def _failures(summary: Summary) -> list[str]:
    """
    Write the failures section (RF-04).

    Args:
        summary (Summary): The data.

    Returns:
        list[str]: ``No failing messages.`` when there is none; otherwise the title and two groups,
            recognized senders first, each limited to ``_LIMIT`` sources with a remainder line that
            still counts the failing messages it hides. An empty group is not printed.
    """
    if not summary.failing:
        return ["No failing messages."]
    messages = sum(source.messages for source in summary.failing)
    lines = [
        f"! FAILING: {_count(messages, 'message')} in {_count(len(summary.failing), 'source')}"
    ]
    recognized = [source for source in summary.failing if source.outcome is Outcome.KNOWN]
    unrecognized = [source for source in summary.failing if source.outcome is not Outcome.KNOWN]
    for title, sources in (
        ("Recognized senders that fail", recognized),
        ("Unrecognized sources that fail", unrecognized),
    ):
        if not sources:
            continue
        lines.append(f"  {title}")
        for source in sources[:_LIMIT]:
            lines.extend(_source_lines(source))
        rest = sources[_LIMIT:]
        if rest:
            hidden = sum(source.messages for source in rest)
            lines.append(
                f"  ... and {_count(len(rest), 'other source')}: "
                f"{_count(hidden, 'failing message')}"
            )
    return lines


def _left_out(
    skipped: Sequence[SkippedFile],
    by_reason: Sequence[tuple[Reason, int]],
    duplicates: int,
    other_domain: int,
) -> list[str]:
    """
    Write what was left out of the numbers (RF-05); it always prints, also at zero.

    Args:
        skipped (Sequence[SkippedFile]): The refused files, in the order to print them.
        by_reason (Sequence[tuple[Reason, int]]): The refusals counted per reason, in the order to
            print them.
        duplicates (int): Reports dropped as already seen.
        other_domain (int): Reports dropped for belonging to another domain.

    Returns:
        list[str]: The skipped count with its reasons, the first ``_LIMIT`` files with their reason
            and a line with how many more, then the duplicates and the other domains.
    """
    reasons = ", ".join(f"{number} {_REASON_PHRASES[reason]}" for reason, number in by_reason)
    count = str(len(skipped)) + (f" ({reasons})" if reasons else "")
    lines = [_field("skipped files", count, _LEFT_OUT_KEY)]
    for file in skipped[:_LIMIT]:
        phrase = _REASON_PHRASES[file.reason]
        # The phrase is the part that must survive, so it is the name that is cut.
        name = _fit(file.path.name or str(file.path), _WIDTH - 4 - len(phrase) - 2)
        lines.append(f"    {name}: {phrase}")
    if len(skipped) > _LIMIT:
        lines.append(f"    ... and {len(skipped) - _LIMIT} more")
    lines.append(_field("duplicates", str(duplicates), _LEFT_OUT_KEY))
    lines.append(_field("other domains", str(other_domain), _LEFT_OUT_KEY))
    return lines


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def render_summary(summary: Summary, config_source: str | None) -> str:
    """
    Turn a summary into the text of the command.

    Args:
        summary (Summary): The data, complete: the limits are applied here.
        config_source (str | None): The configuration path as the command resolved it, ``None`` for
            no file. It is run metadata, not part of the data.

    Returns:
        str: The five sections (header, situations, senders, failures, left out), separated by one
            blank line, without a trailing newline.
    """
    sections = [
        _header(summary, config_source),
        _situations(summary),
        _senders(summary),
        _failures(summary),
        [
            "Left out of these numbers",
            *_left_out(
                summary.skipped, summary.skipped_by_reason, summary.duplicates, summary.other_domain
            ),
        ],
    ]
    return "\n\n".join("\n".join(lines) for lines in sections)


def no_reports_message(result: IngestionResult, domain: str) -> str:
    """
    Explain an empty result, for standard error (RF-10).

    The counts of what was refused and filtered make the cause visible: a wrong extension, a report
    of another domain, a folder with nothing in it.

    Args:
        result (IngestionResult): What ``ingest`` returned, with no report kept.
        domain (str): The domain the reports were filtered for.

    Returns:
        str: The domain, the skipped files with their reasons, the duplicates and the reports of
            other domains, without a trailing newline.
    """
    summary = summarize(result, Config(domain, MappingProxyType({})))
    lines = [f"No DMARC report for {_fit(domain, _WIDTH - 30)} was kept."]
    if not (summary.skipped or summary.duplicates or summary.other_domain):
        lines.append("No .xml, .gz or .zip file was found in the paths given.")
    lines.extend(
        _left_out(
            summary.skipped, summary.skipped_by_reason, summary.duplicates, summary.other_domain
        )
    )
    return "\n".join(lines)
