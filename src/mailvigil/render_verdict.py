"""
The text of the verdict: a frozen ``Verdict`` turned into the sections of the command.

Everything the verdict says in English lives here, so spec 006 replaces text modules (language,
``--json``) without touching the rules (RNF-03). The limits on the sources and their "and N more"
lines are applied here and never in ``judge``, which keeps the complete data. The thresholds shown
come from the rules of the ``Verdict``, which ``judge`` builds from the constants of ``verdict.py``,
so no number of the criterion is typed twice (RNF-05). The layout follows the summary's: ASCII, 80
columns at most, no color; the text is returned without a trailing newline and writing it is the
command's. The words "safe" and "attack" are not used anywhere: the verdict reads reports, it does
not certify a domain and it does not guess intent.
"""

from __future__ import annotations

import textwrap
from collections.abc import Callable, Sequence

from mailvigil.render import address, count_noun, fit, format_share
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

# The title words. A test iterates ``Answer``, so an answer added later cannot reach the output as
# a bare key.
_WORDS = {
    Answer.READY: "READY for p=reject",
    Answer.TOO_EARLY: "TOO EARLY to say",
    Answer.NOT_READY: "NOT READY for p=reject",
}
# Under ``p=reject`` the question is "is enforcement blocking mail it should not" (RF-05).
_WORDS_ENFORCING = {
    Answer.READY: "NO PROBLEM SEEN",
    Answer.TOO_EARLY: "TOO EARLY to say",
    Answer.NOT_READY: "BLOCKING REAL MAIL",
}

# One name per rule, short so the table fits in 80 columns beside a share and a count.
_RULE_NAMES = {
    RuleId.PERIOD: "period covered",
    RuleId.COVERAGE: "days with a report",
    RuleId.VOLUME: "messages seen",
    RuleId.RECOGNIZED_FAILURES: "recognized failures",
    RuleId.UNRECOGNIZED_FAILURES: "unrecognized failures",
}

# How a source that was not recognized is described, as the summary does. ``KNOWN`` has no entry:
# it is named by its service.
_KIND_WORDS = {
    Outcome.UNKNOWN: "unrecognized",
    Outcome.FOREIGN_DOMAIN: "foreign domain",
    Outcome.FAILING_SIGNATURE: "failing signature",
}

# The one sentence that closes every verdict (design, Risk 3 and 4).
_CAVEAT = (
    "This reads only the reports you gave it: mail that no receiver reports on, and senders that "
    "were quiet in this period, are not covered."
)

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


def _recognized_line(source: FailingSource) -> str:
    """
    Write a failing source of a recognized sender.

    Args:
        source (FailingSource): The source.

    Returns:
        str: The service, its failing messages, its address and its override types.
    """
    where = fit(address(source.source_ip), _ADDRESS_MAX)
    messages = count_noun(source.messages, "failing message")
    return _entry(source.service, f": {messages} from {where}{_overrides(source)}")


def _other_line(source: FailingSource) -> str:
    """
    Write a failing source that is not recognized.

    Args:
        source (FailingSource): The source.

    Returns:
        str: The address, what kind of source it is (with the configured selectors involved, so the
            owner can tell a copied selector from a broken one), its failing messages and its
            override types.
    """
    kind = _KIND_WORDS.get(source.outcome, "unrecognized")
    if source.selectors:
        noun = "selector" if len(source.selectors) == 1 else "selectors"
        kind += f" ({noun} {', '.join(fit(s, _NAME_MAX) for s in source.selectors)})"
    messages = count_noun(source.messages, "failing message")
    where = fit(address(source.source_ip), _ADDRESS_MAX)
    return _entry(where, f"  {kind}: {messages}{_overrides(source)}")


def _sources(
    sources: Sequence[FailingSource], limit: int, line: Callable[[FailingSource], str]
) -> list[str]:
    """
    Write the first sources of a list and one line that still counts the others.

    Args:
        sources (Sequence[FailingSource]): The sources, the worst first.
        limit (int): How many to print.
        line (Callable[[FailingSource], str]): How to write one.

    Returns:
        list[str]: One line per printed source and, when some were left out, a line with how many
            and their failing messages.
    """
    lines = [line(source) for source in sources[:limit]]
    rest = sources[limit:]
    if rest:
        hidden = sum(source.messages for source in rest)
        lines.append(
            f"  ... and {count_noun(len(rest), 'other source')}: "
            f"{count_noun(hidden, 'failing message')}"
        )
    return lines


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


def _title(verdict: Verdict) -> list[str]:
    """
    Write the title: the domain and the answer (RF-03, RF-05).

    Args:
        verdict (Verdict): The verdict.

    Returns:
        list[str]: One line when the domain fits beside the answer; otherwise two, with the domain
            cut at the first and the answer, capitalized, alone on the second.
    """
    if verdict.enforcing == "reject":
        phrase = f"already at p=reject: {_WORDS_ENFORCING[verdict.answer]}"
    else:
        phrase = _WORDS[verdict.answer]
    head = "MailVigil verdict for "
    domain = fit(verdict.domain, len(verdict.domain))
    one = f"{head}{domain}: {phrase}"
    if len(one) <= _WIDTH:
        return [one]
    return [head + fit(domain, _WIDTH - len(head)), phrase[:1].upper() + phrase[1:]]


def _missing(rule: Rule) -> str:
    """
    Say what a failed data rule lacks.

    Args:
        rule (Rule): A failed data rule.

    Returns:
        str: For example ``need 1 more day`` or ``need 120 more messages``.
    """
    noun = "message" if rule.id is RuleId.VOLUME else "day"
    return f"need {rule.missing} more {noun if rule.missing == 1 else noun + 's'}"


def _why(verdict: Verdict) -> list[str]:
    """
    Write the reason: the rule that decided and the sources or amounts behind it (RF-03).

    Args:
        verdict (Verdict): The verdict.

    Returns:
        list[str]: The ``Why:`` sentence and its lines, by answer.
    """
    if verdict.answer is Answer.READY:
        lines = ["Why: every rule passes."]
        if verdict.unrecognized_failing:
            lines.append("Still failing from unrecognized sources, under the limit:")
            lines.extend(_sources(verdict.unrecognized_failing, _UNRECOGNIZED_LIMIT, _other_line))
        return lines

    if verdict.answer is Answer.TOO_EARLY:
        lines = ["Why: not enough reports to tell yet."]
        if _rule(verdict, RuleId.PERIOD).measured == 0:
            lines.append("  no report was kept for this domain")
            return lines
        for rule in verdict.rules:
            if rule.kind is RuleKind.DATA and not rule.passed:
                lines.append(f"  {_RULE_NAMES[rule.id]}: {_missing(rule)}")
        return lines

    if verdict.deciding is RuleId.RECOGNIZED_FAILURES:
        lines = ["Why: a recognized sender fails DMARC."]
        lines.extend(_sources(verdict.recognized_failing, _RECOGNIZED_LIMIT, _recognized_line))
        return lines

    rule = _rule(verdict, RuleId.UNRECOGNIZED_FAILURES)
    sentence = (
        "Why: failures from unrecognized sources are "
        f"{format_share(rule.measured, rule.whole)} of the messages ({rule.measured} of "
        f"{rule.whole}); the limit is {_per_mille(rule.needed)}."
    )
    lines = _wrap(sentence, rest=" " * 5)
    lines.extend(_sources(verdict.unrecognized_failing, _UNRECOGNIZED_LIMIT, _other_line))
    return lines


def _measured(rule: Rule) -> str:
    """
    Write what a rule measured, a share always beside its count (004 RF-06).

    Args:
        rule (Rule): The rule.

    Returns:
        str: For example ``28 days``, ``27 of 28 (96.4%)`` or ``12 (0.1%)``.
    """
    share = format_share(rule.measured, rule.whole)
    if rule.id is RuleId.PERIOD:
        return count_noun(rule.measured, "day")
    if rule.id is RuleId.COVERAGE:
        return f"{rule.measured} of {rule.whole} ({share})"
    if rule.id is RuleId.UNRECOGNIZED_FAILURES:
        return f"{rule.measured} ({share})"
    return str(rule.measured)


def _needed(rule: Rule) -> str:
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


def _result(rule: Rule) -> str:
    """
    Write the result of a rule, telling the two kinds of failure apart (RF-01).

    Args:
        rule (Rule): The rule.

    Returns:
        str: ``pass``, ``FAIL`` for a problem rule or ``fail (too early)`` for a data rule.
    """
    if rule.passed:
        return "pass"
    return "FAIL" if rule.kind is RuleKind.PROBLEM else "fail (too early)"


def _table(verdict: Verdict) -> list[str]:
    """
    Write the rules table: the whole criterion, rule by rule (RF-03).

    Args:
        verdict (Verdict): The verdict.

    Returns:
        list[str]: The title, the header and one line per rule. The columns are as wide as their
            data; the measured column gives way if a huge count would push a line past the screen.
    """
    header = ("rule", "measured", "needed", "result")
    rows = [
        (
            f"{int(rule.id)}  {_RULE_NAMES[rule.id]}",
            _measured(rule),
            _needed(rule),
            _result(rule),
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

    return ["Rules", line(header), *(line(row) for row in rows)]


# What each note says. A test iterates ``NoteKind``, so a kind added later cannot reach the output
# as a bare key.


def _fragile(note: Note) -> str:
    """Say how much traffic passes by one mechanism only, and how much of it by SPF."""
    fragile, spf_only, total = note.numbers
    return (
        f"Fragile traffic: {fragile} of {total} messages ({format_share(fragile, total)}) pass by "
        f"only one of DKIM and SPF; {spf_only} of those by SPF only, which forwarding breaks."
    )


def _partial(note: Note) -> str:
    """Say that the policy applies to part of the mail."""
    pct = note.numbers[0]
    return f"The policy applies to only {pct}% of the mail (pct={pct})."


def _changed(note: Note) -> str:
    """Say that the figures mix two policies."""
    earlier = ", ".join(fit(text, _NAME_MAX) for text in note.texts)
    return (
        f"The policy changed during the period (earlier p: {earlier}), so the figures mix policies."
    )


def _subdomains(note: Note) -> str:
    """Show the policy subdomains already have, which moving ``p`` does not change."""
    sp, np = note.texts
    pairs = (("sp", sp), ("np", np))
    shown = ", ".join(f"{key}={fit(value, _NAME_MAX)}" for key, value in pairs if value)
    return f"Subdomains have their own policy ({shown}): moving p does not change it."


def _quarantine(note: Note) -> str:
    """Say that the current policy is ``quarantine``."""
    return "The policy is p=quarantine now; this verdict is about moving to p=reject."


_NOTE_TEXT: dict[NoteKind, Callable[[Note], str]] = {
    NoteKind.FRAGILE: _fragile,
    NoteKind.PARTIAL_POLICY: _partial,
    NoteKind.POLICY_CHANGED: _changed,
    NoteKind.SUBDOMAIN_POLICY: _subdomains,
    NoteKind.CURRENTLY_QUARANTINE: _quarantine,
}


def _notes(verdict: Verdict) -> list[str]:
    """
    Write the notes, one sentence each, only those present (RF-04).

    Args:
        verdict (Verdict): The verdict.

    Returns:
        list[str]: The title and the notes; nothing when there are none.
    """
    if not verdict.notes:
        return []
    lines = ["Notes"]
    for note in verdict.notes:
        lines.extend(_wrap(_NOTE_TEXT[note.kind](note), "  - ", "    "))
    return lines


def _next_step(verdict: Verdict) -> list[str]:
    """
    Write the next step, one sentence chosen by the rule that decided (RF-03).

    Args:
        verdict (Verdict): The verdict.

    Returns:
        list[str]: The sentence; nothing for ``READY``.
    """
    if verdict.deciding is None:
        return []
    if verdict.deciding is RuleId.RECOGNIZED_FAILURES:
        services = list(dict.fromkeys(source.service for source in verdict.recognized_failing))
        who = fit(services[0], _NAME_MAX) if len(services) == 1 else "each service listed above"
        text = (
            f"Next: make {who} sign with your domain (DKIM) or add its servers to SPF, then "
            "collect another period."
        )
    elif verdict.deciding is RuleId.UNRECOGNIZED_FAILURES:
        text = (
            "Next: look at the sources above and add the selectors of the ones that are yours to "
            "[senders] in the configuration."
        )
    else:
        text = "Next: keep collecting reports until the rules marked 'fail (too early)' pass."
    return _wrap(text, rest=" " * 6)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def render_verdict(verdict: Verdict) -> str:
    """
    Turn a verdict into the text of the command.

    Args:
        verdict (Verdict): The verdict, complete: the limits are applied here.

    Returns:
        str: The title, the reason, the rules table, the notes (when present), the next step (unless
            ready) and the closing sentence, separated by one blank line, without a trailing
            newline.
    """
    sections = [
        _title(verdict),
        _why(verdict),
        _table(verdict),
        _notes(verdict),
        _next_step(verdict),
        _wrap(_CAVEAT),
    ]
    return "\n\n".join("\n".join(lines) for lines in sections if lines)
