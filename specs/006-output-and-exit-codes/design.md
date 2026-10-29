---
feature: Output and exit codes — `--json`, the stable exit-code contract and the Portuguese text
status: done
date: 2026-10-28
related:
  - 006-output-and-exit-codes/requirements.md
  - 005-reject-verdict/design.md
origin: conception
---

# 006 — Output and exit codes — design

## Overview

Nothing upstream of the `Summary` and the `Verdict` changes. This spec adds two output paths beside
the English text and a catalog the text renderers read their words from:

```text
paths ──ingest──▶ ... ──summarize──▶ Summary ─┬─render_summary(messages)──▶ text (en | pt-BR)
                                              ├─summary_document──────────▶ JSON
                              judge──▶ Verdict ┬─render_verdict(messages)──▶ text (en | pt-BR)
                                               └─verdict_document──────────▶ JSON
```

- **`render_json.py`** (new) turns a `Summary` or a `Verdict` into a plain `dict` and the `dict` into
  one JSON string. Each type has its own small, hand-written function, so the public shape is a
  decision written down, not a by-product of field names (ADR-2).
- **`messages/`** (new package) holds every sentence MailVigil writes, once per language, as a
  frozen dataclass whose fields are templates. `render.py` and `render_verdict.py` keep the layout
  and the logic and read the words from a `Messages` they are given; the default is English, so
  today's calls and today's tests are unchanged (ADR-3).
- **`cli.py`** gets `--json` and `--lang` on the two commands (in the shared parent parser), picks
  one of four output paths, and keeps the exit-code table (ADR-1). The rules, the model and the
  reports are untouched (RNF-02).
- **`docs/json-schema.md`** (new) is the written contract; a test parses its example and compares it
  with the real output (RF-03).

## Module layout

```text
src/mailvigil/
  render_json.py     # NEW  summary_document, verdict_document, dumps
  messages/          # NEW  the catalog
    __init__.py      #      re-exports Messages, Plural, ENGLISH, PORTUGUESE, language_by_code
    model.py         #      Plural and the frozen dataclasses of templates, grouped by area
    en.py            #      ENGLISH: today's text, moved, not rewritten
    pt_br.py         #      PORTUGUESE: ASCII only
  render.py          # CHANGED  takes a Messages (default ENGLISH); words from it, layout stays
  render_verdict.py  # CHANGED  same
  cli.py             # CHANGED  --json, --lang, the exit-code table without "provisional"
docs/json-schema.md  # NEW  fields, types, the compatibility promise, an example
```

`summary.py`, `verdict.py`, `reports/`, `config.py`, `senders.py` and `text.py` do not change. The
only imports that grow are in the output layer: `render.py` and `render_verdict.py` import
`messages`; `messages` imports the enums it keys on (`Answer`, `RuleId`, `NoteKind`, `Outcome`,
`Reason`, `ConfigReason`) and nothing from the renderers.

## Data model

### The JSON documents (RF-02, RF-03)

Both start with the same three keys, in this order: `schema_version` (`1`), `command` and `domain`.
Every optional value is `null`, never missing and never an empty string (RF-03). Counts are
integers; a share is never a field (RF-02). Enums are written as their `StrEnum` values, which are
already stable lower-case words.

**`summary`** (the keys in order):

| Key | Type | Notes |
|---|---|---|
| `config` | object | `source`: the path as the user typed it or `null`; `selectors`: how many are mapped |
| `reports` | object | `count`, `reporters` |
| `period` | object or `null` | `first_day`, `last_day` (`YYYY-MM-DD`), `days_spanned`, `days_with_reports` |
| `policy` | object or `null` | `p`, `sp` (`null` when absent), `np` (`null` when absent), `pct` |
| `earlier_p` | list of strings | other `p` values in the period, oldest first |
| `totals` | `counts` | all messages |
| `recognized_messages` | integer | |
| `senders` | list of `sender` | every row, in the summary's order, no display limit |
| `failing` | list of `source` | every failing source, the worst first, no display limit |
| `skipped` | list of object | `name` (file name only, no folder), `reason` |
| `skipped_by_reason` | list of object | `reason`, `count` |
| `duplicates`, `other_domain` | integers | |

`counts` is `{ok, dkim_only, spf_only, failing, total}`. `sender` is `{outcome, service, source_ip,
selectors, counts}` with `service` and `source_ip` `null` when the row has none. `source` is
`{outcome, service, source_ip, messages, selectors, dkim, spf, override_reasons}`, the same object in
both documents.

**`verdict`** (the keys in order):

| Key | Type | Notes |
|---|---|---|
| `answer` | `ready` / `too_early` / `not_ready` | the same value whether or not the policy is already `reject` |
| `enforcing` | string or `null` | the latest published `p`; `null` without reports |
| `deciding` | rule id or `null` | `null` exactly when `answer` is `ready` |
| `rules` | list of `rule`, always five, in order | |
| `recognized_failing`, `unrecognized_failing` | lists of `source` | every source, no display limit |
| `notes` | list of `{kind, numbers, texts}` | as `judge` builds them |
| `left_out` | `{skipped, duplicates, other_domain}` | |

`rule` is `{id, kind, measured, whole, needed, unit, comparison, passed, missing}`. `id` is a stable
word (`period_covered`, `days_with_report`, `messages_seen`, `recognized_failures`,
`unrecognized_failures`), `comparison` is `at_least` or `at_most`, and `unit` says what `needed`
and `measured` count (`days`, `percent_of_days`, `messages`, `per_mille_of_messages`), so a consumer
never has to know that rule 5 keeps tenths of a percent. `whole` is `0` when the rule is not a
share, as in the model.

The key order is fixed by how each function builds its `dict`; the list orders are the ones
`summarize` and `judge` already guarantee (005 RNF-02). The text of a report is already sanitized
(002); the JSON is written with `ensure_ascii=True`, so a non-ASCII letter is a `\uXXXX` escape and
no console encoding can corrupt it (RF-01).

### The catalog (RF-06, RNF-05)

```python
@dataclass(frozen=True, slots=True)
class Plural:
    """A phrase with a count in it, in its two forms; ``one`` is used for exactly 1."""
    one: str
    many: str

    def of(self, number: int, **values: str) -> str: ...
```

`Messages` is a frozen dataclass of nested frozen dataclasses grouped by area (`common`, `summary`,
`verdict`, `refusals`). Its fields are either a `str` template using `str.format` names (`{domain}`,
`{n}`) or a `Plural`. Both languages construct the same dataclass, so a missing message is a `mypy`
error and a `TypeError` on import, not a bare key in the output. Mappings keyed by an enum
(`Answer`, `RuleId`, `Outcome`, `Reason`, `ConfigReason`, `NoteKind`) are `Mapping[Enum, str]` fields
and a test iterates each enum (the same guard 004 and 005 already use).

The inventory of the sentences is the first task of the text stage: every literal in `render.py`,
`render_verdict.py`, `no_reports_message` and the refusal lines of `cli.py` moves into the catalog
as it is, in English, before a Portuguese word is written. The numbers inside a sentence
(thresholds, limits) are passed in as template values from the constants, never typed in either
language (RNF-05).

## Components

### render_json.py (RF-01 to RF-03)

- `summary_document(summary, config_source) -> dict[str, object]` and `verdict_document(verdict) ->
  dict[str, object]`: each builds its `dict` key by key from the frozen values, using small helpers
  (`_counts`, `_sender`, `_source`, `_rule`, `_note`, `_period`, `_policy`). An empty string becomes
  `None` through one helper, `_or_none`.
- `dumps(document) -> str`: `json.dumps(document, ensure_ascii=True, allow_nan=False, indent=2)`
  and no trailing newline (the command's `_write` adds it). `allow_nan=False` makes a stray `NaN` an
  error instead of invalid JSON; there are no floats in the documents, so it never fires.
- The rule id words and the units are two small `dict`s in this module keyed by `RuleId`; a test
  iterates `RuleId`, so a sixth rule cannot reach the output without a word.
- It computes nothing: every number is read from the `Summary` or the `Verdict`. The one thing it
  derives is `counts.total`, which is `Counts.total`, the property the text already uses.

### messages/ (RF-06)

- `ENGLISH` holds today's sentences, moved verbatim, so the 004 and 005 renderer tests pass
  untouched (RNF-02). `PORTUGUESE` is written after the inventory, ASCII only (Resolved decision 4)
  and checked by a test that encodes every template to ASCII.
- `language_by_code(code) -> Messages` maps the two accepted codes. The CLI accepts the code in any
  case (`pt-br` and `pt-BR`) and rejects anything else as a usage error (RF-07).
- Pluralization is `Plural.of`: Portuguese uses the singular for exactly 1, as English does, so one
  rule serves both. A phrase whose other words agree with the count ("1 arquivo ignorado", "2
  arquivos ignorados") is a `Plural` of the whole phrase, not of the noun, which is why the catalog
  stores phrases and not words.

### render.py and render_verdict.py (RF-06)

- `render_summary(summary, config_source, messages=ENGLISH)`, `no_reports_message(result, domain,
  messages=ENGLISH)` and `render_verdict(verdict, messages=ENGLISH)`. The new parameter is last and
  has a default, so no existing call changes.
- Layout code (columns, wrapping, `fit`, the beyond-the-limit shares of 005 RF-08) stays where it
  is. What changes is each literal: `"Why: every rule passes."` becomes
  `messages.verdict.why_ready`. Widths that were counted from an English prefix
  (`_WIDTH - 22` for `"MailVigil summary for "`) become `_WIDTH - len(prefix)` of the translated
  prefix, so a longer Portuguese title cannot push the domain past the screen.
- `share_tenths`, `format_share`, `fit`, `address`, `count_noun`: the helpers stay language
  neutral. `count_noun` and `address`'s `"no address"` are called with catalog phrases instead of
  English nouns; `count_noun` itself is kept for the English default and implemented through
  `Plural`.

### cli.py (RF-01, RF-04, RF-05, RF-06)

- The shared parent parser gains `--json` (`store_true`) and `--lang` (default `en`). Both are on
  `summary` and `verdict` only, so `--version` and the bare command are unaffected (RF-01).
- `_load` writes its refusal lines with the chosen `Messages`; with `--json` it writes nothing to
  standard output either way (Resolved decision 1).
- `_run_summary` and `_run_verdict` end in one branch:

  ```python
  if args.json:
      _write(sys.stdout, dumps(verdict_document(verdict)))
  else:
      _write(sys.stdout, render_verdict(verdict, messages))
  return _VERDICT_EXIT[verdict.answer]
  ```

  The exit code is computed before and apart from the format, so `--json` and `--lang` cannot
  change it (RF-04).
- The exit-code constants stay in `cli.py` as the single table, with the word "provisional" removed
  from comments and from the `verdict` help text (RF-04).
- A refusal line for a configuration file is built from the `ConfigError`: English keeps
  `str(error)` as 003 defined it; Portuguese builds `phrase [key]` from the `ConfigReason` and
  appends `detail` for `MALFORMED_TOML` and `UNKNOWN_KEY` only, because there the detail is the
  parser's own message or a suggested key (ADR-5). Lines for `--domain` conflicts and the missing
  domain come from the catalog.

## Interfaces

```text
mailvigil summary PATH... [--config FILE] [--domain DOMAIN] [--json] [--lang {en,pt-BR}]
mailvigil verdict PATH... [--config FILE] [--domain DOMAIN] [--json] [--lang {en,pt-BR}]
```

| Code | Meaning | stdout | stderr |
|---|---|---|---|
| `0` | `summary` printed; or `verdict` printed `ready` | the text or one JSON document | empty |
| `1` | refused (configuration, domain, no report kept) | empty | one line, or the no-reports explanation |
| `2` | usage error | empty | argparse's usage and message |
| `3` | `verdict` printed `too early` | the text or one JSON document | empty |
| `4` | `verdict` printed `not ready` | the text or one JSON document | empty |

`--help` and the usage errors of argparse stay in English whatever `--lang` says: they are
argparse's text, and the language is only known after parsing (Risk 4).

## ADRs

### ADR-1 — The exit codes stay as they are; what changes is the promise

- **Decision:** `0`, `1`, `2`, `3` and `4` keep the meanings 004 and 005 gave them; this spec removes
  "provisional", puts the table in one place and tests it.
- **Alternatives:** renumber (`10`/`11` for the verdicts, to keep `3` free for `sysexits`); add a
  code for "ready with notes".
- **Why:** no consumer exists yet, which is exactly when a renumbering would be free, but the
  current codes are already the smallest set that lets a script tell "yes", "wait" and "no" from
  "I could not run". `sysexits` values do not map onto these ideas and would be a table the reader
  must look up.
- **Trade-off:** `3` and `4` mean something only for `verdict`. `summary` never returns them, and
  the table says so.

### ADR-2 — The JSON is built by hand, type by type

- **Decision:** one function per type in `render_json.py`, listing every key.
- **Alternatives:** `dataclasses.asdict` plus a custom encoder; a generic walker over
  `dataclasses.fields`.
- **Why:** with a walker the public contract is whatever the dataclasses happen to be called. The
  hand-written mapping lets the model rename a field without a breaking change, drops derived or
  English-only fields (`SkippedFile.detail`, `Counts.fragile`), turns empty strings into `null`,
  and carries things the model does not hold as words (rule ids, units).
- **Trade-off:** a field added to the model does not reach the JSON until someone adds it. That is
  the point, and the test that compares the output with the documented example (RF-03) fails when
  the two disagree. The requirement's recommendation ("walks the frozen dataclasses") was about
  keeping the rule modules untouched; the mapping does that too.

### ADR-3 — A typed catalog of templates, not `gettext`

- **Decision:** two frozen dataclasses, one per language, whose fields are templates and `Plural`s.
- **Alternatives:** `gettext` with `.po`/`.mo` files; a `dict[str, str]` per language plus a test
  that the keys match; two copies of the renderers.
- **Why:** `gettext` needs compiled catalogs, a build step, a tool the contributors do not have and
  data files in the wheel, for two languages and about a hundred strings. A `dict` finds a missing
  key only when a test reaches it. Two copies of the renderers would duplicate every layout rule
  and let the two outputs drift. A dataclass makes a missing or misspelled message a type error, and
  sentences keep their word order because a template carries the whole sentence.
- **Trade-off:** adding a language is a new module of the same shape, not a data file a translator
  can edit alone. A third language reopens this (requirements, Non-goals).

### ADR-4 — The language is a parameter, not a global

- **Decision:** renderers take a `Messages` argument, defaulting to English.
- **Alternatives:** a module-level "current language"; reading `LANG` or `locale`.
- **Why:** a global makes `render_verdict` depend on state the test did not pass, which 004 RNF-02
  forbids ("nothing depends on the clock, the locale or the file system"). A parameter keeps every
  renderer a pure function and makes the English tests pass without edits.
- **Trade-off:** the argument threads through a few private helpers. The sentences that need it
  are the ones that need translating anyway.

### ADR-5 — A configuration refusal is translated by reason, English keeps its line

- **Decision:** with `--lang en` the line stays `str(error)` (003's contract, asserted by the 004
  tests); with `pt-BR` it is a translated phrase per `ConfigReason`, then `[key]`, then the
  `detail` only for `MALFORMED_TOML` and `UNKNOWN_KEY`.
- **Alternatives:** translate `detail` too (it is English prose built inside `config.py`, which this
  spec does not change); change English to the phrase form as well.
- **Why:** `ConfigError` already carries a stable reason and the key; the free text is for logs
  (003). Touching `config.py` to carry structured details would break RNF-02, and changing the
  English line would break tests of a finished spec for no reader's benefit. The two details kept
  are the ones a reader cannot act without: the parser's position and the suggested key.
- **Trade-off:** those two lines mix a Portuguese phrase with an English tail. A later spec can give
  `ConfigError` structured details and drop the mix.

### ADR-6 — `--lang` has no effect on the JSON and none on the exit code

- **Decision:** the JSON has no language; the exit code is computed before the format and language
  are chosen.
- **Why:** a script that parses output must not change behavior because someone's alias adds
  `--lang`. It is also the cheapest way to prove RF-04 and RF-06: one test runs each case in every
  combination and asserts one exit code and one document.
- **Trade-off:** `--lang` with `--json` is accepted and ignored for standard output; it still
  selects the language of a refusal line on standard error.

### ADR-7 — A bug, Ctrl+C and a closed pipe get codes (amendment of 2026-10-29)

- **Decision:** `main` wraps the dispatch: `Exception` gives `70` and one line, `KeyboardInterrupt`
  gives `130`, `BrokenPipeError` gives `141` after `_silence_stdout()`. `parse_args` stays outside,
  so a usage error is still argparse's `SystemExit(2)`.
- **Alternatives:** keep Python's traceback and `1` (the original decision: a script cannot tell a
  bug from a refusal); a flag that prints the traceback; `5` instead of `70`.
- **Why:** the table is a contract from the first release and a bug is the one case it did not
  cover. `70` follows `sysexits.h` and cannot collide with `0` to `4`; `130` and `141` are what a
  shell reports for the two signals.
- **Trade-off:** the contract has eight codes, not five, and the traceback is not shown. The line
  gives the class, file and line, which is what an issue needs; the message is left out on purpose.

## Impact on existing code

- `render.py` and `render_verdict.py`: every English literal moves to the catalog and the functions
  gain a last, defaulted parameter. The English output must be byte-equal to today's; the existing
  render and CLI tests are the proof and are not edited (RNF-02). Hard-coded English lengths
  (`_WIDTH - 22`, `_WIDTH - 30`) become computed from the templates.
- `cli.py`: two arguments, one output branch, the messages threaded into the refusal lines.
- `README.md`, `CLAUDE.md`, `docs/stack.md`, `specs/README.md`: the codes lose "provisional", the
  flags are documented, the `CLAUDE.md` language line is rewritten (Resolved decision 2), and the
  architecture block gains `render_json.py` and `messages/`. `/atualizar-docs` does this at the end.
- Nothing in `pyproject.toml` changes: `json` is the standard library and the wheel gains Python
  modules only. The `package` job's check for `Requires-Dist` is unaffected.

## Risks

1. **The documented schema drifts from the code.** Mitigation: the example in `docs/json-schema.md`
   is parsed by a test and compared field by field with the real output for a built `Summary` and
   `Verdict`, and a second test fails on any key that is not in the documented list (RF-03).
2. **The English text changes while it is being moved.** Mitigation: the catalog stage is a
   behavior-neutral refactor on its own pull request, as 005 stage 1 was; the unedited 004 and 005
   suites are the proof, and a quality gate runs before any Portuguese is written.
3. **Portuguese is wider and breaks the 80 columns.** Mitigation: widths derived from the templates
   (above) and a test that renders both languages on the stress inputs the English tests already use
   (long domain, long service name, many sources) and asserts every line fits and is ASCII (RF-06).
4. **`--help` and usage errors stay in English.** They are argparse's, built before `--lang` is
   known, and translating them means a custom parser. Recorded here and in the README; revisit with
   the third language if one comes. The requirement (RF-06) lists what MailVigil writes, which does
   not include argparse's text.
5. **A quote, a backslash or a control character in a report value corrupts the JSON.** Mitigation:
   `json.dumps` escapes them, values are already sanitized text, and a test round-trips the awkward
   values (RF-07).
6. **A script treats `1` as "not ready".** The table says `1` is a refusal and `4` is "not ready";
   the README gives the three-line shell example (`case $?`) so the difference is visible, and
   `docs/json-schema.md` repeats the table.
7. **The mixed-language configuration line (ADR-5)** reads oddly. Accepted for `0.1`; it is the
   lesser of the two costs listed in the ADR.

## Test strategy

- **`render_json`:** call `summary_document` and `verdict_document` with built values: every key and
  its order, every `null` (no period, no policy, empty `sp`), the full lists beyond the text limits,
  the rule ids and units for each `RuleId`, the answer in each enforcing form with an equal code,
  byte-equality of two builds from reordered files, and the awkward values round-tripped through
  `json.loads`.
- **Schema page:** the example is extracted and compared with the real output; the set of keys is
  compared with the documented list.
- **Catalog:** both languages construct (no missing field); every enum-keyed mapping covers its
  enum; every template encodes to ASCII; both have the same placeholders per field; no template is
  empty.
- **Renderers in both languages:** each answer's title, the answer word and the section order; every
  line within 80 columns on the stress inputs; the same numbers in both; the English output
  byte-equal to the moved one (the unedited suites).
- **CLI through `main(argv)` and `capsys`:** one test per exit code (RF-04); `--json` leaves standard
  error empty and `--json` on a refusal leaves standard output empty (RF-05); `--lang` unknown is
  `2`; `--lang` and `--json` do not change the code; the README's code table equals the constants.
- **Synthetic only** (RNF-06); **quality gate last** in every stage, with its real result recorded.
