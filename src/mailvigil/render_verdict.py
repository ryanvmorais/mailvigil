"""
The text of the verdict: a frozen ``Verdict`` turned into the sections of the command.

The layout lives here and the words live in ``mailvigil.messages``: every sentence is read from the
``Messages`` the caller passes (English by default), so a second language does not need a second
layout and the rules are untouched (spec 006, RNF-03). The limits on the sources and their "and N
more" lines are applied here and never in ``judge``, which keeps the complete data. The thresholds
shown come from the rules of the ``Verdict``, which ``judge`` builds from the constants of
``verdict.py``, so no number of the criterion is typed twice, in either language (RNF-05). The
layout follows the summary's: ASCII, 80 columns at most, no color; the text is returned without a
trailing newline and writing it is the command's. The words "safe" and "attack" are not used
anywhere in the English text: the verdict reads reports, it does not certify a domain and it does
not guess intent.
"""

from __future__ import annotations

import textwrap
from collections.abc import Callable, Iterable, Sequence
from functools import partial

from mailvigil.messages import ENGLISH, Messages
from mailvigil.render import address, fit, format_share, share_tenths, spf_domains_part
from mailvigil.senders import Outcome
from mailvigil.summary import FailingSource
from mailvigil.verdict import Answer, Note, NoteKind, Rule, RuleId, RuleKind, Verdict

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# The widest line of the output (004 RF-09), the same as ``render.py``'s.
_WIDTH = 80

# Failing sources shown before "and N other sources": every recognized sender is the owner's own
# map, so it gets the summary's limit; the unrecognized ones are a pointer to look, so fewer
# (RF-03).
_RECOGNIZED_LIMIT = 10
_UNRECOGNIZED_LIMIT = 5

# The longest a service name, an address or a list of reasons may be inside a sentence.
_NAME_MAX = 30
_ADDRESS_MAX = 45
_REASONS_MAX = 40

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _wrap(text: str, first: str = "", rest: str = "") -> list[str]:
    """
    Break a sentence into lines no wider than the screen.

    Args:
        text (str): The sentence; every dynamic part of it has already passed through ``fit``.
        first (str, optional): What the first line starts with. Default: nothing.
        rest (str, optional): What the other lines start with. Default: nothing.

    Returns:
        list[str]: The lines. A word wider than a line is broken, so none overflows.
    """
    return textwrap.wrap(
        text,
        width=_WIDTH,
        initial_indent=first,
        subsequent_indent=rest,
        break_on_hyphens=False,
    )


def _per_mille(tenths: int) -> str:
    """
    Write a threshold kept in tenths of a percent.

    Args:
        tenths (int): The threshold in tenths of a percent, as rule 5 keeps it.

    Returns:
        str: For example ``0.5%`` for 5.
    """
    return f"{tenths // 10}.{tenths % 10}%"


def _share(rule: Rule) -> str:
    """
    Write the share of a rule so that it never reads as a pass beside a failure (RF-08, ADR-8).

    A share is printed to one decimal, so a rule that fails by a hair rounds to its own limit and
    would read ``0.5%`` beside ``<= 0.5%`` and ``FAIL``. The choice is taken from ``Rule.passed``
    and ``share_tenths``, both integers, not from the text.

    Args:
        rule (Rule): Rule 2 or rule 5, the two that carry a share.

    Returns:
        str: The share as ``format_share`` writes it; or, for a failed rule whose share rounds to
            its limit, the limit with ``<`` (an "at least" rule) or ``>`` (an "at most" rule).
    """
    if not rule.passed:
        if rule.id is RuleId.COVERAGE:
            limit, text = rule.needed * 10, f"{rule.needed}%"
        else:
            limit, text = rule.needed, _per_mille(rule.needed)
        if share_tenths(rule.measured, rule.whole) == limit:
            return f"{'<' if rule.at_least else '>'}{text}"
    return format_share(rule.measured, rule.whole)


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


def _entry(head: str, tail: str) -> str:
    """
    Write one line of a source list, indented by two.

    Args:
        head (str): The part that gives way, the name or the address.
        tail (str): The part that must survive: the count, the address, the reasons.

    Returns:
        str: The line. The head is the part that is cut, so the numbers stay visible.
    """
    room = _WIDTH - 2 - len(tail)
    if room < 4:
        return "  " + fit(head + tail, _WIDTH - 2)
    return "  " + fit(head, room) + tail


def _overrides(source: FailingSource) -> str:
    """
    Write the override types the receiver gave for a source (RF-03).

    Args:
        source (FailingSource): The source.

    Returns:
        str: ``" (forwarded, mailing_list)"``, or nothing when there are none.
    """
    reasons = fit(", ".join(source.override_reasons), _REASONS_MAX)
    return f" ({reasons})" if reasons else ""


def _recognized_line(source: FailingSource, messages: Messages) -> str:
    """
    Write a failing source of a recognized sender.

    Args:
        source (FailingSource): The source.
        messages (Messages): The language.

    Returns:
        str: The service, its failing messages, its address and its override types.
    """
    where = fit(address(source.source_ip, messages.common.no_address), _ADDRESS_MAX)
    tail = messages.verdict.recognized_tail.format(
        messages=messages.common.failing_message.of(source.messages), where=where
    )
    return _entry(source.service, tail + _overrides(source))


def _other_line(source: FailingSource, messages: Messages) -> str:
    """
    Write a failing source that is not recognized.

    Args:
        source (FailingSource): The source.
        messages (Messages): The language.

    Returns:
        str: The address, what kind of source it is (with the configured selectors involved, so the
            owner can tell a copied selector from a broken one), its failing messages and its
            override types.
    """
    common = messages.common
    kind = common.kinds.get(source.outcome, common.kinds[Outcome.UNKNOWN])
    if source.selectors:
        names = ", ".join(fit(s, _NAME_MAX) for s in source.selectors)
        kind += f" ({common.selectors_named.of(len(source.selectors), names=names)})"
    where = fit(address(source.source_ip, common.no_address), _ADDRESS_MAX)
    tail = messages.verdict.other_tail.format(
        kind=kind, messages=common.failing_message.of(source.messages)
    )
    tail += _overrides(source) + spf_domains_part(messages, source.spf_domains, _NAME_MAX)
    return _entry(where, tail)


def _sources(
    sources: Sequence[FailingSource],
    limit: int,
    line: Callable[[FailingSource], str],
    messages: Messages,
) -> list[str]:
    """
    Write the first sources of a list and one line that still counts the others.

    Args:
        sources (Sequence[FailingSource]): The sources, the worst first.
        limit (int): How many to print.
        line (Callable[[FailingSource], str]): How to write one.
        messages (Messages): The language.

    Returns:
        list[str]: One line per printed source and, when some were left out, a line with how many
            and their failing messages.
    """
    lines = [line(source) for source in sources[:limit]]
    rest = sources[limit:]
    if rest:
        common = messages.common
        lines.append(
            "  "
            + common.more_failing.format(
                sources=common.other_source.of(len(rest)),
                messages=common.failing_message.of(sum(source.messages for source in rest)),
            )
        )
    return lines


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


def answer_phrase(verdict: Verdict, messages: Messages) -> str:
    """
    Say the answer as a phrase, with the policy already in force when it is ``p=reject`` (RF-05).

    The text format and the HTML report both read this phrase (008 ADR-2).

    Args:
        verdict (Verdict): The verdict.
        messages (Messages): The language.

    Returns:
        str: The phrase of the answer, in lower case as the title writes it after the colon.
    """
    text = messages.verdict
    if verdict.enforcing == "reject":
        return text.enforcing.format(words=text.words_enforcing[verdict.answer])
    return text.words[verdict.answer]


def _title(verdict: Verdict, messages: Messages) -> list[str]:
    """
    Write the title: the domain and the answer (RF-03, RF-05).

    Args:
        verdict (Verdict): The verdict.
        messages (Messages): The language.

    Returns:
        list[str]: One line when the domain fits beside the answer; otherwise two, with the domain
            cut at the first and the answer, capitalized, alone on the second.
    """
    text = messages.verdict
    phrase = answer_phrase(verdict, messages)
    domain = fit(verdict.domain, len(verdict.domain))
    one = f"{text.title.format(domain=domain)}: {phrase}"
    if len(one) <= _WIDTH:
        return [one]
    room = _WIDTH - len(text.title.format(domain=""))
    return [text.title.format(domain=fit(domain, room)), phrase[:1].upper() + phrase[1:]]


def missing_text(rule: Rule, messages: Messages) -> str:
    """
    Say what a failed data rule lacks.

    Args:
        rule (Rule): A failed data rule.
        messages (Messages): The language.

    Returns:
        str: For example ``need 1 more day`` or ``need 120 more messages``.
    """
    text = messages.verdict
    phrase = text.need_messages if rule.id is RuleId.VOLUME else text.need_days
    return phrase.of(rule.missing)


def reason_sentence(verdict: Verdict, messages: Messages) -> str:
    """
    Say why the answer is what it is, in one sentence and without its label (RF-03).

    The text format and the HTML report both read this sentence, so the rounding rule of the share
    (``_share``) lives once (008 ADR-2).

    Args:
        verdict (Verdict): The verdict.
        messages (Messages): The language.

    Returns:
        str: For ``READY`` and ``TOO_EARLY`` the fixed sentence of the answer (a run with no report
            kept is also ``TOO_EARLY``); for ``NOT_READY`` the sentence of the rule that decided,
            with the share of rule 5 filled in.
    """
    text = messages.verdict
    if verdict.answer is Answer.READY:
        return text.why_ready
    if verdict.answer is Answer.TOO_EARLY:
        return text.why_too_early
    if verdict.deciding is RuleId.RECOGNIZED_FAILURES:
        return text.why_recognized
    rule = _rule(verdict, RuleId.UNRECOGNIZED_FAILURES)
    return text.why_unrecognized.format(
        share=_share(rule),
        measured=rule.measured,
        whole=rule.whole,
        limit=_per_mille(rule.needed),
    )


def _why(verdict: Verdict, messages: Messages) -> list[str]:
    """
    Write the reason: the rule that decided and the sources or amounts behind it (RF-03).

    Args:
        verdict (Verdict): The verdict.
        messages (Messages): The language.

    Returns:
        list[str]: The reason sentence, with its label, and its lines, by answer.
    """
    text = messages.verdict
    label = text.why_label
    sentence = f"{label} {reason_sentence(verdict, messages)}"
    if verdict.answer is Answer.READY:
        lines = [sentence]
        if verdict.unrecognized_failing:
            lines.append(text.still_failing)
            lines.extend(
                _sources(
                    verdict.unrecognized_failing,
                    _UNRECOGNIZED_LIMIT,
                    partial(_other_line, messages=messages),
                    messages,
                )
            )
        return lines

    if verdict.answer is Answer.TOO_EARLY:
        lines = [sentence]
        if _rule(verdict, RuleId.PERIOD).measured == 0:
            lines.append("  " + text.no_report_kept)
            return lines
        for rule in verdict.rules:
            if rule.kind is RuleKind.DATA and not rule.passed:
                lines.append(f"  {text.rule_names[rule.id]}: {missing_text(rule, messages)}")
        return lines

    if verdict.deciding is RuleId.RECOGNIZED_FAILURES:
        lines = [sentence]
        lines.extend(
            _sources(
                verdict.recognized_failing,
                _RECOGNIZED_LIMIT,
                partial(_recognized_line, messages=messages),
                messages,
            )
        )
        return lines

    lines = _wrap(sentence, rest=" " * (len(label) + 1))
    lines.extend(
        _sources(
            verdict.unrecognized_failing,
            _UNRECOGNIZED_LIMIT,
            partial(_other_line, messages=messages),
            messages,
        )
    )
    return lines


def measured_text(rule: Rule, messages: Messages) -> str:
    """
    Write what a rule measured, a share always beside its count (004 RF-06).

    Args:
        rule (Rule): The rule.
        messages (Messages): The language.

    Returns:
        str: For example ``28 days``, ``27 of 28 (96.4%)`` or ``12 (0.1%)``.
    """
    share = _share(rule)
    if rule.id is RuleId.PERIOD:
        return messages.common.day.of(rule.measured)
    if rule.id is RuleId.COVERAGE:
        return messages.verdict.measured_coverage.format(
            measured=rule.measured, whole=rule.whole, share=share
        )
    if rule.id is RuleId.UNRECOGNIZED_FAILURES:
        return f"{rule.measured} ({share})"
    return str(rule.measured)


def needed_text(rule: Rule) -> str:
    """
    Write the threshold of a rule, in the unit it is kept in.

    Args:
        rule (Rule): The rule.

    Returns:
        str: The comparison and the number: ``>= 28``, ``>= 80%``, ``<= 0`` or ``<= 0.5%``.
    """
    if rule.id is RuleId.COVERAGE:
        value = f"{rule.needed}%"
    elif rule.id is RuleId.UNRECOGNIZED_FAILURES:
        value = _per_mille(rule.needed)
    else:
        value = str(rule.needed)
    return f"{'>=' if rule.at_least else '<='} {value}"


def _result(rule: Rule, messages: Messages) -> str:
    """
    Write the result of a rule, telling the two kinds of failure apart (RF-01).

    Args:
        rule (Rule): The rule.
        messages (Messages): The language.

    Returns:
        str: The word for a pass, for a failed problem rule or for a failed data rule.
    """
    text = messages.verdict
    if rule.passed:
        return text.result_pass
    return text.result_fail if rule.kind is RuleKind.PROBLEM else text.result_too_early


def _table(verdict: Verdict, messages: Messages) -> list[str]:
    """
    Write the rules table: the whole criterion, rule by rule (RF-03).

    Args:
        verdict (Verdict): The verdict.
        messages (Messages): The language.

    Returns:
        list[str]: The title, the header and one line per rule. The columns are as wide as their
            data; the measured column gives way if a huge count would push a line past the screen.
    """
    text = messages.verdict
    header = (text.col_rule, text.col_measured, text.col_needed, text.col_result)
    rows = [
        (
            f"{int(rule.id)}  {text.rule_names[rule.id]}",
            measured_text(rule, messages),
            needed_text(rule),
            _result(rule, messages),
        )
        for rule in verdict.rules
    ]
    widths = [max(len(cell) for cell in column) for column in zip(header, *rows, strict=True)]
    # 1. The line is two for the margin, two between each pair of columns and an unpadded last one.
    room = _WIDTH - 2 - 3 * 2 - widths[0] - widths[2] - widths[3]
    widths[1] = max(1, min(widths[1], room))

    def line(cells: Sequence[str]) -> str:
        """Place the four cells of a row in their columns."""
        first, measured, needed, result = cells
        return (
            f"  {first:<{widths[0]}}  {fit(measured, widths[1]):<{widths[1]}}"
            f"  {needed:<{widths[2]}}  {result}"
        )

    return [text.rules_title, line(header), *(line(row) for row in rows)]


# What each note says. A test iterates ``NoteKind``, so a kind added later cannot reach the output
# as a bare key. Each function fills the template of its kind with the numbers of the note.


def _fragile(note: Note, messages: Messages) -> str:
    """Say how much traffic passes by one mechanism only, and how much of it by SPF."""
    fragile, spf_only, total = note.numbers
    return messages.verdict.notes[NoteKind.FRAGILE].format(
        fragile=fragile, total=total, share=format_share(fragile, total), spf_only=spf_only
    )


def _partial(note: Note, messages: Messages) -> str:
    """Say that the policy applies to part of the mail."""
    return messages.verdict.notes[NoteKind.PARTIAL_POLICY].format(pct=note.numbers[0])


def _changed(note: Note, messages: Messages) -> str:
    """Say that the figures mix two policies."""
    earlier = ", ".join(fit(text, _NAME_MAX) for text in note.texts)
    return messages.verdict.notes[NoteKind.POLICY_CHANGED].format(earlier=earlier)


def _subdomains(note: Note, messages: Messages) -> str:
    """Show the policy subdomains already have, which moving ``p`` does not change."""
    sp, np = note.texts
    pairs = (("sp", sp), ("np", np))
    shown = ", ".join(f"{key}={fit(value, _NAME_MAX)}" for key, value in pairs if value)
    return messages.verdict.notes[NoteKind.SUBDOMAIN_POLICY].format(shown=shown)


def _quarantine(note: Note, messages: Messages) -> str:
    """Say that the current policy is ``quarantine``."""
    return messages.verdict.notes[NoteKind.CURRENTLY_QUARANTINE].format()


def _silent(note: Note, messages: Messages) -> str:
    """Say which large reporter went quiet, and for how long."""
    days, sent, total = note.numbers
    return messages.verdict.notes[NoteKind.SILENT_REPORTER].format(
        name=fit(note.texts[0], _NAME_MAX), share=format_share(sent, total), days=days
    )


def _stale(note: Note, messages: Messages) -> str:
    """Say how long ago the latest report ended."""
    return messages.verdict.notes[NoteKind.STALE].format(days=note.numbers[0])


_NOTE_TEXT: dict[NoteKind, Callable[[Note, Messages], str]] = {
    NoteKind.FRAGILE: _fragile,
    NoteKind.PARTIAL_POLICY: _partial,
    NoteKind.POLICY_CHANGED: _changed,
    NoteKind.SUBDOMAIN_POLICY: _subdomains,
    NoteKind.CURRENTLY_QUARANTINE: _quarantine,
    NoteKind.SILENT_REPORTER: _silent,
    NoteKind.STALE: _stale,
}


def note_sentence(note: Note, messages: Messages) -> str:
    """
    Write one note as a sentence, whatever its kind.

    Args:
        note (Note): The note.
        messages (Messages): The language.

    Returns:
        str: The template of the note's kind with its numbers and texts filled in.
    """
    return _NOTE_TEXT[note.kind](note, messages)


def _notes(verdict: Verdict, messages: Messages) -> list[str]:
    """
    Write the notes, one sentence each, only those present (RF-04).

    Args:
        verdict (Verdict): The verdict.
        messages (Messages): The language.

    Returns:
        list[str]: The title and the notes; nothing when there are none.
    """
    if not verdict.notes:
        return []
    lines = [messages.verdict.notes_title]
    for note in verdict.notes:
        lines.extend(_wrap(note_sentence(note, messages), "  - ", "    "))
    return lines


def next_sentence(verdict: Verdict, messages: Messages, *, on_page: bool = False) -> str:
    """
    Say the next step in one sentence, chosen by the rule that decided, without its label (RF-03).

    Args:
        verdict (Verdict): The verdict.
        messages (Messages): The language.
        on_page (bool, optional): ``True`` for the HTML page, which lists the failing sources
            after the next step where the text lists them before it, so the two sentences that
            point at them say "below" instead of "above". Default: ``False``.

    Returns:
        str: The sentence; empty for ``READY``.
    """
    if verdict.deciding is None:
        return ""
    text = messages.verdict
    each_service = messages.html.next_each_service if on_page else text.next_each_service
    unrecognized = messages.html.next_unrecognized if on_page else text.next_unrecognized
    if verdict.deciding is RuleId.RECOGNIZED_FAILURES:
        services = list(dict.fromkeys(source.service for source in verdict.recognized_failing))
        who = fit(services[0], _NAME_MAX) if len(services) == 1 else each_service
        return text.next_recognized.format(who=who)
    if verdict.deciding is RuleId.UNRECOGNIZED_FAILURES:
        return unrecognized
    return text.next_data.format(marker=text.result_too_early)


def _next_step(verdict: Verdict, messages: Messages) -> list[str]:
    """
    Write the next step, labeled and wrapped (RF-03).

    Args:
        verdict (Verdict): The verdict.
        messages (Messages): The language.

    Returns:
        list[str]: The sentence; nothing for ``READY``.
    """
    body = next_sentence(verdict, messages)
    if not body:
        return []
    label = messages.verdict.next_label
    return _wrap(f"{label} {body}", rest=" " * (len(label) + 1))


def left_out_parts(verdict: Verdict, messages: Messages) -> list[str]:
    """
    Name what the summary did not count, one phrase per kind, only the kinds above zero (RF-09).

    The phrases give counts and no file name: the names and the reasons are in ``summary``. The
    text format and the HTML report both read them (008 ADR-2).

    Args:
        verdict (Verdict): The verdict.
        messages (Messages): The language.

    Returns:
        list[str]: For example ``2 files skipped``; empty when every count is zero.
    """
    text = messages.verdict
    left = verdict.left_out
    parts = [
        text.skipped_file.of(left.skipped) if left.skipped else "",
        text.duplicate.of(left.duplicates) if left.duplicates else "",
        text.other_domain.of(left.other_domain) if left.other_domain else "",
        text.passed_over.of(left.passed_over) if left.passed_over else "",
    ]
    return [part for part in parts if part]


def _left_out(verdict: Verdict, messages: Messages) -> list[str]:
    """
    Say what the summary did not count, in one sentence, only when something was left out (RF-09).

    Args:
        verdict (Verdict): The verdict.
        messages (Messages): The language.

    Returns:
        list[str]: The wrapped sentence; nothing when every count is zero.
    """
    shown = left_out_parts(verdict, messages)
    if not shown:
        return []
    return _wrap(messages.verdict.left_out.format(parts=", ".join(shown)), rest=" " * 4)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def render_verdict(verdict: Verdict, messages: Messages = ENGLISH) -> str:
    """
    Turn a verdict into the text of the command.

    Args:
        verdict (Verdict): The verdict, complete: the limits are applied here.
        messages (Messages, optional): The language. Default: English.

    Returns:
        str: The title, the reason, the rules table, the notes (when present), the next step (unless
            ready), what was left out (when anything was) and the closing sentence, separated by
            one blank line, without a trailing newline.
    """
    sections = [
        _title(verdict, messages),
        _why(verdict, messages),
        _table(verdict, messages),
        _notes(verdict, messages),
        _next_step(verdict, messages),
        _left_out(verdict, messages),
        _wrap(messages.verdict.caveat),
    ]
    return "\n\n".join("\n".join(lines) for lines in sections if lines)


def render_tally(verdicts: Iterable[Verdict], messages: Messages = ENGLISH) -> str:
    """
    Count the answers of several domains in one line (spec 010, RF-05, ADR-5).

    Args:
        verdicts (Iterable[Verdict]): The verdicts of the run.
        messages (Messages, optional): The language. Default: English.

    Returns:
        str: The number of domains and, for each answer that someone has, how many, ready first and
            not ready last, with no trailing newline.
    """
    text = messages.verdict
    answers = [verdict.answer for verdict in verdicts]
    parts = [
        phrase.of(answers.count(answer))
        for answer, phrase in (
            (Answer.READY, text.tally_ready),
            (Answer.TOO_EARLY, text.tally_early),
            (Answer.NOT_READY, text.tally_not_ready),
        )
        if answer in answers
    ]
    return text.tally.of(len(answers), parts=", ".join(parts))
