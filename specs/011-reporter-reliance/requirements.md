---
feature: A note when the answer rests on one reporting organization
status: in progress
date: 2026-11-14
related:
  - 004-summary/requirements.md
  - 005-reject-verdict/requirements.md
  - 006-output-and-exit-codes/requirements.md
  - 008-html-report/requirements.md
  - 010-multiple-domains/requirements.md
origin: conception
---

# 011 — Reporter reliance

## Context and problem

The verdict ([005](../005-reject-verdict/)) adds up every report it is given. Aggregate reports are
not signed, and the name of the reporting organization is whatever the report says it is, so a
file that did not come from a real receiver counts the same as one that did: in the volume, in the
days covered and in the share of failures. The README states this as a limit ("It trusts the
numbers in the reports") and asks the reader to check the reporting organizations.

That check is left to the reader, and the verdict does not help with it. The summary says how many
organizations reported (`reports 12 from 3 reporters`), but neither the summary nor the verdict says
when the answer **depends** on one of them. A `ready` that holds only because of one
organization's reports deserves a second look before the domain moves to `p=reject`, because that
move is the one that rejects real mail when the numbers are wrong. The same is true without any
foul play: a domain whose reports come almost all from one receiver sees the world through that
receiver alone.

The verdict already has one note about reporters: `silent_reporter` ([005](../005-reject-verdict/)
RF-04), for a large reporter that went quiet. This spec adds a second one, built the same way: it
qualifies the answer and never changes it. It needs a spec of its own, not an amendment, because
it reaches the summary's data, the verdict, the text in two languages, `--json`, the HTML page and
the run of several domains at once, and two of those are public contract
([docs/stability.md](../../docs/stability.md)).

## Goals

- **Say when a `ready` rests on one organization:** name it, give its share of the messages and say
  what the answer would be without its reports.
- **No new number to tune:** the note follows from the five rules of 005 as they are, not from a new
  threshold.
- **Nothing else changes:** the answer, the deciding rule, the exit code and every run where the
  note does not apply stay as they are.

## Non-goals

- **Authenticating reports.** Checking the signature of the mail that carried a report needs DNS
  lookups and public-key cryptography, which would break "offline" and "zero runtime dependencies".
  The note tells the reader where to look; it does not tell a real report from a false one.
- **A list of trusted reporters in the configuration.** The organization name is written by whoever
  wrote the report, so a list of names gives an assurance it cannot keep.
- **Changing the answer or the exit code.** A note never does (005 RF-04). A domain with one honest
  receiver is not less ready because of it.
- **A note on `too early` or `not ready`.** Those answers keep the current policy, and the failing
  sources they list are already the place to look (RF-01).
- **A per-reporter breakdown in `--json` or on the page.** Only the note is added; a table of
  reporters would be a new section of the document and of the page.
- **An option to turn the note off.** No note has one.

## Personas

- As a **domain owner about to move to `p=reject`,** I want to know when the green light comes from
  one organization's reports, so that I check that I recognize it before I act.
- As the **owner of a small domain** whose reports come from one or two receivers, I want the note to
  read as a check, not as an alarm, and my answer and exit code to stay the same.
- As a **user with a scheduled job,** I want the exit code untouched and the note in `--json` as one
  more note kind, so that my script can read it or ignore it.
- As a **maintainer,** I want the note computed from the data the summary already holds, without
  reading the reports twice, and decided by the same five rules, so that there is one criterion.

## Functional requirements

### RF-01 — When the note applies

- **Given** a verdict whose answer is `ready`
  **When**, for one reporting organization, the five rules of 005 are applied to every report of the
  run except that organization's
  **Then** if the answer of those rules is not `ready`, the answer rests on that organization and
  the verdict carries the note.
- **Given** several organizations that the answer rests on, each one alone
  **When** the note is built
  **Then** it names one of them: the one with the most messages, and by name on a tie. One line per
  verdict, not one per organization.
- **Given** a verdict whose answer is `ready`, and no organization it rests on
  **When** the verdict is built
  **Then** there is no note, and the output is the same bytes as before this spec.
- **Given** a verdict whose answer is `too early` or `not ready`
  **When** the verdict is built
  **Then** there is no note.

### RF-02 — What the note says

- **Given** the note
  **When** it is built
  **Then** it carries the organization's name as the reports gave it (already cleaned, 002), its
  messages, all the messages of the domain, the number of organizations that reported, and the
  answer and the deciding rule the five rules gave without its reports.
- **Given** the note in text, in English or in Portuguese
  **When** it is printed
  **Then** it names the organization and its share, says what the answer would be without its
  reports, and asks the reader to check that they recognize it, in the words of a check and not of
  a warning. The Portuguese text has its accents on a stream that carries them and is folded to
  ASCII otherwise (006 ADR-9).
- **Given** a run with one reporting organization and a `ready` answer
  **When** the note is printed
  **Then** it says that every report came from that organization, instead of a share of 100%.

### RF-03 — Where the note appears

- **Given** `mailvigil verdict`, in text, with `--json` or with `--html`
  **When** the note applies
  **Then** it is listed with the other notes, in the fixed order of the note kinds, and the page
  shows it in its notes card with no new section and no change to the layout of 008.
- **Given** `mailvigil summary`
  **When** it runs
  **Then** nothing changes: notes belong to the verdict.
- **Given** a run of several domains (010)
  **When** the verdict is built
  **Then** the note is decided for each domain on that domain's reports only, and the worst-answer
  exit code is unchanged.

### RF-04 — The answer and the exit code are untouched

- **Given** any run
  **When** the note applies
  **Then** the answer, the deciding rule, the five rules, the failing sources and the exit code are
  the same as without the note.

## Non-functional requirements

### RNF-01 — A public contract that only grows

- **Given** `--json`
  **When** the note applies
  **Then** it is one more value of the note `kind`, with its numbers and texts documented in
  `docs/json-schema.md`, inside the same `schema_version`. The release is a **minor** one, and
  `docs/json-schema.md` says that a consumer must accept a note kind it does not know, as it ignores
  a key it does not know.
- **Given** the existing tests
  **When** they run unchanged
  **Then** they pass, except those that build a `ready` verdict the new note applies to, which are
  updated in the same stage and named in `tasks.md`.

### RNF-02 — Bounded, and from memory

- **Given** a run with many reporting organizations
  **When** the note is decided
  **Then** no report is read again; the check works on figures the summary keeps per organization,
  and its cost grows with the organizations and the days of the run, both already bounded by the
  ingestion caps (002). The design states the bound.

### RNF-03 — One criterion

- **Given** the check of RF-01
  **When** it applies the rules
  **Then** it uses the thresholds of `verdict.py` and no other number, so a change to a threshold
  changes the note with it.

### RNF-04 — Deterministic, offline, zero dependencies

- **Given** the same files and arguments
  **When** the run is repeated
  **Then** the note and the organization it names are identical; nothing in the run touches the
  network and the wheel declares no dependency.

### RNF-05 — Hostile text stays text

- **Given** an organization name from a report
  **When** it appears in the note
  **Then** it goes through the same cleaning and escaping as in the summary and the
  `silent_reporter` note, in text, JSON and HTML.

### RNF-06 — Synthetic data and the quality gate

- **Given** the tests
  **When** they need reports
  **Then** every report, organization and domain is invented and every address is in a
  documentation range. The gate (`ruff`, `black`, `mypy` strict, `pytest --cov` at 100%) closes
  every stage.

## Open questions

Answered on 2026-11-14: the maintainer approved the requirements with the recommendation of all
four.

1. **What "rests on" means (RF-01).** Recommended: the answer without that organization's reports,
   by the five rules as they are. It needs no new threshold and says something exact ("without it,
   `too early`"). The alternative, a share of the messages above a fixed percentage (a "dominant
   reporter"), is simpler to compute but adds a number to tune, fires for a large reporter the
   answer does not depend on, and misses a small one it does (a few days of coverage, the last
   messages over the volume rule).
2. **A small domain with one or two receivers (RF-02).** Recommended: the note still appears, worded
   as a check. For such a domain the answer does rest on one organization, and that is true and
   worth one line; it changes neither the answer nor the exit code. The alternative, no note when
   there is only one organization, leaves out the case where the whole folder is one organization's
   reports, which is the case the note is for.
3. **Only on `ready` (RF-01).** Recommended: yes. The step the verdict guards is the move to
   `p=reject`; `too early` and `not ready` keep the current policy and already say where to look.
   The alternative, on every answer, adds a line where it changes no decision.
4. **A new value of `kind` is a minor change (RNF-01).** Recommended: yes, stated in
   `docs/json-schema.md` as the rule for consumers. The alternative, a `schema_version` 2, makes every
   consumer change for one line of text.

## Tests

Following [specs/README.md](../README.md#how-a-spec-is-tested):

- **Unit tests, no CLI:** the check of RF-01 on built summaries: one organization, two where the
  answer rests on the larger, two where it rests on the smaller (coverage or volume), several where
  it rests on more than one (the tie by name), none it rests on, and the `too early` and `not ready`
  answers with no note. Each rule of 005 that can turn the answer is the cause in at least one case.
- **Criterion:** a test that changes a threshold of `verdict.py` in the test and sees the note follow
  (RNF-03).
- **Text:** both languages, the share and the one-organization wording, and the ASCII folding of the
  Portuguese text.
- **CLI:** `main(argv)` with `capsys` for `verdict` in text, `--json` and `--html`, with one and with
  several domains, and the exit codes unchanged.
- **Contract:** `test_json_schema_doc.py` extended to the new kind, and the examples of
  `docs/json-schema.md` built by the code.
- **Synthetic only:** RNF-06.
- **Quality gate last:** `ruff` → `black --check` → `mypy` → `pytest --cov`, with its real result
  recorded in `tasks.md`.
