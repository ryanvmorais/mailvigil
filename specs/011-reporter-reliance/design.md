---
feature: A note when the answer rests on one reporting organization
status: in progress
date: 2026-11-14
related:
  - 011-reporter-reliance/requirements.md
  - 004-summary/design.md
  - 005-reject-verdict/design.md
  - 006-output-and-exit-codes/design.md
origin: conception
---

# 011 — Reporter reliance — design

## Overview

The figures go where figures already go, and the judgment where the judgment already is:

```text
IngestionResult ──summarize──▶ Summary ─────────────judge──────────────▶ Verdict
                   (004)        + without_reporter     the five rules, once for the run
                                  (ADR-2, ADR-3)       and once per entry of without_reporter
                                                       (ADR-1) → NoteKind.REPORTER_RELIANCE
```

- **summarize** adds one internal field to the `Summary`: for each reporting organization, the five
  measures the rules read (days spanned, days with a report, messages, recognized and unrecognized
  failing messages) as they would be **without that organization's reports**. It computes them in
  the same pass and one sweep over the periods, never by summarizing again (ADR-2, ADR-3).
- **judge** applies the same five rules to each entry, in the order of `reporter_activity`, only
  when the answer of the run is `ready`. The first entry whose answer is not `ready` becomes the note
  (ADR-1, ADR-4). The answer, the deciding rule and everything else of the verdict are computed as
  today, before the note and without reading it (RF-04).
- **render_verdict**, the two message modules, `render_json` and `render_html` print the note through
  the paths every note already takes: the table of note texts, `note_sentence` and `_note`. No new
  section, no new layout (RF-03).

`summary` prints nothing new; `fetch` is untouched. A run of several domains gets the note per
domain for free, because `summarize` and `judge` already run once per domain (010, ADR-3).

## Module layout

```text
src/mailvigil/
  summary.py          + WithoutReporter, Summary.without_reporter, the per-reporter tallies
                        in the loop, _without_reporter() and the exclusive-time sweep
  verdict.py          + NoteKind.REPORTER_RELIANCE, _answer() (taken out of judge), the
                        check in _notes()
  render_verdict.py   + _reliance() in the table of note texts
  messages/model.py   + reliance_alone in the verdict messages
  messages/en.py      + two sentences
  messages/pt_br.py   + two sentences
  render_json.py      unchanged (_note is generic)
  render_html.py      unchanged (the notes card is generic)
```

## Data model

```python
@dataclass(frozen=True, slots=True)
class WithoutReporter:
    """
    The five measures of the rules as they would be without one organization's reports.

    Attributes:
        name (str): The organization, as the reports gave it (already cleaned).
        messages (int): Its own messages, so the note can give its share.
        days_spanned (int): The days the other reports span; 0 when there are none.
        days_with_reports (int): The days the other reports cover (004, MIN_COVERED_SECONDS).
        total (int): The messages of the other reports.
        recognized_failing (int): Their failing messages under a recognized sender.
        unrecognized_failing (int): Their other failing messages.
    """
```

`Summary.without_reporter: tuple[WithoutReporter, ...] = ()` holds one entry per organization, in
the order of `reporter_activity` (most messages first, then by name). Like `days` and `covered`, it is
internal: no `--json` document carries it (requirements, non-goals).

The note:

```python
class NoteKind(StrEnum):
    ...
    SILENT_REPORTER = "silent_reporter"
    REPORTER_RELIANCE = "reporter_reliance"   # new, kept next to the other reporter note
    STALE = "stale"
```

| Part | Content |
|---|---|
| `numbers` | its messages, all the messages of the domain, the organizations that reported, the id of the rule that decides the answer without it |
| `texts` | its name, the answer without it (`too_early` or `not_ready`) |

## Components

### The per-reporter tallies (summary.py)

The loop of `summarize` already classifies every record (`count > 0`, the identification, failing
when neither DKIM nor SPF passes). It adds three `Counter[str]` keyed by `report.reporter`:
messages, failing messages under `Outcome.KNOWN`, and all failing messages. Per organization it also
keeps the earliest `begin` and the last day touched (`_days_touched`), and the periods of its reports.
The totals of the run minus an organization's tallies give `total`, `recognized_failing` and
`unrecognized_failing` without it.

### The period without an organization

`days_spanned` without an organization runs from the earliest `begin` of the others to the last day
the others touch, as `_period` does for the run. The organizations are sorted once by their earliest
`begin` and once by their last day; for each one, the bound of the others is the first of each list
that is not itself. A zero-length report counts for the period and not for the coverage, as in 004.

### The coverage without an organization (ADR-3)

`_covered` merges the periods of every report and counts a day when the merged periods cover at least
`MIN_COVERED_SECONDS` of it. Without an organization, a day can only lose the time that **only that
organization** covered. One sweep over the start and end of every period, with a count of the
reports each organization has open, finds the stretches of time where exactly one organization has
a report open: its exclusive time. For each organization:

- a whole UTC day inside its exclusive time is covered now and would not be (0 seconds left);
- a day where its exclusive time starts or ends keeps the seconds the merged periods give it today,
  minus that organization's exclusive seconds on that day, and is lost when the rest falls below
  `MIN_COVERED_SECONDS`.

`days_with_reports` without it is today's count minus the days it would lose. `_covered` is split so
that the sweep reads the same per-day seconds that decide today's coverage, and the two cannot
disagree about a day.

### The check (verdict.py)

The loop at the end of `judge` that turns the five rules into an answer moves into
`_answer(rules) -> tuple[Answer, RuleId | None]`, and `judge` calls it as before. `_notes` receives the
answer of the run; when it is `READY`, it walks `summary.without_reporter`, builds `_rules(...)` from
each entry and calls `_answer`. The first entry whose answer is not `READY` gives the note and the
walk stops (RF-01). No threshold is read outside `_rules` (RNF-03).

### The text (render_verdict.py and messages)

`_reliance(note, messages)` picks one of two sentences by the number of organizations:

| | English | Portuguese |
|---|---|---|
| several | `The answer rests on {name} ({share} of the messages): without its reports it would be {words}. Check that you recognize this reporter.` | `A resposta depende de {name} ({share} das mensagens): sem os relatórios dessa organização, seria {words}. Confira se você a reconhece.` |
| one | `Every report came from {name}, so the answer rests on its numbers alone. Check that you recognize this reporter.` | `Todos os relatórios vieram de {name}, então a resposta depende só dos números dessa organização. Confira se você a reconhece.` |

`{words}` is the label the title already uses for that answer: `words`, or `words_enforcing` when
the domain is at `p=reject` already, so the note and the title never name an answer differently.
`{share}` is `format_share`, and `{name}` goes through `fit(name, _NAME_MAX)`, as in the
`silent_reporter` note. The Portuguese sentences are folded to ASCII by the existing folding (006
ADR-9).

## Interfaces

- **Text and HTML:** one more line in the notes, in the order of `NoteKind`. Nothing else moves.
- **`--json`:** one more `kind`, `reporter_reliance`, inside `schema_version` 1:

```json
{
  "kind": "reporter_reliance",
  "numbers": [6300, 7335, 3, 2],
  "texts": ["Example Receiver", "too_early"]
}
```

- **`docs/json-schema.md`:** the `note` table lists the kind with its numbers and texts, and the
  rules of the document say that a consumer must accept a note `kind` it does not know.
- **Exit codes:** unchanged (RF-04).

## Architecture decisions

### ADR-1 — "Rests on" is the answer of the five rules without that organization (RF-01, RNF-03)

**Decision.** An answer rests on an organization when the five rules of 005, applied to the
measures without its reports, do not answer `ready`. The rules are built by `_rules` and turned into
an answer by `_answer`, the same two functions as the verdict of the run.

**Alternatives.** A share of the messages above a fixed percentage (a "dominant reporter").

**Why.** Approved with the requirements (open question 1): no new number to tune, and an exact
statement ("without it, too early") instead of a proxy. A share misses a small organization that
completes the coverage or the volume, and fires for a large one the answer does not depend on.

**Trade-off.** The check needs the five measures per organization, which a share would not
(ADR-2).

### ADR-2 — The measures without each organization come from the summary's own pass (RF-01, RNF-02)

**Decision.** `summarize` computes `without_reporter` from per-organization tallies and one sweep
(ADR-3), in time that grows with the reports and the organizations, not with their product.

**Alternatives.** Summarize again without each organization's reports and judge the result.

**Why.** It would be the simplest code, but its cost is the whole summary once per organization.
The organization name is written by the report, so a folder can hold as many organizations as
reports, and the ingestion caps (002: a million records per run) would allow a run that takes hours.
The tallies add three counters to a loop that already exists.

**Trade-off.** A second way to compute the coverage, which could drift from `_covered`. The tests use
the simple alternative as the oracle: for built sets of reports, every entry of `without_reporter`
must equal the measures of `summarize` run without that organization (Tests).

### ADR-3 — Coverage without an organization is today's coverage minus its exclusive time (RF-01)

**Decision.** The sweep of the components section: a day is lost without an organization only if the
seconds the merged periods cover on it, minus the seconds no other organization covers, fall below
`MIN_COVERED_SECONDS`.

**Alternatives.** Run `_covered` again over the other reports for each organization (ADR-2, the
product cost again); or count per day which organizations sent a report that begins on it, which is
not how 004 counts a covered day and would make the note disagree with rule 2.

**Why.** Removing reports can only remove covered time, and the time it removes is exactly the time
no one else covered. Only the first and the last day of an exclusive stretch are visited; the whole
days between them are counted, not looped over, as `_covered` does (004 RNF-09). The sweep has two
events per report, so the work follows the reports, not the distance between them.

**Trade-off.** The sweep is the most intricate code of the spec. It is tested against the oracle of
ADR-2 and on hand-built edges: periods that touch at midnight, overlaps between two organizations,
a day covered half by each, a zero-length report.

### ADR-4 — One note, for the organization with the most messages (RF-01)

**Decision.** The walk follows `reporter_activity` and stops at the first organization the answer
rests on.

**Alternatives.** One note per organization; or the organization whose removal changes the most
rules.

**Why.** The reader needs one place to start, and the largest is the one whose numbers weigh most in
every rule. The order is already fixed and tested (most messages, then name), so the choice is
deterministic (RNF-04). A run of forged names could otherwise add hundreds of lines.

**Trade-off.** A second organization the answer also rests on is not named. The note says where to
look, and the summary lists the organizations.

### ADR-5 — The note carries its figures, not its sentence (RF-02, RNF-01)

**Decision.** `numbers` and `texts` as in the data model; the JSON kind is `reporter_reliance`,
added in a minor version.

**Alternatives.** A `schema_version` 2 (rejected with the requirements, open question 4); or the
sentence itself in the document.

**Why.** Every note is figures and words a consumer can use without parsing English, and the text is
built from them in either language (006). The rule id lets a script say which rule would fail.

**Trade-off.** A consumer that rejects unknown kinds breaks on the first run with the note. The rule
in `docs/json-schema.md` is stated so that it is the consumer's contract, as it is for keys.

## Impact

- **New:** `WithoutReporter`, `Summary.without_reporter`, the sweep, `NoteKind.REPORTER_RELIANCE`,
  `_answer`, two sentences in two languages. `[project].dependencies` stays empty.
- **Changed:** the loop of `summarize` (three counters), `_covered` split so the sweep reads its
  per-day seconds, `_notes` (the answer as an argument).
- **Unchanged and tested to stay so:** every run whose verdict is not `ready`, or is `ready` without
  resting on one organization: same text, JSON, page and exit code. `summary` output, `fetch`.
- **Changed output, on purpose:** a `ready` run that rests on one organization gains a note line.
  The README demo is such a run (its later period comes from one invented receiver), so
  `docs/demo/verdict.cast` and its picture are rebuilt with the commands in `build_demo.py`; the
  existing tests that build such a run are updated and named in `tasks.md`.
- **Release:** a minor version: a new note kind.
- **Docs:** README and README.pt-BR (the "It trusts the numbers in the reports" limit points to the
  note), `docs/json-schema.md` (the kind and the rule for unknown kinds), `docs/stability.md` (the
  JSON row), CHANGELOG, `specs/README.md` (the roadmap row).
- **CI:** nothing new.

## Risks

- **Noise on small domains.** A domain with one receiver sees the note on every `ready`. Accepted with
  the requirements (open question 2): the sentence is a check, and the answer and the exit code stay.
- **The sweep drifts from `_covered`.** Mitigation: the oracle tests of ADR-2 and the shared per-day
  seconds of the components section.
- **A forged report under a real organization's name.** Out of scope (non-goals): the note points to
  the organization, it does not authenticate it. The README limit stays.
- **Cost on a large run.** Mitigation: ADR-2 and ADR-3 keep the work at a sort and a sweep over the
  reports. A test builds a run of ten thousand reports, each from its own organization, and checks
  one entry per organization; the time of `summarize` on it, before and after, is measured once and
  recorded in `tasks.md`.

## Tests

- **summary.py:** the counters on built reports; `without_reporter` against the oracle (summarize
  without each organization) on a table of report sets: one organization, two that overlap, two that
  alternate days, a day covered half by each, periods that touch at midnight, zero-length reports,
  records with `count` 0, failures under known and unknown senders.
- **verdict.py:** the note for each rule that can turn a `ready` (period, coverage, volume and the
  unrecognized share; rule 4 cannot, and a test says so), the choice by messages and by name, no note
  when nothing rests on one organization, no note on `too_early` and `not_ready`, and the answer,
  rules and exit code equal with and without the note. A threshold patched in the test moves the
  note with it (RNF-03).
- **Text:** both sentences in both languages, with `words` and `words_enforcing`, a long name cut by
  `fit`, and the folded Portuguese.
- **CLI:** `main(argv)` with `capsys` for `verdict` in text, `--json` and `--html`, one domain and
  several, and the exit codes.
- **Contract:** `test_json_schema_doc.py` sees the new kind, and the example of the kind in
  `docs/json-schema.md` is built by the code.
- **Hostile text:** an organization name with markup and control characters reaches the note cleaned
  in text and escaped in HTML (RNF-05).
- **Quality gate last:** `ruff` → `black --check` → `mypy` → `pytest --cov`, with its real result
  recorded in `tasks.md`.
