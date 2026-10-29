---
feature: Output and exit codes — `--json`, the stable exit-code contract and the Portuguese text
status: done
date: 2026-10-28
related:
  - 004-summary/requirements.md
  - 005-reject-verdict/requirements.md
origin: conception
---

# 006 — Output and exit codes

## Context and problem

After [005](../005-reject-verdict/) the two commands answer the product's question, but only to a
person reading English on a terminal. Three things are still open, each one promised to this spec by
004 and 005:

- **A script cannot read the answer.** `mailvigil verdict` prints a table; a cron job, a CI step or
  a dashboard would have to parse text laid out for humans. The data exists already (`Summary` and
  `Verdict` are frozen dataclasses with no text in them), it just has no machine-readable output.
- **The exit codes are provisional.** `0`, `1` and `2` come from 004 and `3` and `4` from 005, and
  both specs say "provisional until 006". Once `1.0.0` is published a script will depend on them, and
  changing a code then is a breaking change.
- **The text is English only.** The maintainer's audience, and the owners of small domains this
  tool is for, are largely Brazilian. The text of both commands lives in `render.py` and
  `render_verdict.py` precisely so a second language does not need a second implementation.

The job of this spec is to **freeze what a script and a reader may rely on** before `1.0.0`, and to
do it without touching the rules: `summarize` and `judge` do not change, only what turns their
results into output.

Two things keep the contract honest:

- **JSON is the data, not a transcript of the text.** It carries numbers, enums and lists, never a
  sentence or a rounded percentage. A consumer that needs a sentence is in the wrong layer; one
  that needs a share divides two integers.
- **A contract that cannot be tested is not a contract.** The shape of the JSON and the table of
  exit codes are asserted by tests that fail on any change, so a breaking change is always a
  deliberate edit of a test and of the documented version, never an accident.

## Goals

- **`--json` on both commands**, printing one JSON document on standard output built from the
  `Summary` or the `Verdict`.
- **A versioned schema** (a `schema_version` field) and a written description of it, so a change is
  visible.
- **The exit codes, fixed and documented**, for `summary` and `verdict`, including what each
  refusal returns.
- **Portuguese text** (Brazil) for both commands, chosen explicitly, with English staying the
  default.
- **No change to the numbers or the answer**: the same reports give the same `Summary`, the same
  `Verdict` and the same exit code in every format and language.

## Non-goals

- New rules, new thresholds or new notes: that is 005. The verdict is the same in any output.
- More commands (`explain`, `export`), a `--quiet` flag, `--output FILE`, or other formats (CSV,
  HTML, Markdown). JSON and the text are the two; others wait for a request.
- Translating anything that is not shown to the reader by MailVigil: report fields (service names,
  addresses, selectors, override reasons as DMARC spells them) stay as they are in the data.
- A third language, or a translation framework (`gettext`, catalog files): two languages in plain
  modules (RNF-01). A third language reopens this.
- Localized number formats (`1.234,5`): digits and the decimal point stay as they are in both
  languages, because the text is laid out in fixed columns (004 RF-09).
- Reading the language from the system by default (open question 2).
- A JSON Schema file validated at runtime. The schema is documented and tested; shipping a
  validator would be a dependency.

## Personas

- As **someone running MailVigil from a script** (cron, CI, a cheap monitor), I want one JSON
  document and an exit code that never changes meaning, so that I can alert on `not ready` without
  parsing text.
- As the **owner of a small Brazilian domain**, I want the answer and the reason in Portuguese, so
  that I can act on it without translating.
- As a **contributor**, I want the schema and the codes in one place each, and a test that breaks
  when either changes, so that I cannot change the contract by accident.

## Functional requirements

### RF-01 — `--json` prints one document

- **Given** `mailvigil summary ... --json` or `mailvigil verdict ... --json`
  **When** the run succeeds
  **Then** standard output holds exactly one JSON document and a newline, nothing else (no
  heading, no log line), and standard error is empty.
- **Given** the same reports and configuration
  **When** the command runs twice, or with the files in another order
  **Then** the two documents are byte-equal: keys in a fixed order, lists in the order the
  `Summary` and `Verdict` already guarantee, no timestamp of the run, no path of the machine other
  than the ones the user typed.
- **Given** a value that came from a report (a service name, a selector, an address, an override
  reason)
  **When** it is written
  **Then** it is already the sanitized text of 002 and the document is valid UTF-8 JSON with
  non-ASCII escaped, so no console encoding can corrupt it.
- **Given** `--json`
  **When** the command is not `summary` or `verdict`
  **Then** `--json` is not accepted (`--version` has no JSON form).

### RF-02 — The document is data, not text

- **Given** the document of either command
  **When** it is read
  **Then** it contains integers, booleans, strings that are identifiers or report values, enums
  spelled as their stable names, and lists; it contains no sentence written for a person, no
  rounded percentage and no column layout.
- **Given** a share (days with a report over days spanned, failing messages over all messages)
  **When** it is needed
  **Then** the document carries the two integers (`part`, `whole`) and the threshold as integers,
  never a computed ratio, so the same integer arithmetic of 005 (RNF-02) is reproducible by the
  consumer.
- **Given** the `summary` document
  **When** it is built
  **Then** it carries everything the text shows, **without the display limits** of the text (004
  Resolved decision 12): every sender row and every failing source, every skipped file with its
  reason, and the totals, so that no information exists only in the text.
- **Given** the `verdict` document
  **When** it is built
  **Then** it carries the answer, whether the policy already enforces, every rule (id, kind, name
  as an identifier, measured, whole, needed, comparison, passed, missing), the deciding rule, all
  the failing sources (recognized and unrecognized, not only the first 5 and 10), the notes as
  kind plus numbers plus texts, and what was left out.
- **Given** a rule or a note in the document
  **When** it is identified
  **Then** it is by a stable identifier (`period_covered`, `days_with_report`, …), never by its
  English or Portuguese name, which the text may translate.

### RF-03 — The schema is versioned and described

- **Given** both documents
  **When** they are built
  **Then** each carries `schema_version` (an integer, `1` for the first release), `command`
  (`"summary"` or `"verdict"`) and `domain`.
- **Given** the schema
  **When** the README and `docs/` are written
  **Then** one page lists every field with its type and meaning, the compatibility promise (a field
  is only added in a version that keeps the number; a field is renamed, removed or changes type
  only with a new `schema_version`) and an example with invented data.
- **Given** the schema
  **When** the test suite runs
  **Then** a test compares the real output for a built `Summary` and a built `Verdict` against the
  documented example, field by field, so the documentation cannot drift from the code, and a
  second test fails on any key that is not in the documented list.
- **Given** a field that holds a value the model may not have (no period, no published policy)
  **When** it is written
  **Then** it is `null`, never missing and never an empty string standing for "none".

### RF-04 — The exit codes are a contract

- **Given** the two commands
  **When** they end
  **Then** the exit code is one of these, and only these:

  | Code | Meaning | Commands |
  |---|---|---|
  | `0` | an answer was printed, and for `verdict` the answer is `ready` | both |
  | `1` | the run was refused: invalid configuration or domain, or no report kept | both |
  | `2` | usage error (argparse) | both |
  | `3` | `verdict` printed `too early` | `verdict` |
  | `4` | `verdict` printed `not ready` | `verdict` |
  | `70` | internal error (a bug): one line on standard error | both |
  | `130` | interrupted with Ctrl+C, no output | both |
  | `141` | the output pipe was closed, no output | both |

- **Given** any verdict word of the enforcing form (005 RF-05: `blocking real mail`,
  `no problem seen`)
  **When** the command ends
  **Then** the code is the one of the answer it reads as (`4` and `0`); the text changes, the code
  does not.
- **Given** `--json` or `--lang`
  **When** the command ends
  **Then** the code is exactly what it would be without them.
- **Given** an unexpected error (a bug), Ctrl+C or a closed output pipe
  **When** it escapes the command
  **Then** it ends as `70`, `130` or `141` (amendment of 2026-10-29, Resolved decision 7); the
  original wording, which let a bug exit with Python's `1` and a traceback, was withdrawn because
  that code is the refusal's.
- **Given** the table
  **When** the test suite runs
  **Then** a test per code feeds the input that produces it, through `main(argv)`, and asserts the
  code; the table lives in one place in the code (`cli.py` constants) and the README is checked
  against it.
- **Given** the codes are now stable
  **When** the help text, the README and the specs are updated
  **Then** the word "provisional" is removed from them (004 RF-10, 005 RF-06), and a change to the
  table is recorded as a breaking change.

### RF-05 — Refusals with `--json`

- **Given** a refused run (exit `1`) with `--json`
  **When** it ends
  **Then** standard output is empty and the one line goes to standard error, exactly as without
  `--json` (open question 1): a script reads the exit code, and a half-valid document must never
  appear on standard output.
- **Given** `--json` and a verdict `too early` or `not ready`
  **When** the command ends
  **Then** the document is still printed in full and the code is `3` or `4`: a non-zero code means
  "the answer is not yes", not "there is no output".

### RF-06 — Portuguese text

- **Given** `--lang pt-BR` (and `--lang en`)
  **When** either command prints its text
  **Then** every sentence MailVigil writes (titles, headings, rule names, reasons, notes, next
  step, the left-out line, the closing sentence, the no-reports message and the refusal lines) is in
  that language, and the layout rules of 004 RF-09 still hold: at most 80 columns, ASCII, no color,
  no control code.
- **Given** Portuguese text
  **When** it contains accented letters
  **Then** it is still ASCII (`nao`, not `não`), so that no console encoding can break the layout
  (open question 4 asks whether to relax this for UTF-8 streams).
- **Given** no `--lang`
  **When** the command runs
  **Then** the text is English, whatever the system language: the same command prints the same text
  on every machine (open question 2).
- **Given** a value that comes from the data (service names, addresses, selectors, domain)
  **When** it is printed in either language
  **Then** it is unchanged; only MailVigil's own words are translated.
- **Given** `--lang` with `--json`
  **When** the command runs
  **Then** the document is identical to the one without `--lang`: the data has no language.
- **Given** the two languages
  **When** the test suite runs
  **Then** a test asserts that both have the same set of message keys, that none is empty, and that
  every line of both stays within 80 columns on the same inputs; a test per language asserts the
  title, the answer word and the exit code of each of the three answers.
- **Given** the same reports
  **When** the text is printed in each language
  **Then** the numbers, the order of the sections and the exit code are equal (RF-04), because
  both texts are built from the same `Summary` or `Verdict`.

### RF-07 — The edge cases are tested, not assumed

- **Given** the test suite for this spec
  **When** it runs
  **Then** it contains, at least: a `Summary` with no period and no policy (`null`s in the
  document); a `Summary` with more senders and failing sources than the text limits show (all of
  them in the document); the same `Summary` built from the files in two orders (byte-equal
  documents); each of the three answers in both enforcing forms (the code does not change); a
  refusal with `--json` (empty standard output); a report value with a quote, a backslash, a
  control character and a non-ASCII letter (valid JSON, round trip equal to the sanitized value);
  `--lang` with an unknown value (usage error, exit `2`); and a Portuguese rendering of every
  verdict, note kind and rule.

## Non-functional requirements

### RNF-01 — Standard library only

- **Given** the project at any commit
  **When** `[project].dependencies` is read
  **Then** it is still empty. JSON uses `json`; the two languages are Python modules, with no
  catalog library.

### RNF-02 — The rules and the numbers do not move

- **Given** this spec
  **When** it is implemented
  **Then** `summary.py`, `verdict.py`, `reports/`, `config.py` and `senders.py` are not changed,
  except to add `to_dict`-like data conversion where open question 5 puts it; the 004 and 005 test
  suites pass untouched.

### RNF-03 — Output layers apart

- **Given** the layers
  **When** they are read
  **Then** there is one function per format (text in each language, JSON) that takes a `Summary`
  or a `Verdict`, and `cli.py` only chooses among them from `--json` and `--lang`; no output module
  imports the others' text, and no rule module imports an output module.

### RNF-04 — Typed and immutable

- **Given** the new code
  **When** `mypy` runs in strict mode
  **Then** it passes, and anything new that holds data is a frozen dataclass or a mapping built
  once.

### RNF-05 — The text cannot drift between languages

- **Given** the thresholds and the limits
  **When** the text of either language states them
  **Then** they are built from the same constants the rules and the display limits use, never
  retyped in a sentence, in either language (005 RNF-05 applied to both).

### RNF-06 — Synthetic fixtures only

- **Given** the tests, the docs and the schema example
  **When** they need a report, an address or a domain
  **Then** they use the documentation ranges and domains of 004 RNF-07. No real report, IP or
  domain of the maintainer enters the repository.

### RNF-07 — Fits the Python floor

- **Given** the Python floor `3.12`
  **When** the code is written
  **Then** it uses nothing newer, and the CI matrix passes.

## Open questions

All six were answered on 2026-10-28; the answers are Resolved decisions 1 to 6.

1. **A refusal under `--json`: stderr line or a JSON error object?** Recommended: the stderr line
   only (RF-05). A script already reads the exit code; a second format of error on standard output
   would be a second contract to freeze, and "standard output is either a full document or empty" is
   the rule that cannot be misread. Revisit if someone needs the cause in structured form.
2. **How is the language chosen?** Recommended: `--lang {en,pt-BR}`, default `en`, and no reading of
   the system locale. `locale` is process-global, behaves differently on Windows and Linux, and
   makes the same command print different text on two machines, which 004 RNF-02 forbids. The cost
   is that a Brazilian user types `--lang pt-BR` or aliases it; an environment variable
   (`MAILVIGIL_LANG`) is the cheap next step if that turns out to be a nuisance. (The `CLAUDE.md`
   line "locale or `--lang`" is rewritten to match the answer.)
3. **What does an unexpected exception exit with?** Recommended: leave Python's behavior (traceback,
   exit `1`). Catching everything to print a tidy line would hide bugs from the issue reports, and a
   distinct code (`70`, `EX_SOFTWARE`) is a sixth public code for a case that should not exist. The
   table says `1` means refused; the README says a traceback is a bug to report.
4. **Accents in the Portuguese text.** Recommended: ASCII only, as the English text, so there is a
   single layout rule and a legacy Windows console cannot turn `ã` into `?` (004 ADR-4 already
   replaces unencodable characters rather than failing). The cost is `nao` and `acao` in prose, which
   reads as informal. The alternative is accents when the stream's encoding is UTF-8, with the width
   rule counting characters; it doubles the layout tests.
5. **Where does the conversion to a dictionary live?** Recommended: in a new `render_json.py` that
   walks the frozen dataclasses (`dataclasses.fields`, enums by name), so `summary.py` and
   `verdict.py` stay untouched (RNF-02) and the JSON shape is a decision of the output layer, not a
   by-product of field names. The alternative, `dataclasses.asdict`, would freeze every internal
   field name as public contract.
6. **One spec or two?** Recommended: one, in three delivery stages, each a pull request: the exit
   codes and the JSON (the contract), then the Portuguese text. If the Portuguese text turns out to
   be larger than expected (a string table for ~60 messages), it becomes `007-portuguese-text` and
   this spec closes with the contract only. The contract is the part that blocks `1.0.0`; the text
   language does not.

## Resolved decisions

The maintainer approved the requirements, with the recommendations of questions 1 to 6, on
2026-10-28.

1. **A refusal under `--json` prints no JSON.** Standard output is empty and the one line goes to
   standard error, as without `--json`. Standard output is either a full document or empty.
2. **The language is explicit.** `--lang {en,pt-BR}`, default `en`; the system locale is never read.
   The `CLAUDE.md` line "locale or `--lang`" is rewritten to match.
3. **~~An unexpected exception keeps Python's behavior~~** (traceback, exit `1`). Superseded by
   decision 7.
4. **The Portuguese text is ASCII only** (`nao`, not `não`), so there is one layout rule.
5. **The JSON conversion lives in a new `render_json.py`**; `summary.py` and `verdict.py` are not
   touched and `dataclasses.asdict` is not used (the design makes the mapping explicit, ADR-2).
6. **One spec, delivered in stages**: the contract (exit codes and JSON) first, the Portuguese text
   after. If the text grows past what one spec holds, it becomes `007-portuguese-text` and this spec
   closes with the contract.

## Tests

Following [specs/README.md](../README.md#how-a-spec-is-tested):

- **Unit tests, no CLI:** the JSON conversion is called with built `Summary` and `Verdict` values,
  and the Portuguese renderers with the same inputs as the English ones; every key, enum name,
  `null` and line width is asserted on values.
- **The CLI through `main(argv)` and `capsys`:** the document on standard output, an empty standard
  output on a refusal, the exit code of each row of the table and the unknown `--lang` as a usage
  error; reports are synthetic files in `tmp_path`.
- **The documented example is the test:** the example in the schema page is parsed by the test and
  compared with the real output.
- **Synthetic only** (RNF-06).
- **Quality gate last:** `ruff` → `black --check` → `mypy` → `pytest --cov`, with its real result
  recorded in `tasks.md`.
7. **Amendment (2026-10-29, issue #60): a bug, Ctrl+C and a closed pipe have codes.** Before the
   first release, while a new code is still free. An uncaught exception ends as `70` (`EX_SOFTWARE`
   of `sysexits.h`), so a script can tell a bug from a refusal (`1`); the line on standard error
   names the exception class and the file and line, never the message (it may hold report text),
   and asks for a report. Ctrl+C ends as `130` and a closed pipe as `141` (128 plus the signal),
   both without output; on a closed pipe standard output is pointed at the null device so the
   interpreter does not complain at exit. The line stays in English, like argparse's usage errors,
   and there is no flag for the traceback. Reverses decision 3 and open question 3.
