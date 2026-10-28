"""
The JSON documents: ``Summary`` and ``Verdict`` as data a script can rely on.

``summary_document`` and ``verdict_document`` turn the frozen values into plain ``dict``s, key by
key, and ``dumps`` writes one as JSON. The mapping is written by hand, type by type, so the public
shape is a decision and not a by-product of the field names of the model (ADR-2): a field renamed
inside ``summary.py`` does not change the contract. Nothing is computed here: every number is read
from the value it came from, a share is never a field (RF-02), and a value the model may not have
is ``null``, never missing and never an empty string (RF-03). There is no sentence and no language
in a document, so nothing in this module imports a text module.
"""

from __future__ import annotations

import json
from typing import Final

from mailvigil.reports import PolicyPublished, SkippedFile
from mailvigil.summary import Counts, FailingSource, Period, SenderRow, Summary
from mailvigil.verdict import LeftOut, Note, Rule, RuleId, Verdict

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
        "dkim": list(source.dkim),
        "spf": list(source.spf),
        "override_reasons": list(source.override_reasons),
    }


def _skipped(file: SkippedFile) -> dict[str, object]:
    """
    Write one refused file: its name without the folder and the reason, never the English detail.

    Args:
        file (SkippedFile): The refused file.

    Returns:
        dict[str, object]: ``name`` and ``reason``.
    """
    return {"name": file.path.name, "reason": file.reason.value}


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
        left_out (LeftOut): The three figures.

    Returns:
        dict[str, object]: ``skipped``, ``duplicates`` and ``other_domain``.
    """
    return {
        "skipped": left_out.skipped,
        "duplicates": left_out.duplicates,
        "other_domain": left_out.other_domain,
    }


# ---------------------------------------------------------------------------
# The documents (RF-02, RF-03)
# ---------------------------------------------------------------------------


def summary_document(summary: Summary, config_source: str | None) -> dict[str, object]:
    """
    Write the summary as data, with every row and every source (no display limit).

    Args:
        summary (Summary): What ``summarize`` produced.
        config_source (str | None): The configuration file as the user typed it, ``None`` when
            there was none.

    Returns:
        dict[str, object]: The document, its keys in the order of ``docs/json-schema.md``.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "command": "summary",
        "domain": summary.domain,
        "config": {"source": config_source, "selectors": summary.selectors_configured},
        "reports": {"count": summary.reports, "reporters": summary.reporters},
        "period": _period(summary.period),
        "policy": _policy(summary.policy),
        "earlier_p": list(summary.earlier_p),
        "totals": _counts(summary.totals),
        "recognized_messages": summary.recognized_messages,
        "senders": [_sender(row) for row in summary.senders],
        "failing": [_source(source) for source in summary.failing],
        "skipped": [_skipped(file) for file in summary.skipped],
        "skipped_by_reason": [
            {"reason": reason.value, "count": count} for reason, count in summary.skipped_by_reason
        ],
        "duplicates": summary.duplicates,
        "other_domain": summary.other_domain,
    }


def verdict_document(verdict: Verdict) -> dict[str, object]:
    """
    Write the verdict as data, with the five rules and every failing source.

    Args:
        verdict (Verdict): What ``judge`` produced.

    Returns:
        dict[str, object]: The document, its keys in the order of ``docs/json-schema.md``.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "command": "verdict",
        "domain": verdict.domain,
        "answer": verdict.answer.value,
        "enforcing": _or_none(verdict.enforcing),
        "deciding": None if verdict.deciding is None else _RULE_WORDS[verdict.deciding],
        "rules": [_rule(rule) for rule in verdict.rules],
        "recognized_failing": [_source(source) for source in verdict.recognized_failing],
        "unrecognized_failing": [_source(source) for source in verdict.unrecognized_failing],
        "notes": [_note(note) for note in verdict.notes],
        "left_out": _left_out(verdict.left_out),
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
