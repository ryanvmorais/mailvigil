"""
The verdict: is this domain ready for ``p=reject``, by five named rules.

``judge`` turns a ``Summary`` into a frozen ``Verdict``: five rules, each with the value measured,
the threshold and the result; the answer derived from them; the failing sources behind it; and the
notes that qualify it without changing it. It holds the complete data and nothing to print: no
label, phrase or percentage string (RNF-03). The text is ``render_verdict.py``'s, so spec 006
replaces text modules and not these rules. It does no I/O, reads no clock and never raises on a
``Summary`` it is given (RNF-02).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum

from mailvigil.senders import Outcome
from mailvigil.summary import FailingSource, Summary

# ---------------------------------------------------------------------------
# The criterion (RNF-05)
# ---------------------------------------------------------------------------

# The four thresholds are a first proposal, to be checked against real reports before 0.1 (design,
# Risk 1). They live here and nowhere else: the text is built from these names, never from retyped
# numbers, and a test fails if the two disagree.

#: Rule 1, in days: the reports must span at least this many.
MIN_DAYS_SPANNED = 28
#: Rule 2, in percent of the days spanned: at least this share must have a report.
MIN_COVERAGE_PERCENT = 80
#: Rule 3, in messages: at least this many must have been seen.
MIN_MESSAGES = 1000
#: Rule 5, in tenths of a percent of all messages: unrecognized failures may be at most this much
#: (5 is 0.5%). Per mille, not percent, so the comparison stays in integers (ADR-4).
MAX_UNRECOGNIZED_PER_MILLE = 5

# ---------------------------------------------------------------------------
# Vocabulary and model
# ---------------------------------------------------------------------------


class Answer(StrEnum):
    """
    What the rules add up to.

    Attributes:
        READY (str): Every rule passes.
        TOO_EARLY (str): Nothing is wrong yet, but a data rule fails: not enough evidence.
        NOT_READY (str): A problem rule fails: something is wrong already.
    """

    READY = "ready"
    TOO_EARLY = "too_early"
    NOT_READY = "not_ready"


class RuleKind(StrEnum):
    """
    What a rule asks about.

    Attributes:
        DATA (str): Is there enough evidence to answer at all.
        PROBLEM (str): Is there something wrong already.
    """

    DATA = "data"
    PROBLEM = "problem"


class RuleId(IntEnum):
    """
    The stable ids of the rules (RF-02); the position of a rule in a verdict is its id minus one.

    Attributes:
        PERIOD (int): The reports span enough days.
        COVERAGE (int): Enough of those days have a report.
        VOLUME (int): Enough messages were seen.
        RECOGNIZED_FAILURES (int): No message fails under a recognized sender.
        UNRECOGNIZED_FAILURES (int): Few messages fail under the other sources.
    """

    PERIOD = 1
    COVERAGE = 2
    VOLUME = 3
    RECOGNIZED_FAILURES = 4
    UNRECOGNIZED_FAILURES = 5


class NoteKind(StrEnum):
    """
    The things worth saying that do not change the answer (RF-04), in the order they are listed.

    Attributes:
        FRAGILE (str): Some traffic passes by one mechanism only. Numbers: fragile messages, those
            of them that pass by SPF only, all messages.
        PARTIAL_POLICY (str): The policy applies to part of the mail. Numbers: ``pct``.
        POLICY_CHANGED (str): The policy changed during the period. Texts: the earlier ``p`` values,
            oldest first.
        SUBDOMAIN_POLICY (str): ``sp`` or ``np`` differs from ``p``. Texts: ``sp`` and ``np``
            (empty when absent).
        CURRENTLY_QUARANTINE (str): The policy is ``quarantine`` now.
    """

    FRAGILE = "fragile"
    PARTIAL_POLICY = "partial_policy"
    POLICY_CHANGED = "policy_changed"
    SUBDOMAIN_POLICY = "subdomain_policy"
    CURRENTLY_QUARANTINE = "currently_quarantine"


@dataclass(frozen=True, slots=True)
class Rule:
    """
    One rule, measured.

    Attributes:
        id (RuleId): The stable id.
        kind (RuleKind): ``DATA`` or ``PROBLEM``.
        measured (int): The value found: days, days with a report, messages or failing messages.
        whole (int): The denominator of a share (days spanned for rule 2, all messages for rule 5),
            0 when the rule is not a share.
        needed (int): The threshold, in the unit of the rule: days, percent of the days, messages,
            messages (0), or tenths of a percent of all messages.
        at_least (bool): True when the rule passes at ``measured >= needed``, False at ``<=``.
        passed (bool): Whether the rule passes.
        missing (int): How much a failed data rule lacks, in days (rules 1 and 2, the second
            rounded up) or messages (rule 3); 0 otherwise.
    """

    id: RuleId
    kind: RuleKind
    measured: int
    whole: int
    needed: int
    at_least: bool
    passed: bool
    missing: int


@dataclass(frozen=True, slots=True)
class Note:
    """
    One thing worth saying about the verdict.

    Attributes:
        kind (NoteKind): Which note it is.
        numbers (tuple[int, ...]): The figures the text needs, as documented on the kind. Default:
            none.
        texts (tuple[str, ...]): The words the text needs, as documented on the kind. Default: none.
    """

    kind: NoteKind
    numbers: tuple[int, ...] = ()
    texts: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Verdict:
    """
    The answer to "is this domain ready for ``p=reject``", with the criterion behind it.

    Attributes:
        domain (str): The domain the verdict is about.
        answer (Answer): What the rules add up to.
        enforcing (str): The latest published ``p``, lower case and trimmed; empty without reports.
        rules (tuple[Rule, ...]): Always the five, in id order.
        deciding (RuleId | None): The first failed rule of the kind that decided the answer;
            ``None`` exactly when the answer is ``READY``.
        recognized_failing (tuple[FailingSource, ...]): Every failing source of a recognized
            sender, the worst first.
        unrecognized_failing (tuple[FailingSource, ...]): Every other failing source, the worst
            first.
        notes (tuple[Note, ...]): The notes that apply, in the order of ``NoteKind``.
    """

    domain: str
    answer: Answer
    enforcing: str
    rules: tuple[Rule, ...]
    deciding: RuleId | None
    recognized_failing: tuple[FailingSource, ...]
    unrecognized_failing: tuple[FailingSource, ...]
    notes: tuple[Note, ...]


# ---------------------------------------------------------------------------
# Rules, notes and the entry point (RF-01 to RF-05)
# ---------------------------------------------------------------------------


def _rules(
    days: int, with_reports: int, total: int, recognized: int, unrecognized: int
) -> tuple[Rule, ...]:
    """
    Build the five rules from the measures, with integer arithmetic only (ADR-4).

    Args:
        days (int): The days the reports span, 0 without reports.
        with_reports (int): The days with at least one report.
        total (int): All the messages seen.
        recognized (int): The failing messages under recognized senders.
        unrecognized (int): The failing messages under the other sources.

    Returns:
        tuple[Rule, ...]: The five rules, in id order.
    """
    # 1. Rule 2 passes only with some days to measure, so no reports never divides or passes.
    coverage_passed = days > 0 and 100 * with_reports >= MIN_COVERAGE_PERCENT * days
    # 2. The days to add are rounded up: 80% of 28 days is 22.4, so 23 are needed.
    days_needed = -(-MIN_COVERAGE_PERCENT * days // 100)
    return (
        Rule(
            RuleId.PERIOD,
            RuleKind.DATA,
            measured=days,
            whole=0,
            needed=MIN_DAYS_SPANNED,
            at_least=True,
            passed=days >= MIN_DAYS_SPANNED,
            missing=max(0, MIN_DAYS_SPANNED - days),
        ),
        Rule(
            RuleId.COVERAGE,
            RuleKind.DATA,
            measured=with_reports,
            whole=days,
            needed=MIN_COVERAGE_PERCENT,
            at_least=True,
            passed=coverage_passed,
            missing=max(0, days_needed - with_reports),
        ),
        Rule(
            RuleId.VOLUME,
            RuleKind.DATA,
            measured=total,
            whole=0,
            needed=MIN_MESSAGES,
            at_least=True,
            passed=total >= MIN_MESSAGES,
            missing=max(0, MIN_MESSAGES - total),
        ),
        Rule(
            RuleId.RECOGNIZED_FAILURES,
            RuleKind.PROBLEM,
            measured=recognized,
            whole=0,
            needed=0,
            at_least=False,
            passed=recognized == 0,
            missing=0,
        ),
        Rule(
            RuleId.UNRECOGNIZED_FAILURES,
            RuleKind.PROBLEM,
            measured=unrecognized,
            whole=total,
            needed=MAX_UNRECOGNIZED_PER_MILLE,
            at_least=False,
            passed=1000 * unrecognized <= MAX_UNRECOGNIZED_PER_MILLE * total,
            missing=0,
        ),
    )


def _notes(summary: Summary, enforcing: str) -> tuple[Note, ...]:
    """
    Collect the notes that apply, in the order of ``NoteKind`` (RF-04).

    Args:
        summary (Summary): The summary.
        enforcing (str): The latest ``p``, normalized.

    Returns:
        tuple[Note, ...]: The notes; none changes the answer.
    """
    notes: list[Note] = []
    totals = summary.totals
    if totals.fragile > 0:
        notes.append(
            Note(NoteKind.FRAGILE, numbers=(totals.fragile, totals.spf_only, totals.total))
        )
    policy = summary.policy
    if policy is not None and policy.pct < 100:
        notes.append(Note(NoteKind.PARTIAL_POLICY, numbers=(policy.pct,)))
    if summary.earlier_p:
        notes.append(Note(NoteKind.POLICY_CHANGED, texts=summary.earlier_p))
    if policy is not None:
        sp = policy.sp.strip().lower()
        np = policy.np.strip().lower()
        if (sp and sp != enforcing) or (np and np != enforcing):
            notes.append(Note(NoteKind.SUBDOMAIN_POLICY, texts=(sp, np)))
    if enforcing == "quarantine":
        notes.append(Note(NoteKind.CURRENTLY_QUARANTINE))
    return tuple(notes)


def judge(summary: Summary) -> Verdict:
    """
    Say whether the domain is ready for ``p=reject``, and why.

    There is no loop over messages: the figures are the ones ``summarize`` already computed. A
    failed problem rule decides the answer even when a data rule also fails (ADR-2): a recognized
    service that fails is a fact that more days of reports will not change. The same ``Summary``
    always gives an equal ``Verdict``.

    Args:
        summary (Summary): What the reports say, from ``summarize``.

    Returns:
        Verdict: The five rules, the answer, the failing sources split by whether the sender is
            recognized, and the notes.
    """
    period = summary.period
    days = period.days_spanned if period else 0
    with_reports = period.days_with_reports if period else 0

    # 1. A recognized row's failing messages are exactly the failing messages of its sources (004
    #    RF-04), so splitting the failing sources by outcome adds up to ``totals.failing``.
    recognized_failing = tuple(s for s in summary.failing if s.outcome is Outcome.KNOWN)
    unrecognized_failing = tuple(s for s in summary.failing if s.outcome is not Outcome.KNOWN)
    recognized = sum(source.messages for source in recognized_failing)
    unrecognized = summary.totals.failing - recognized

    rules = _rules(days, with_reports, summary.totals.total, recognized, unrecognized)

    # 2. A failed problem rule beats a failed data rule; ``deciding`` is the first of that kind.
    answer = Answer.READY
    deciding: RuleId | None = None
    for kind, outcome in ((RuleKind.PROBLEM, Answer.NOT_READY), (RuleKind.DATA, Answer.TOO_EARLY)):
        failed = [r for r in rules if r.kind is kind and not r.passed]
        if failed:
            answer, deciding = outcome, failed[0].id
            break

    enforcing = summary.policy.p.strip().lower() if summary.policy else ""
    return Verdict(
        domain=summary.domain,
        answer=answer,
        enforcing=enforcing,
        rules=rules,
        deciding=deciding,
        recognized_failing=recognized_failing,
        unrecognized_failing=unrecognized_failing,
        notes=_notes(summary, enforcing),
    )
