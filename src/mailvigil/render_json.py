"""
The JSON documents: ``Summary``, ``Verdict`` and ``FetchOutcome`` as data a script can rely on.

``summary_document``, ``verdict_document`` and ``fetch_document`` turn the frozen values into plain
``dict``s, key by key, and ``dumps`` writes one as JSON. A run of several domains wraps the
one-domain documents in an envelope (``summaries_document``, ``verdicts_document``; spec 010,
ADR-7). The mapping is written by hand, type by
type, so the public shape is a decision and not a by-product of the field names of the model
(ADR-2): a field renamed inside ``summary.py`` does not change the contract. Nothing is computed
here: every number is read from the value it came from, a share is never a field (RF-02), and a
value the model may not have is ``null``, never missing and never an empty string (RF-03). There is
no sentence and no language in a document, so nothing in this module imports a text module.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Final

from mailvigil.fetch.model import FetchOutcome
from mailvigil.reports import PolicyPublished, SkippedFile
from mailvigil.summary import Counts, FailingSource, Period, SenderRow, Summary
from mailvigil.verdict import LeftOut, Note, Rule, RuleId, Verdict, worst_answer

# ---------------------------------------------------------------------------
# The contract
# ---------------------------------------------------------------------------

#: The version of the documents; a field is added inside a version, and renamed, removed or
#: retyped only with a new one (RF-03).
SCHEMA_VERSION: Final = 1

# The stable word of each rule: a consumer identifies a rule by it, never by a translated name
# (RF-02). A test iterates ``RuleId``, so a sixth rule cannot reach the output without a word.
_RULE_WORDS: Final = {
    RuleId.PERIOD: "period_covered",
    RuleId.COVERAGE: "days_with_report",
    RuleId.VOLUME: "messages_seen",
    RuleId.RECOGNIZED_FAILURES: "recognized_failures",
    RuleId.UNRECOGNIZED_FAILURES: "unrecognized_failures",
}

# What ``needed`` and ``measured`` count, so a consumer never has to know that rule 5 keeps tenths
# of a percent (005 ADR-4).
_RULE_UNITS: Final = {
    RuleId.PERIOD: "days",
    RuleId.COVERAGE: "percent_of_days",
    RuleId.VOLUME: "messages",
    RuleId.RECOGNIZED_FAILURES: "messages",
    RuleId.UNRECOGNIZED_FAILURES: "per_mille_of_messages",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _or_none(value: str) -> str | None:
    """
    Turn the model's "nothing" into the document's.

    Args:
        value (str): A string field of the model.

    Returns:
        str | None: ``None`` for an empty string, otherwise the value.
    """
    return value or None


def _counts(counts: Counts) -> dict[str, object]:
    """
    Write the messages per situation.

    Args:
        counts (Counts): The counts.

    Returns:
        dict[str, object]: ``ok``, ``dkim_only``, ``spf_only``, ``failing`` and ``total``.
    """
    return {
        "ok": counts.ok,
        "dkim_only": counts.dkim_only,
        "spf_only": counts.spf_only,
        "failing": counts.failing,
        "total": counts.total,
    }


def _sender(row: SenderRow) -> dict[str, object]:
    """
    Write one row of the senders table.

    Args:
        row (SenderRow): The row.

    Returns:
        dict[str, object]: The ``sender`` object.
    """
    return {
        "outcome": row.outcome.value,
        "service": _or_none(row.service),
        "source_ip": _or_none(row.source_ip),
        "selectors": list(row.selectors),
        "spf_domains": list(row.spf_domains),
        "counts": _counts(row.counts),
    }


def _source(source: FailingSource) -> dict[str, object]:
    """
    Write one failing source; it is the same object in both documents.

    Args:
        source (FailingSource): The source.

    Returns:
        dict[str, object]: The ``source`` object.
    """
    return {
        "outcome": source.outcome.value,
        "service": _or_none(source.service),
        "source_ip": source.source_ip,
        "messages": source.messages,
        "selectors": list(source.selectors),
        "spf_domains": list(source.spf_domains),
        "dkim": list(source.dkim),
        "spf": list(source.spf),
        "override_reasons": list(source.override_reasons),
    }


def _skipped(file: SkippedFile) -> dict[str, object]:
    """
    Write one refused file: its name without the folder, the part of a mail file and the reason,
    never the English detail.

    Args:
        file (SkippedFile): The refused file.

    Returns:
        dict[str, object]: ``name``, ``part`` (``None`` for a loose file) and ``reason``.
    """
    return {"name": file.path.name, "part": file.part or None, "reason": file.reason.value}


def _period(period: Period | None) -> dict[str, object] | None:
    """
    Write the time the reports cover.

    Args:
        period (Period | None): The period, ``None`` without reports.

    Returns:
        dict[str, object] | None: The days as ``YYYY-MM-DD`` and the two counts, or ``None``.
    """
    if period is None:
        return None
    return {
        "first_day": period.first_day.isoformat(),
        "last_day": period.last_day.isoformat(),
        "days_spanned": period.days_spanned,
        "days_with_reports": period.days_with_reports,
    }


def _policy(policy: PolicyPublished | None) -> dict[str, object] | None:
    """
    Write the latest published policy.

    Args:
        policy (PolicyPublished | None): The policy, ``None`` without reports.

    Returns:
        dict[str, object] | None: ``p``, ``sp``, ``np`` and ``pct``, or ``None``.
    """
    if policy is None:
        return None
    return {
        "p": policy.p,
        "sp": _or_none(policy.sp),
        "np": _or_none(policy.np),
        "pct": policy.pct,
    }


def _rule(rule: Rule) -> dict[str, object]:
    """
    Write one rule, with its stable word and the unit of its numbers.

    Args:
        rule (Rule): The rule.

    Returns:
        dict[str, object]: The ``rule`` object.
    """
    return {
        "id": _RULE_WORDS[rule.id],
        "kind": rule.kind.value,
        "measured": rule.measured,
        "whole": rule.whole,
        "needed": rule.needed,
        "unit": _RULE_UNITS[rule.id],
        "comparison": "at_least" if rule.at_least else "at_most",
        "passed": rule.passed,
        "missing": rule.missing,
    }


def _note(note: Note) -> dict[str, object]:
    """
    Write one note as the kind, the figures and the words ``judge`` built.

    A text that is empty means "absent" in the model (the ``sp`` and ``np`` of the subdomain note),
    so it is ``null`` here and keeps its position.

    Args:
        note (Note): The note.

    Returns:
        dict[str, object]: ``kind``, ``numbers`` and ``texts``.
    """
    return {
        "kind": note.kind.value,
        "numbers": list(note.numbers),
        "texts": [_or_none(text) for text in note.texts],
    }


def _left_out(left_out: LeftOut) -> dict[str, object]:
    """
    Write what the summary did not count.

    Args:
        left_out (LeftOut): The four figures.

    Returns:
        dict[str, object]: ``skipped``, ``duplicates``, ``other_domain`` and ``passed_over``.
    """
    return {
        "skipped": left_out.skipped,
        "duplicates": left_out.duplicates,
        "other_domain": left_out.other_domain,
        "passed_over": left_out.passed_over,
    }


def _cut[T](items: Sequence[T], top: int | None) -> tuple[Sequence[T], int]:
    """
    Keep the first ``top`` items of a list that is already sorted worst first.

    Args:
        items (Sequence[T]): The whole list.
        top (int | None): How many to keep; ``None`` keeps all.

    Returns:
        tuple[Sequence[T], int]: What was kept and how many items were left out.
    """
    if top is None:
        return items, 0
    return items[:top], max(len(items) - top, 0)


def _top(limit: int | None, left_out: dict[str, int]) -> dict[str, object]:
    """
    Write the ``top`` key a trimmed document carries (spec 006, ADR-8).

    Args:
        limit (int | None): The ``--top`` given; ``None`` when the document was not trimmed.
        left_out (dict[str, int]): For each trimmed list, how many items were left out.

    Returns:
        dict[str, object]: ``{"top": {...}}`` when trimmed, and nothing when not, so a document made
            without ``--top`` stays byte-equal to the one that never had the key.
    """
    if limit is None:
        return {}
    return {"top": {"limit": limit, "left_out": left_out}}


# ---------------------------------------------------------------------------
# The documents (RF-02, RF-03)
# ---------------------------------------------------------------------------


def summary_document(
    summary: Summary, config_source: str | None, top: int | None = None
) -> dict[str, object]:
    """
    Write the summary as data, with every row and every source (no display limit).

    Args:
        summary (Summary): What ``summarize`` produced.
        config_source (str | None): The configuration file as the user typed it, ``None`` when
            there was none.
        top (int | None, optional): Keep only this many senders and failing sources (``--top``) and
            say so in a ``top`` key. Default: keep them all, with no such key.

    Returns:
        dict[str, object]: The document, its keys in the order of ``docs/json-schema.md``.
    """
    senders, senders_out = _cut(summary.senders, top)
    failing, failing_out = _cut(summary.failing, top)
    return {
        "schema_version": SCHEMA_VERSION,
        "command": "summary",
        "domain": summary.domain,
        "config": {
            "source": config_source,
            "selectors": summary.selectors_configured,
            "spf_domains": summary.spf_domains_configured,
            "ip_ranges": summary.ip_ranges_configured,
        },
        "reports": {"count": summary.reports, "reporters": summary.reporters},
        "period": _period(summary.period),
        "policy": _policy(summary.policy),
        "earlier_p": list(summary.earlier_p),
        "totals": _counts(summary.totals),
        "recognized_messages": summary.recognized_messages,
        "senders": [_sender(row) for row in senders],
        "failing": [_source(source) for source in failing],
        "skipped": [_skipped(file) for file in summary.skipped],
        "skipped_by_reason": [
            {"reason": reason.value, "count": count} for reason, count in summary.skipped_by_reason
        ],
        "duplicates": summary.duplicates,
        "other_domain": summary.other_domain,
        "passed_over": summary.passed_over,
        **_top(top, {"senders": senders_out, "failing": failing_out}),
    }


def verdict_document(verdict: Verdict, top: int | None = None) -> dict[str, object]:
    """
    Write the verdict as data, with the five rules and every failing source.

    Args:
        verdict (Verdict): What ``judge`` produced.
        top (int | None, optional): Keep only this many failing sources of each kind (``--top``)
            and say so in a ``top`` key; the answer and the rules are not touched. Default: keep
            them all, with no such key.

    Returns:
        dict[str, object]: The document, its keys in the order of ``docs/json-schema.md``.
    """
    recognized, recognized_out = _cut(verdict.recognized_failing, top)
    unrecognized, unrecognized_out = _cut(verdict.unrecognized_failing, top)
    return {
        "schema_version": SCHEMA_VERSION,
        "command": "verdict",
        "domain": verdict.domain,
        "answer": verdict.answer.value,
        "enforcing": _or_none(verdict.enforcing),
        "deciding": None if verdict.deciding is None else _RULE_WORDS[verdict.deciding],
        "rules": [_rule(rule) for rule in verdict.rules],
        "recognized_failing": [_source(source) for source in recognized],
        "unrecognized_failing": [_source(source) for source in unrecognized],
        "notes": [_note(note) for note in verdict.notes],
        "left_out": _left_out(verdict.left_out),
        **_top(
            top,
            {"recognized_failing": recognized_out, "unrecognized_failing": unrecognized_out},
        ),
    }


def summaries_document(
    summaries: Sequence[Summary], config_source: str | None, top: int | None = None
) -> dict[str, object]:
    """
    Wrap the summaries of a run of several domains in one document (spec 010, ADR-7).

    Each element of ``domains`` is the document a run of that one domain prints, so a script that
    reads one reads the other; the envelope adds nothing of its own beyond the version and the
    command. ``schema_version`` stays ``1``: the envelope is a new shape, reached only by naming
    two or more domains, and no existing document changes.

    Args:
        summaries (Sequence[Summary]): One summary per domain, in the order of the run.
        config_source (str | None): The configuration file as the user typed it, ``None`` when
            there was none; every element carries it.
        top (int | None, optional): Passed to each element, which then says in its own ``top`` key
            what it left out. Default: keep every entry.

    Returns:
        dict[str, object]: ``schema_version``, ``command`` and ``domains``, in that order.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "command": "summary",
        "domains": [summary_document(summary, config_source, top) for summary in summaries],
    }


def verdicts_document(verdicts: Sequence[Verdict], top: int | None = None) -> dict[str, object]:
    """
    Wrap the verdicts of a run of several domains in one document (spec 010, ADR-7).

    The envelope carries the worst answer, the one the exit code stands for (ADR-6), so a script
    reads the meaning of the code from the document.

    Args:
        verdicts (Sequence[Verdict]): One verdict per domain, in the order of the run.
        top (int | None, optional): Passed to each element, which then says in its own ``top`` key
            what it left out. Default: keep every entry.

    Returns:
        dict[str, object]: ``schema_version``, ``command``, ``answer`` and ``domains``, in that
            order.

    Raises:
        ValueError: When ``verdicts`` is empty: a run always has a domain.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "command": "verdict",
        "answer": worst_answer(verdicts).value,
        "domains": [verdict_document(verdict, top) for verdict in verdicts],
    }


def fetch_document(outcome: FetchOutcome) -> dict[str, object]:
    """
    Write what a finished ``fetch`` run did as data: the six numbers and nothing else.

    The document has no ``domain`` (the command is about a mailbox, not a domain) and no folder,
    host or user: those are the caller's own words and a path of the machine is not part of a
    document. A refused run has no document (spec 009, ADR-11).

    Args:
        outcome (FetchOutcome): The six numbers of the run.

    Returns:
        dict[str, object]: The document, its keys in the order of ``docs/json-schema.md``.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "command": "fetch",
        "matched": outcome.matched,
        "saved": outcome.saved,
        "already": outcome.already,
        "too_large": outcome.too_large,
        "skipped": outcome.skipped,
        "left": outcome.left,
    }


def dumps(document: dict[str, object]) -> str:
    """
    Write a document as JSON: indented, ASCII only and without a trailing newline.

    ``ensure_ascii`` turns a non-ASCII letter into a ``\\uXXXX`` escape, so no console encoding can
    corrupt it (RF-01). ``allow_nan=False`` makes a stray ``NaN`` an error instead of invalid JSON;
    the documents hold no float, so it never fires.

    Args:
        document (dict[str, object]): A document from this module.

    Returns:
        str: The JSON text; the command adds the newline.

    Raises:
        ValueError: When the document holds a ``NaN`` or an infinity.
    """
    return json.dumps(document, ensure_ascii=True, allow_nan=False, indent=2)
