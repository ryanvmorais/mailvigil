---
feature: Reject verdict — "is this domain ready for p=reject?", with the criterion stated
status: done
date: 2026-10-28
related:
  - 005-reject-verdict/requirements.md
  - 004-summary/design.md
origin: conception
---

# 005 — Reject verdict — design

## Overview

One new module for the rules, one for the text, and a second command in `cli.py`:

```text
paths ──ingest──▶ IngestionResult ─┐
file/--domain ──resolve──▶ Config ─┴─summarize──▶ Summary ──judge──▶ Verdict ──render_verdict──▶ text
(004, RF-08)                          (004)                  (RF-01..05)          (RF-03, RF-06)
```

- **judge** is a pure function from a `Summary` to a frozen `Verdict`: five rules, each with its
  measured value, its threshold and its result, the answer derived from them, the sources behind a
  failed problem rule, and the notes. It reads the figures 004 already computed and counts nothing
  of its own beyond splitting the failing messages into recognized and unrecognized.
- **render_verdict** turns a `Verdict` into text: the title, the reason, the rules table, the next
  step and the closing caveat. All the verdict's English text lives in `render_verdict.py`, so spec
  `006` replaces text modules, not logic (RNF-03).
- **cli.py** gets the `verdict` subcommand. It shares everything before the `Summary` with `summary`
  (resolve the configuration, ingest, refuse when nothing was kept), then judges, prints and maps
  the answer to an exit code.

Two additions after testing the command end to end (issue #28; RF-08 and RF-09): the verdict text
no longer prints a share that reads as a pass beside a `FAIL`, and the verdict carries and prints
what was left out of the numbers. Both are in `verdict.py`, `render_verdict.py` and one new public
helper of `render.py`; the rules and the thresholds do not change.

`summarize`, `Summary` and `render_summary` do not change. `judge` does no I/O and never raises on
data it is given (RNF-02).

## Module layout

```text
src/mailvigil/
  verdict.py          # Answer, RuleKind, RuleId, Rule, NoteKind, Note, Verdict, the threshold
                      # constants, judge                                      (RF-01..05, RNF-05)
  render_verdict.py   # render_verdict and the English text of the verdict   (RF-03, RF-04, RF-05)
  render.py           # + the helpers the verdict text reuses become public: fit, address, count_noun
                      # + share_tenths, the integer under format_share, public for RF-08
  cli.py              # + the `verdict` subcommand, _load shared with `summary`, exit codes 3 and 4
tests/
  test_verdict.py         # RF-01..05, RF-07, RNF-02, RNF-04, RNF-05
  test_render_verdict.py  # RF-03, RF-04, RF-05, RNF-05
  test_cli_verdict.py     # RF-06, through main(argv) and capsys
  test_render.py          # + the renamed helpers (no behavior change)
  test_cli_summary.py     # unchanged: `summary` is untouched (RF-06)
```

The dependency points one way: `cli → render_verdict → verdict → summary`, and
`render_verdict → render` for the helpers. `verdict.py` imports `summary` and `senders` (for
`Outcome`) and never any text module, so a later `--json` reads a `Verdict` without rendering.

## Data model

All types are `@dataclass(frozen=True, slots=True)` and every collection is a tuple (RNF-04).

```python
class Answer(StrEnum):
    READY = "ready"
    TOO_EARLY = "too_early"
    NOT_READY = "not_ready"

class RuleKind(StrEnum):
    DATA = "data"          # is there enough evidence to answer at all
    PROBLEM = "problem"    # is there something wrong already

class RuleId(IntEnum):     # the stable ids of RF-02
    PERIOD = 1
    COVERAGE = 2
    VOLUME = 3
    RECOGNIZED_FAILURES = 4
    UNRECOGNIZED_FAILURES = 5

class Rule:
    id: RuleId
    kind: RuleKind
    measured: int          # days, days with reports, messages, failing messages
    whole: int             # the denominator of a share, 0 when the rule is not a share
    needed: int            # the threshold, in the unit of the rule (see below)
    at_least: bool         # True: pass when measured >= needed; False: when <= needed
    passed: bool
    missing: int           # how much a failed data rule lacks (days, messages), else 0

class NoteKind(StrEnum):
    FRAGILE = "fragile"                    # numbers: fragile, spf_only, total messages
    PARTIAL_POLICY = "partial_policy"      # numbers: pct
    POLICY_CHANGED = "policy_changed"      # texts: the earlier p values, oldest first
    SUBDOMAIN_POLICY = "subdomain_policy"  # texts: sp, np ("" when absent)
    CURRENTLY_QUARANTINE = "currently_quarantine"
    SILENT_REPORTER = "silent_reporter"
    STALE = "stale"

class Note:
    kind: NoteKind
    numbers: tuple[int, ...] = ()
    texts: tuple[str, ...] = ()

class LeftOut:                             # RF-09: what the Summary did not count
    skipped: int = 0                       # files refused (unsafe, too large, malformed, unreadable)
    duplicates: int = 0                    # reports dropped as already seen
    other_domain: int = 0                  # reports of another domain

class Verdict:
    domain: str
    answer: Answer
    enforcing: str                         # latest p, lower case; "" without reports
    rules: tuple[Rule, ...]                # always the five, in id order
    deciding: RuleId | None                # the rule the reason and the next step are about
    recognized_failing: tuple[FailingSource, ...]    # all of them, worst first (from 004)
    unrecognized_failing: tuple[FailingSource, ...]  # all of them, worst first
    notes: tuple[Note, ...]                # in the order of NoteKind
    left_out: LeftOut = LeftOut()          # RF-09; the default keeps a hand-built Verdict valid
```

The units of `needed` are fixed per rule and documented on the constants: days (rule 1), percent of
days (rule 2), messages (rule 3), messages (rule 4, zero), tenths of a percent of all messages
(rule 5, `5`). `Verdict` has no label, phrase or percentage string (RNF-03). `deciding` is `None`
exactly when the answer is `ready`.

## Components

### verdict.py — the constants (RNF-05)

```python
MIN_DAYS_SPANNED = 28            # rule 1
MIN_COVERAGE_PERCENT = 80        # rule 2
MIN_MESSAGES = 1000              # rule 3
MAX_UNRECOGNIZED_PER_MILLE = 5   # rule 5: 0.5% of all messages
```

`render_verdict.py` builds the "needed" column and its explanation from these same names, never from
retyped numbers, and a test fails if the rendered column and the constants disagree (RNF-05).

### verdict.py — `judge` (RF-01 to RF-05)

`judge(summary: Summary) -> Verdict`. No loop over messages: the figures are in the `Summary`.

1. **Measures.** `period = summary.period`; `days = period.days_spanned if period else 0`;
   `with_reports = period.days_with_reports if period else 0`; `total = summary.totals.total`;
   `recognized = sum of counts.failing over the senders whose outcome is KNOWN`;
   `unrecognized = summary.totals.failing - recognized`. A `KNOWN` row's failing messages are exactly
   the failing messages of recognized senders (004 RF-04, the "signature passed but not aligned"
   case included), so the two figures add up to `totals.failing` by construction.
2. **Rules**, built in id order, all integer arithmetic (ADR-4):

   | Id | passed | missing |
   |---|---|---|
   | 1 | `days >= MIN_DAYS_SPANNED` | `max(0, MIN_DAYS_SPANNED - days)` |
   | 2 | `days > 0 and 100 * with_reports >= MIN_COVERAGE_PERCENT * days` | days to add, rounding up: `max(0, ceil(MIN_COVERAGE_PERCENT * days / 100) - with_reports)`, in integers |
   | 3 | `total >= MIN_MESSAGES` | `max(0, MIN_MESSAGES - total)` |
   | 4 | `recognized == 0` | 0 |
   | 5 | `1000 * unrecognized <= MAX_UNRECOGNIZED_PER_MILLE * total` | 0 |

   With no reports `days` is 0, so rules 1 to 3 fail and rule 5 passes on `0 <= 0` (no division,
   RF-01).
3. **Answer (ADR-2).** Any failed problem rule → `NOT_READY`; else any failed data rule →
   `TOO_EARLY`; else `READY`. `deciding` is the first failed rule of the kind that decided; `None`
   for `READY`.
4. **Sources.** From `summary.failing` (already ordered, 004): `recognized_failing` keeps those with
   outcome `KNOWN`, `unrecognized_failing` the rest. They are always filled, whatever the answer, so
   the renderer can mention the second group when the first decided, or when the answer is `ready`
   (ADR-3); the renderer applies the limit of 5 (ADR-1 of 004, applied again).
5. **Notes**, in `NoteKind` order, each only when it applies:
   - `FRAGILE` when `totals.fragile > 0`: `(fragile, spf_only, total)`.
   - `PARTIAL_POLICY` when `policy.pct < 100`.
   - `POLICY_CHANGED` when `summary.earlier_p` is not empty.
   - `SUBDOMAIN_POLICY` when `sp` or `np` is present and differs from `p`.
   - `CURRENTLY_QUARANTINE` when the latest `p` is `quarantine`.
   - `SILENT_REPORTER` when a `reporter_activity` entry has `SILENT_MIN_PERCENT` (10) of the
     messages and its latest `end` is more than `SILENT_AFTER` (7 days) before the period's `end`;
     the first such entry (the largest) is named; `numbers` holds the days, its messages and all.
   - `STALE` when `judge(summary, now)` got a `now` and the latest `end` is more than `STALE_AFTER`
     (14 days) before it; `numbers` holds the whole days.
6. **Left out (RF-09).** `left_out = LeftOut(len(summary.skipped), summary.duplicates,
   summary.other_domain)`: three figures the `Summary` already holds, copied, never recomputed. They
   take no part in the rules or the answer.
7. **Enforcing.** `enforcing = policy.p.strip().lower()` (`""` without reports). Comparisons use this
   normalized value; `?` (a report that does not say) is neither `reject` nor `quarantine`.

`judge` neither sorts nor filters beyond step 4, so the same `Summary` gives the same `Verdict`
(RNF-02), and the order of the reports has already been neutralized by `summarize`.

### render_verdict.py — text (RF-03, RF-04, RF-05)

`render_verdict(verdict: Verdict) -> str`, no trailing newline, the layout rules of 004 RF-09 (80
columns, ASCII, no color or control code). Sections, one blank line apart:

1. **Title.** `MailVigil verdict for DOMAIN: READY for p=reject`, `NOT READY for p=reject` or `TOO
   EARLY to say`. When `enforcing == "reject"` the title is `already at p=reject: NO PROBLEM SEEN`,
   `... BLOCKING REAL MAIL` or `... TOO EARLY to say` (RF-05). The words "safe" and "attack" are not
   used.
2. **Why.** By answer:
   - `NOT_READY`, `deciding` is rule 4: `Why: a recognized sender fails DMARC.` and one line per
     `recognized_failing` source: the service name, the failing messages and the source IP, with
     the override reason types next to it (RF-03). Limit 10 with a remainder line, as 004.
   - `NOT_READY`, `deciding` is rule 5: `Why: failures from unrecognized sources are N% of the
     messages.` and the first 5 `unrecognized_failing` sources, then `... and N other sources: M
     failing messages`. Each source is labeled as 004 labels it (`unrecognized`, `foreign domain
     (selector s)`, `failing signature (selector s)`).
   - `TOO_EARLY`: `Why: not enough reports to tell yet.` and one line per failed data rule with
     what is missing (`need 1 more day`, `need 120 more messages`). With no reports at all, the one
     line is `no report was kept for this domain`.
   - `READY`: `Why: every rule passes.` and, when `unrecognized_failing` is not empty, the line
     `Still failing from unrecognized sources, under the limit:` with the first 5 of them (ADR-3).
3. **Rules table.** Columns `rule`, `measured`, `needed`, `result`, with the id and the name. A share
   is printed with `format_share` and always beside its count (`27 of 28`, `0.3%`; 004 RF-06). The
   result is `pass`, `FAIL` for a failed problem rule and `fail (too early)` for a failed data rule.
   A failed rule whose share would print equal to its limit prints it beyond the limit (RF-08,
   ADR-8): `>0.5%` for rule 5, `<80%` for rule 2, here and in the reason. The decision is taken from
   `Rule.passed` and `share_tenths`, both integers; the counts stay beside it.
4. **Notes** (RF-04), one sentence each, only those present.
5. **Next step.** One sentence chosen by `deciding`: rule 4 → make the service sign with the domain or
   add its servers to SPF, then collect another period; rule 5 → look at the sources above, add the
   selectors of the ones that are yours to `[senders]`; rules 1 to 3 → collect reports until the
   rules pass. Not printed for `READY`.
6. **Left out** (RF-09), only when `left_out` has a figure above zero: one sentence, wrapped at 80
   columns, for example `Left out of this verdict: 2 files skipped, 1 duplicate, 3 reports of
   other domains. mailvigil summary shows why.` The parts at zero are omitted; no file name is
   printed. Placed between the next step and the caveat.
7. **Caveat.** Always, in one fixed sentence: the verdict reads only the reports given; mail that no
   receiver reports on, and senders quiet in this period, are not covered.

### cli.py — the command (RF-06)

```text
mailvigil verdict PATH [PATH ...] [--config FILE] [--domain DOMAIN]
```

`summary` and `verdict` take the same three arguments, so `build_parser()` defines them once in a
parent parser (`add_help=False`, passed to both with `parents=[...]`). `_run_summary` is split: a new
`_load(args) -> tuple[Config, str | None, IngestionResult] | None` does resolve → ingest → refuse
when no report was kept, writing the standard-error line itself and returning `None` on refusal; each
command then continues from its result. The refusals, their text and the code `1` are exactly 004's
(RF-10), because they are the same code.

`_run_verdict(args)`: `_load`; `verdict = judge(summarize(result, config))`; write
`render_verdict(verdict)` to standard output; return the code of the answer:

| Answer | Code | Constant |
|---|---|---|
| `READY` | 0 | `EXIT_OK` |
| `TOO_EARLY` | 3 | `EXIT_TOO_EARLY` |
| `NOT_READY` | 4 | `EXIT_NOT_READY` |

`1` (refused) and `2` (usage) are unchanged. All four stay documented as provisional until `006`
(Resolved decision 4). `main` dispatches on `args.command`; `summary` behaves as before.

### render.py — helpers made public

`share_tenths(part, whole) -> int` is added (RF-08): the tenths of a percent, round half up, that
`format_share` already computes inside; `format_share` calls it, with no change of output, so the
004 suite passes untouched. `render_verdict` uses it to tell whether a failed share would print
equal to its limit.

`_fit`, `_address` and `_count` become `fit`, `address` and `count_noun`, because a second module now
uses them (ADR-5). The change is a rename with its call sites and `test_render.py`; no behavior
changes, and the 004 suite must pass untouched apart from those names.

## Interfaces

| Contract | Shape |
|---|---|
| `mailvigil verdict PATH... [--config FILE] [--domain DOMAIN]` | the command; verdict on standard output, causes on standard error |
| exit codes | `0` ready; `3` too early; `4` not ready; `1` it could not be made; `2` usage error. Provisional until `006` |
| `mailvigil.verdict.judge(summary)` | `Summary -> Verdict` |
| `mailvigil.verdict.Verdict` and its parts | the frozen dataclasses above; the input of `006`'s JSON |
| thresholds | `MIN_DAYS_SPANNED`, `MIN_COVERAGE_PERCENT`, `MIN_MESSAGES`, `MAX_UNRECOGNIZED_PER_MILLE` |
| `mailvigil.render_verdict.render_verdict(verdict)` | `Verdict -> str` |
| `mailvigil.verdict.LeftOut` | `skipped`, `duplicates`, `other_domain`: the counts the verdict printed under RF-09 |
| `mailvigil.render.share_tenths(part, whole)` | `int`; tenths of a percent, the integer behind `format_share` |

Nothing here is a public contract before `0.1`. The rule ids, the threshold values and the exit
codes become one at the first version.

## ADRs

### ADR-1 — The verdict is a short list of named rules, not a score

**Decision.** The answer is derived from five rules with a fixed id, a measured value, a threshold
and a pass or fail. There is no weighting and no confidence number.
**Alternatives.** A weighted score with a cutoff; a single "ready" boolean with a free-text reason;
copying a checklist from a vendor guide.
**Why.** The product promise is an answer with a reason (specs README). A score cannot say which
rule produced it, and two near-equal scores would look the same to the owner. Five rules fit one
screen, can each be disputed on its own, and can each be unit-tested at the boundary.
**Trade-off.** Five thresholds are five arguments; they are constants in one place, and the
maintainer will check them against real reports before `0.1` (Risk 1). (RF-01, RF-02)

### ADR-2 — `not ready` beats `too early`

**Decision.** A failed problem rule decides the answer even when a data rule also fails.
**Alternatives.** `too early` first (no answer without enough data); report both as a pair.
**Why.** A recognized service that fails is already a fact: more days of reports will not make it
pass, and calling it "too early" would delay a fix. The opposite order would also let a short window
hide the single most useful finding. The data rules still appear in the table, so the short window
is visible.
**Trade-off.** A `not ready` on three days of data rests on little evidence; the table shows the
three days beside it. (RF-01)

### ADR-3 — Rule 5 is a share of the total, with no per-source limit

**Decision.** The unrecognized failures are compared as one sum against 0.5% of all messages. A
`ready` verdict still lists the unrecognized failing sources, under the limit.
**Alternatives.** Also fail when any single unrecognized source exceeds 0.1%; a limit per source
only; zero tolerance.
**Why.** The summary cannot tell a forgotten service from a spoofer (004), so the rule must not
claim to. A second threshold would be a sixth rule with no evidence for its number, and one large
source is named in the reason anyway (the first 5 by messages). Zero tolerance would make `ready`
unreachable for a domain that is spoofed daily, which is the case `reject` exists for.
**Trade-off.** A forgotten service that sends 0.4% of the mail passes rule 5 and would be blocked
under `reject`. Listing the sources in a `ready` verdict is the mitigation: the owner sees them
before deciding, and the verdict stays what was declared. This listing is an addition of the design
to RF-03, which only asks for the notes under `ready`. (RF-02, RF-03, Resolved decision 7)

### ADR-4 — Thresholds are compared with integers

**Decision.** Rule 2 compares `100 * with_reports >= 80 * days`, rule 5 compares `1000 *
unrecognized <= 5 * total`, and the "missing days" round up with integer arithmetic.
**Alternatives.** `with_reports / days >= 0.8`.
**Why.** Floats make a boundary depend on representation (`0.8 * 15` is not exactly `12`), and the
spec requires each boundary and its neighbor to be tested. The same argument as 004's ADR-5.
**Trade-off.** The thresholds are stored as percent and per mille, a unit more than the prose says.
(RF-02, RNF-02)

### ADR-5 — The verdict text is its own module, and the shared helpers become public

**Decision.** `render_verdict.py` holds the verdict's text; `render.py` exposes `fit`, `address` and
`count_noun`, and the verdict module imports them.
**Alternatives.** Add the verdict text to `render.py`; duplicate the helpers; import the
underscored names.
**Why.** `render.py` is about 540 lines for one idea; doubling it mixes two outputs. Duplicating
`fit` would give the "never more than 80 columns, never raw text" rule two definitions, and the
point of `fit` is that it has one. Importing private names across modules hides a real dependency.
**Trade-off.** Spec `006` replaces two text modules instead of one. They share the helpers, so the
second one is small. (RNF-03)

### ADR-6 — Distinct exit codes for the three answers

**Decision.** `verdict` returns `0`, `3` and `4`, and a shared `_load` keeps `1` and `2` the same
as `summary`.
**Alternatives.** `0` for every printed verdict, as `summary` does; `1` for `not ready`.
**Why.** A script (a cron job, a CI check) must tell "wait" from "no" without parsing text. `1` is
taken by "could not be made", and reusing it for a verdict would blur a broken run with a
legitimate answer. `3` and `4` leave `1` and `2` meaning what they meant.
**Trade-off.** The verdict command does not follow `summary`'s "0 means an answer was printed";
that is deliberate, because here the answer is the point. Provisional until `006`. (RF-06)

### ADR-7 — A policy that already enforces changes the words, not the rules

**Decision.** With `p=reject` the thresholds and the five rules are the same; only the title and
the verdict words change (RF-05).
**Alternatives.** A separate rule set for domains that already enforce; refusing to judge them.
**Why.** The criterion stays one thing the owner can learn. Under `reject` the receiver still
reports the evaluated results, so recognized failures are mail being blocked now, which is the
sharper form of the same finding.
**Trade-off.** The data rules read oddly for a domain that has enforced for a year and has a short
batch of reports; the table shows why, and the title already says `reject` is on. (RF-05)

### ADR-8 — A failed share that prints equal to its limit is printed beyond it

**Decision.** For rules 2 and 5, when the rule fails and `share_tenths` equals the limit in tenths
(5 for rule 5, 800 for rule 2), the share prints as `>0.5%` or `<80%`. Otherwise it prints as
before.
**Alternatives.** Two decimals when near the limit; truncating instead of rounding half up; printing
the exact fraction.
**Why.** No fixed number of decimals works: 151 of 30000 is `0.50%`, and 100001 of 20000000 is
`0.500005%`, so a failure just over the limit can always print as the limit. Truncating would make
the passing case (exactly 0.5%) and a failing one (0.5001%) print alike. The comparison symbol says
the one thing that matters, "over", and the counts beside it carry the rest. The test uses
integers, not the text, so the printed form cannot drift from the rule.
**Trade-off.** A share near the limit is printed in a form `format_share` never produces; the
verdict text is the only place that has it. (RF-08)

### ADR-9 — The verdict carries what was left out, as counts, and prints one line

**Decision.** `Verdict.left_out` holds the skipped files, duplicates and reports of another domain,
copied from the `Summary`; `render_verdict` prints one sentence when any is above zero.
**Alternatives.** Print the whole "Left out of these numbers" section of `summary`; print only when
a file was skipped; leave it to `summary`; make a skipped file lower the answer.
**Why.** The answer depends on which reports were read, so the reader must see that some were not.
The full section, with file names, belongs to `summary`, where the reasons are; a verdict that
repeated it would grow to hold paths. Counting duplicates and other domains too follows the
README's rule that a number never silently drops out. A skipped file is not a failing message, so
changing the answer for it would invent a rule with no evidence behind it. Carrying counts as data
(not a string) lets `006` print them in `--json`.
**Trade-off.** A `ready` can still be printed with skipped files; the line is a prompt to look, not a
block. (RF-09)

## Impact on existing code

- **New files:** `src/mailvigil/verdict.py`, `render_verdict.py` and three test files.
- **Changed:** `cli.py` (the `verdict` subcommand, a parent parser, `_load` extracted from
  `_run_summary`, two exit codes); `render.py` (three renames, then `share_tenths`); and for
  RF-08 and RF-09 `verdict.py` (`LeftOut`, `Verdict.left_out`) and `render_verdict.py`.
- **Unchanged on purpose:** `summary.py`, `summarize`, `render_summary`, the output and exit codes
  of `mailvigil summary`, `pyproject.toml` (`dependencies` stays empty).
- **Docs:** the README (status rows, Quick start gains `mailvigil verdict` with an invented
  example, the exit codes stay "provisional"), `docs/stack.md` (`IntEnum`, integer comparison of
  thresholds, `argparse` parent parsers), `CLAUDE.md` (the two modules and the command in the
  architecture block and the status paragraph). `/atualizar-docs` at the end. The `specs/README.md`
  row moves to `in progress`, then `done`.

## Risks

1. **The thresholds are a first proposal.** Before `0.1` they are checked against the maintainer's
   own reports (never committed): does 28 days with 80% coverage match how reporters actually
   behave, and does 0.5% fit a real domain. If not, the change is four constants and their tests.
   The maintainer's own `reject` date (23/11) is a natural test.
2. **Rule 5 can pass while a forgotten service sits under 0.5%.** A `ready` verdict lists the
   unrecognized failing sources, so the owner sees them before deciding (ADR-3).
3. **`ready` can be over-trusted.** It is a statement about the reports given, not about the
   domain. The fixed closing sentence is printed with every verdict, and the wording never says
   "safe".
4. **Reporters that do not report.** Some receivers send nothing, so quiet senders can hide.
   Rules 1 and 2 reduce the risk but cannot remove it; the closing sentence says it.
5. **Forwarded mail makes `not ready` noisy** (Resolved decision 6). The reason types are shown next
   to each source so the owner can see that a failure is forwarding, and decide.
6. **The command and the codes are not final.** `006` fixes the contract. `verdict` is three calls
   and a table, so a rename costs a few lines and a test update.

## Test strategy

Following [specs/README.md](../README.md#how-a-spec-is-tested): `judge` is called with built
`Summary` values (a small builder in the test, with defaults, so each test states only what it
changes); the CLI through `main(argv)` and `capsys`, with synthetic files in `tmp_path`. Domains,
services and addresses are invented (RNF-06).

| Requirement | Tests |
|---|---|
| RF-01 | clean table with a short window is `too early`; a recognized failure with a short window is `not ready`; every rule passing is `ready`; no reports is `too early` with rules 1 to 3 failed and no division by zero; reports with zero messages is `too early` |
| RF-02 | each rule at the threshold and the value beside it (27/28 days, 22/23 of 28 days with a report, 999/1000 messages, 1 recognized failing message, unrecognized at exactly 0.5% and just over); a rule carries id, kind, measured, whole, needed and result as fields; `deciding` is the first failed rule of the deciding kind and `None` for `ready` |
| RF-03 | the recognized and the unrecognized failing sources are split by outcome and keep 004's order; the reason names the recognized sources, each IP and the override types; more than 5 unrecognized sources print 5 and a remainder with its failing count; `too early` names each failed data rule with what is missing; `ready` never prints "safe" and lists unrecognized failing sources when there are any; the next step matches `deciding` |
| RF-04 | the fragile note carries share and SPF-only; `pct` below 100, a changed `p`, an `sp` or `np` that differs, and `quarantine` each give their note and no other; none of them changes the answer |
| RF-05 | with `p=reject` the same inputs give the same answer and the reject wording; with `p=quarantine` the note; with `p=none` and with `?` neither |
| RF-06 | `verdict` returns 0, 3 and 4 for the three answers; a refused configuration, a conflicting domain and no kept report give the lines and code `1` of `summary`; no path is a usage error `2`; `summary` output and codes are byte-for-byte as before; `--help` lists both commands |
| RF-07 | the list of RF-07 is the list of the rows above |
| RF-08 | 151 of 30000 prints `>0.5%` in the table and in the reason, 150 of 30000 still prints `0.5%`; a rule 2 failure whose share rounds to 80.0% prints `<80%`; a share clearly over or under its limit prints as before; the counts stay; the choice follows `Rule.passed`, not the text |
| RF-09 | `judge` copies skipped, duplicates and other-domain counts from the `Summary` and the answer does not change; the line appears with each count alone and together, omits the parts at zero, names no file, stays at 80 columns and sits before the caveat; with nothing left out the output is byte-for-byte what it was; a `ready` with skipped files stays `ready`; through `main(argv)` a real skipped, duplicate and other-domain file reach the line |
| RNF-02 | the same `Summary` judged twice, and built from the same reports in two orders, gives equal verdicts |
| RNF-03 | `judge` imports no text module (checked by import); `Verdict` has no `str` field built for display, only names, ids and the sources |
| RNF-04 | `Verdict` and its parts raise `FrozenInstanceError` on assignment and expose only tuples |
| RNF-05 | the rendered "needed" column is built from the four constants, so a test that monkeypatches a constant changes the text |
| 004 | the unchanged 004 suite passes after the renames in `render.py` |

The quality gate (`ruff` → `black --check` → `mypy` → `pytest --cov`) closes each stage of
`tasks.md`, with its real result recorded.
