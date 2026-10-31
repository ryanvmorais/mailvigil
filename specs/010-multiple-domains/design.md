---
feature: Several domains in one run, and internationalized domains typed as written
status: done
date: 2026-10-30
related:
  - 010-multiple-domains/requirements.md
  - 003-config-and-senders/design.md
  - 006-output-and-exit-codes/design.md
  - 008-html-report/design.md
origin: conception
---

# 010 — Multiple domains — design

## Overview

The pipeline of a run stays `resolve → ingest → summarize → judge → render`. What changes is the
number of domains that travels through it: **a run is a tuple of one or more domains, and a
single-domain run is the tuple of one**. There is no second code path for "many"; the one-domain
behavior of today is what the loop produces when it goes around once (ADR-3).

```text
--config / --domain ─▶ resolve_configs ─▶ (Config, …)         one Config per domain, in order
                          │  load_configs: [[domains]] or the top-level form; check_domain (IDN)
                          ▼
paths ─▶ ingest_many(paths, domains) ─▶ {domain: IngestionResult}    each file opened ONCE
                          ▼
              per domain:  summarize ─▶ judge ─▶ Summary, Verdict
                          ▼
   text  : blocks joined by a rule line (+ a tally line for verdict)
   --json: today's document (1 domain) | {schema_version, command, [answer,] domains:[…]} (2+)
   --html: stdout/--output FILE (1 domain) | --output DIR → mailvigil-<domain>.html each (2+)
   exit  : the worst answer (verdict); 0 (summary)
```

- **`summarize` and `judge` do not change at all.** They already take one domain's result and
  config, and know nothing of the others. The only new thing between them and the reports is the
  split of one reading into per-domain results (ADR-3).
- **The renderers do not change either.** `render_summary`, `render_verdict`, `render_html` and
  `summary_document`/`verdict_document` are called once per domain. The new code is the joining
  (ADR-5, ADR-7) and the choice of where pages go (ADR-8).
- **The domain rules live in one place**, `config.check_domain`, which already serves the file and
  `--domain`; the IDN conversion goes there and reaches `[spf]` keys and both inputs at once (ADR-2).

## Module layout

```text
src/mailvigil/config.py             # CHANGED  load_configs (replaces load_config), the [[domains]] reader,
                                    #          check_domain converts IDN, MAX_DOMAINS, four new reasons
src/mailvigil/reports/ingest.py     # CHANGED  ingest_many; ingest(paths, domain, …) = one-domain call of it
src/mailvigil/reports/__init__.py   # CHANGED  re-exports ingest_many
src/mailvigil/verdict.py            # CHANGED  worst_answer(verdicts) → Answer
src/mailvigil/render.py             # CHANGED  join_blocks, RULE; no_reports_message takes the domains
src/mailvigil/render_verdict.py     # CHANGED  render_tally(verdicts, messages)
src/mailvigil/render_json.py        # CHANGED  summaries_document, verdicts_document
src/mailvigil/messages/model.py     # CHANGED  the new sentences (see Interfaces)
src/mailvigil/messages/en.py, pt_br.py   # CHANGED
src/mailvigil/cli.py                # CHANGED  --domain repeatable, resolve_configs, the loop, page folder
src/mailvigil/cli_fetch.py          # CHANGED  load_configs(path)[0].fetch (ADR-1)
docs/json-schema.md, docs/stability.md, README.md, README.pt-BR.md, CHANGELOG.md, CLAUDE.md,
docs/stack.md, specs/README.md      # CHANGED
tests/test_config*.py, test_reports_ingest*.py, test_verdict.py, test_render*.py, test_cli_*.py,
test_json_schema_doc.py, help_golden.py, test_properties.py        # CHANGED / NEW cases
```

Not touched: `summary.py`, `senders.py`, `text.py`, `render_html.py`, `htmlkit.py`, `html_*.py`,
`fetch/`, `reports/` other than `ingest`.

## Data model

No new type in the domain model. A run carries two parallel things, both plain:

| Thing | Type | Meaning |
|---|---|---|
| the configs | `tuple[Config, ...]` | one per domain, in run order; each has its own `senders`, `spf`, `ranges`; the `fetch` field holds the file's `[fetch]` table, the same value in each (ADR-1) |
| the results | `dict[str, IngestionResult]` | key = `Config.domain`, same order; **shared** parts (`skipped`, `passed_over`) are equal in every value, `reports`, `duplicates` are the domain's own, `other_domain` is the same for all (ADR-4) |

The configuration file, in its new form:

```toml
[[domains]]
domain = "example.com"

[domains.senders]
google = "Google Workspace"

[domains.spf]
"bounce.example.com" = "Mailing service"

[domains.ips]
"192.0.2.0/24" = "Office"

[[domains]]
domain = "bücher.example"     # typed as written; the run calls it xn--bcher-kva.example

[fetch]                       # unchanged, at the top level
host = "imap.example.invalid"
```

The top-level form (`domain = "…"`, `[senders]`, `[spf]`, `[ips]`) stays and means one domain.

## Components

### config.py (RF-01, RF-02, RF-03)

- **`check_domain(value, key)`** (ADR-2): ASCII input follows the path of today. Non-ASCII input is
  converted and checked for fidelity, then follows the same label and length rules as an ASCII name.
- **`load_configs(path) -> tuple[Config, ...]`**: the steps of `load_config` up to the key check,
  then (ADR-1):
  1. `domains` present together with `domain`, `senders`, `spf` or `ips` → `DOMAIN_CONFLICT`, naming
     the first top-level key that clashes.
  2. `domains` present: must be a non-empty array of tables (`WRONG_TYPE` otherwise, `NO_DOMAINS`
     when empty), at most `MAX_DOMAINS` entries (`TOO_MANY_DOMAINS`).
  3. Each entry is read by the code that reads the top level today (`_read_domain`, `_read_senders`,
     `_read_spf`, `_read_ranges`) with the entry as the table, so the strictness is one set of
     rules. An unknown key in an entry is `UNKNOWN_KEY` with the suggestion against the entry's four
     keys; `fetch` inside an entry is unknown too. A failure names its key prefixed by the entry,
     `domains[2].spf`, so a long file points at the right place.
  4. Two entries with the same normalized domain → `DUPLICATE_DOMAIN`, naming the domain (an
     internationalized spelling and its `xn--` spelling are one domain, because both were converted).
  5. `[fetch]` is read once from the top level and given to every `Config`.
- **Reasons added to `ConfigReason`:** `DOMAIN_CONFLICT`, `NO_DOMAINS`, `TOO_MANY_DOMAINS`,
  `DUPLICATE_DOMAIN`. Existing values do not change (006: the values are stable keys). `MISSING_DOMAIN`
  covers an entry without `domain`.

### ingest.py (RF-04)

`ingest_many(paths, domains, now=None, recursive=False) -> dict[str, IngestionResult]` is the old
loop with three changes: the filter is membership in the set of wanted domains, each kept report
goes to its domain's list, and the duplicate key set is per domain (ADR-4). `ingest(paths, domain,
…)` stays with its signature and returns `ingest_many(paths, [domain], …)[domain]`, so the one-domain
result is, by construction, what it was (ADR-3). An empty `domains` or an empty name is the same
`ValueError` as today.

### verdict.py (RF-06)

`worst_answer(verdicts: Iterable[Verdict]) -> Answer`: `NOT_READY` if any, else `TOO_EARLY` if any,
else `READY`. It needs at least one verdict (`ValueError` otherwise: a caller's mistake). It stays in
`verdict.py`, which imports no text module; the exit-code table of `cli.py` maps its result, so
"the one place an answer becomes an exit code" (005 ADR-6) stays one place.

### render.py, render_verdict.py, render_json.py (RF-05, RF-07)

- `RULE` is a line of 80 `=`; `join_blocks(blocks) -> str` joins already-rendered blocks with a
  blank line, the rule and a blank line. With one block it returns that block, unchanged (ADR-5).
- `render_tally(verdicts, messages) -> str`: the one line that counts the answers.
- `summaries_document(summaries, config_source, top)` and `verdicts_document(verdicts, top)` wrap
  the existing per-domain functions (ADR-7). They are not called with one domain.
- `no_reports_message(result, domains, messages)`: the first line names the domain when there is
  one and counts them when there are several; the diagnostic lines (skipped, duplicates, other
  domains) are the shared ones (ADR-11).

### cli.py (RF-02, RF-05 to RF-07)

- `--domain` becomes repeatable (`action="append"`); `args.domain` is a list or `None`.
- **`resolve_configs(config_path, domains, messages) -> (tuple[Config, ...], source)`** replaces
  `resolve_config`. Same order as today: every `--domain` is checked first (so a bad value is
  refused before any file is read), then the file is chosen and loaded, then the selection (ADR-9).
- `_load` returns the configs, the source and the `dict` of results; it refuses (`EXIT_REFUSED`)
  when no domain kept a report (ADR-11).
- `_run_summary` and `_run_verdict` loop over the configs in order: `summarize` → (`judge`) → render.
  The exit code of `verdict` is `_VERDICT_EXIT[worst_answer(verdicts)]`.
- **Where the pages go (ADR-8):** decided right after the configs are known and before the reports
  are read, so a refused run costs nothing.

## Interfaces

```text
mailvigil summary|verdict [--config FILE] [--domain DOMAIN]… [--recursive] [--json] [--top N]
                          [--lang {en,pt-BR}] [--html [--output FILE|DIR]] PATH…
```

| Option | Rule |
|---|---|
| `--domain` | repeatable; each value is checked by `check_domain` (internationalized names accepted); a repeat of the same domain counts once; with a file, each must be in it (ADR-9) |
| `--output` | with `--html`: a **file** for one domain (today), an existing **folder** for two or more (ADR-8) |
| `--json` | one domain: today's document; two or more: the `domains` document (ADR-7) |
| the rest | unchanged |

Exit codes are the existing contract, no new code: `verdict` returns the worst answer (`0`, `3`,
`4`); `1` and `2` as today.

**New sentences** (English and Brazilian Portuguese, ASCII), in the existing groups of
`messages/model.py`: in `RefusalMessages` — `domain_not_listed` (`{wanted}`, `{path}`),
`no_reports_many` (`{count}`), `html_needs_folder` (`{count}`), `output_not_folder` (`{path}`), and
the four reasons in `config_reasons`; in `VerdictMessages` — `tally` (`{ready}`, `{early}`,
`{not_ready}`), written with the plural helper so that "1 domain" and "2 domains" read right.

**JSON for two or more domains** (field list goes to `docs/json-schema.md`):

```json
{
  "schema_version": 1,
  "command": "verdict",
  "answer": "not_ready",
  "domains": [
    {"schema_version": 1, "command": "verdict", "domain": "example.com", "answer": "ready", "…": "…"},
    {"schema_version": 1, "command": "verdict", "domain": "example.net", "answer": "not_ready", "…": "…"}
  ]
}
```

`summary` has the same envelope without `answer`. `answer` is the worst one, the meaning of the exit
code. Each element is byte for byte what a one-domain run prints; a consumer that already reads
that document reads each element with no change, and tells the two shapes apart by the `domains` key.

## Architecture decisions

### ADR-1 — `load_configs` returns a tuple; `load_config` goes away (RF-01, RF-08)

- **Decision:** the loader returns `tuple[Config, ...]` (one or more). The old `load_config` is
  removed; `cli_fetch` calls `load_configs(path)[0].fetch`. The `fetch` field of every `Config` of
  one file is the same `[fetch]` value.
- **Alternatives:** (a) keep `load_config` returning one `Config` and add `load_configs` beside it —
  two entry points that disagree on a multi-domain file; (b) a `ConfigFile(domains, fetch)` wrapper
  type — cleaner on paper, but `Config.fetch` already exists and `cli_fetch` reads it, so the wrapper
  would touch every caller to avoid a repeated reference.
- **Why:** one entry point means one set of rules; a file of one domain and a file of many differ
  only in the length of the tuple.
- **Trade-off:** the 27 test calls of `load_config` change, mechanically (a `load_one` test helper
  that asserts the length and returns the first). `fetch` keeps working with a multi-domain file
  without reading a domain.

### ADR-2 — Internationalized names go through the `idna` codec, and a name that changes is refused (RF-03)

- **Decision:** a non-ASCII value is converted with `value.encode("idna")` and accepted only when
  converting back gives the name that was typed, compared as follows: every ASCII letter of the
  input is lower-cased; a non-ASCII character is lower-cased only if its lower case is still
  non-ASCII (so `Ü` is `ü` but the Kelvin sign is **not** turned into `k`, and a character whose
  lower case has several characters, like `İ`, is left as it is). Anything the codec raises on
  (`UnicodeError`: a label over 63 characters, an empty label, a prohibited character) is refused.
  The codec does not check unassigned code points (Python's `nameprep` skips table A.1), so the
  code checks them with `stringprep.in_table_a1` before converting; a character unassigned in
  Unicode 3.2, an emoji among them, is refused. The conversion and the comparison are made label by
  label, so an `xn--` label and a Unicode one may share a name. Both refusals use `NON_ASCII_DOMAIN`, whose phrase says the
  name could not be converted as written and to write it in its `xn--` form. The result is the
  ASCII name, and then the label and length rules of today apply to it.
- **Alternatives:** (a) accept whatever the codec returns — silently turns `faß.example` into
  `fass.example` and the full stop `。` into a dot, so reports of a different domain would be counted
  for the person (the exact hole the Kelvin comment in `check_domain` was written against); (b)
  implement IDNA 2008 (UTS 46) in the package — thousands of lines of tables, and a dependency in
  disguise; (c) keep refusing and only improve the message — the issue's request, not met.
- **Why:** the codec is in the standard library, so the zero-dependency promise holds; the fidelity
  check keeps the property that matters most here, that the name the person typed is the name that
  is compared with the reports. Refusing is cheap: the person can always write the `xn--` form,
  which is accepted as today.
- **Trade-off:** IDNA 2003 is older than the 2008 rules some registries use. A name whose characters
  the two versions treat differently (`ß`, `ς`, joiners) or that is newer than Unicode 3.2 is refused
  instead of guessed. A look-alike letter from another script (a Cyrillic `а` in `exаmple.com`)
  converts to a different `xn--` name that matches no report of `example.com`: correct, and it is
  shown as `xn--…`, which is also a visible warning.

### ADR-3 — One reading; the single-domain call is the loop of one (RF-04, RNF-01)

- **Decision:** `ingest_many` opens, decompresses and parses every file once and files each parsed
  report under its domain. `ingest` is `ingest_many` with one domain.
- **Alternatives:** (a) call `ingest` once per domain — N times the opening and parsing of the same
  files (a folder of thousands of reports, eight domains: eight passes, and 002's byte and element
  caps applied eight times); (b) a separate many-domain function next to the old one — two loops to
  keep equal.
- **Why:** RF-04 and RNF-02 ask for a cost that does not grow with the number of domains, and one
  loop is one behavior to test. The existing `ingest` tests then also test the many-domain path.
- **Trade-off:** the filter now keeps the parsed reports of every wanted domain at once, where the
  one-domain filter kept only its own. The memory is bounded by the same caps and is the sum of what
  separate runs would have held one after another.

### ADR-4 — What belongs to the domain and what is shared (RF-04)

- **Decision:** `reports` and `duplicates` are per domain (the duplicate key, reporter and report id,
  is checked within a domain's list, as the filter runs first today). `skipped` and `passed_over`
  are the same in every result, because a file that could not be read cannot be assigned to a domain.
  `other_domain` counts the reports of **no domain of the run**, the same number in every result.
- **Alternatives:** (a) `other_domain` per domain counting everything that is not its own — blocks
  that add up to more than the files read; (b) print the shared parts once at the end — a different
  layout from a single-domain run, so a block would no longer be that run's text.
- **Why:** every block stays equal to what a run of that one domain would print when the folder
  holds no other domain's reports; with other domains' reports in the folder, the block does not
  claim to have dropped what another block kept.
- **Trade-off:** a refused file is listed in every block (eight blocks, eight copies of "1 file
  refused"). Noisy at the bottom, honest, and a person can still read each block alone. `--top` and
  the JSON keep it per document as well.

### ADR-5 — Text blocks set apart by a rule; a tally line for the verdict (RF-05)

- **Decision:** the blocks are joined by a blank line, a line of 80 `=` and a blank line. `verdict`
  ends with one line, `N domains: A ready, B too early, C not ready` (the zero counts are omitted),
  after the last block. `summary` has no tally: it has no answer.
- **Alternatives:** a line naming the domain over each block (redundant: every block's title names
  it); a table up front before the blocks (the person reads the blocks to find out which is bad;
  the tally at the end is where the eye lands after scrolling, and it is the same line the exit code
  has in words).
- **Why:** a rule is visible when scrolling a long output and costs no new layout; the 80-column
  and ASCII rules hold because both pieces are plain.
- **Trade-off:** a block's own sections are already separated by blank lines, so the rule is the
  only heavier mark; it must not look like content to a script, which is why a script is pointed
  at `--json`.

### ADR-6 — The exit code is the worst answer (RF-06)

- **Decision:** `4` if any domain is not ready, else `3` if any is too early, else `0`.
- **Alternatives:** a new code for "mixed" (a new public code that scripts then have to learn,
  and what it would say is already in the JSON); `0` if any is ready (reads as "something is safe",
  which is the opposite of what a `cron` job cares about); the code of the first domain (depends on
  file order).
- **Why:** `0` keeps one meaning, "safe to move every one of these", and the order of urgency is
  the one 005 already ranks (a problem beats missing data).
- **Trade-off:** one bad domain makes the whole run exit `4`; a script that needs one domain's code
  passes `--domain` or reads `answer` of each element in the JSON.

### ADR-7 — The `domains` envelope exists only for two or more (RF-07)

- **Decision:** with one domain the document is today's. With two or more it is
  `{schema_version, command, [answer], domains: [...]}`, each element a complete one-domain document.
  `schema_version` stays `1`. `--top N` is applied inside each element, so each element's own `top`
  key says what that domain left out.
- **Alternatives:** always the envelope with `schema_version` `2` (a breaking change and a major
  release for everybody, to serve a feature few have used); a different command name for the many
  form (`command` is a name, not a shape); tying the shape to whether the file uses `[[domains]]`
  (steadier for a script, but `--domain a` would print a different shape depending on the file —
  open question 3, decided by the count of the run).
- **Why:** nobody who runs a single domain sees any difference, and the new shape is reachable only
  by naming more than one domain.
- **Trade-off:** the shape depends on the count in the run; documented as such, with the rule "look
  for `domains`". The addition is not a field inside an existing document, so
  `docs/json-schema.md` and `docs/stability.md` say it in words instead of leaving it implied.

### ADR-8 — A folder of pages, named from the validated domain (RF-07)

- **Decision:** with two or more domains and `--html`, `--output` must be an existing folder, and
  the pages are `mailvigil-<domain>.html`. Without `--output`, or with a path that is not a folder,
  the run is refused before any report is read. Every page is rendered first and written after, each
  by the existing atomic `_write_page`. Nothing is printed on success, as with `--output FILE`. A
  write that fails ends in `output_failed` naming that file; pages already written stay whole.
- **Alternatives:** the folder created when missing (a mistyped path silently makes a tree — open
  question 5); `<domain>.html` (a first label such as `con` or `nul` is a reserved device name on
  Windows, with or without the extension); an index page (non-goal: a new interface).
- **Why:** the prefix makes the name safe on both platforms, and the domain, being letters, digits,
  hyphens and dots after `check_domain`, cannot contain a separator. Rendering everything before
  writing keeps a failure in a renderer from leaving half of the folder written.
- **Trade-off:** pages from an earlier run of a domain no longer in the file stay in the folder; the
  tool never deletes. A path over the system's limit (a 253-character domain plus a long folder)
  fails with the system's own words in `output_failed`.

### ADR-9 — `--domain` selects; it does not add (RF-02)

- **Decision:** with a file, `--domain` narrows the run to the listed domains of the file, in the
  file's order, and a value that is not in the file is refused (`domain_mismatch` when the file has
  one domain, as today; `domain_not_listed` when it has several). Without a file, each distinct
  `--domain`, in the order given, is a domain with empty maps.
- **Alternatives:** `--domain` adds domains to the file's (a typo silently becomes a domain with no
  identities, and a verdict that looks fine because nothing is known to be wrong is not fine);
  refusing `--domain` with a multi-domain file (a script could not ask for one).
- **Why:** it keeps the single rule "the identities come from the file; a flag cannot invent them".
- **Trade-off:** to run a domain that is not in the file, the person adds it to the file or runs
  without it; the first run without a file is unchanged.

### ADR-10 — At most 50 domains (RF-01, RNF-02)

- **Decision:** `MAX_DOMAINS = 50`, for entries of the file and for the distinct `--domain` values.
  Over it is `TOO_MANY_DOMAINS`.
- **Alternatives:** no cap (a 64 KiB file can hold hundreds of entries, and the output, the JSON and
  the pages grow with them); 10 (an agency that looks after a dozen clients would be refused on day
  one).
- **Why:** a number that serves the real user and bounds the work and the output; the 64 KiB cap of
  the file already bounds the input.
- **Trade-off:** it is arbitrary, like the other caps (`MAX_CONFIG_BYTES`); raising it is a minor
  change.

### ADR-11 — Refuse only when no domain kept a report (RF-04)

- **Decision:** if at least one domain has a report, the run goes on and the others get their
  result, with `judge` giving them `too early` as it does for an empty summary today (no period, no
  days: the data rules fail, and the text says "no reports"). If none has, the run is refused with
  `EXIT_REFUSED` and one explanation: for one domain, today's line; for several, `no_reports_many`
  and the same diagnostic lines.
- **Alternatives:** refuse the whole run when any domain is empty (a new client's domain blocks the
  other seven); never refuse (a typo in every path would print N empty blocks and an exit code `3`,
  which reads as "wait a few days" when the truth is "nothing was read").
- **Why:** an empty domain is information (its reports have not arrived yet); an empty run is a
  mistake.
- **Trade-off:** one more state to explain in the tally ("too early" can mean "no report yet"), which
  the block itself already says.

## Impact

- **New:** `ingest_many`, `load_configs` and the `[[domains]]` reader, `worst_answer`, `join_blocks`,
  `render_tally`, the two JSON envelopes, the page folder, four config reasons and six sentences in
  two languages. `[project].dependencies` stays empty.
- **Changed:** `check_domain` (IDN), `resolve_config` → `resolve_configs`, `--domain` repeatable (its
  help text, which the recorded `--help` goldens carry), `cli_fetch` (one line).
- **Unchanged and tested to stay so:** the text, JSON, HTML and exit codes of a one-domain run; the
  isolation of the network code.
- **Release:** a minor version (1.6.0): a new configuration key, a new option form, a new document
  shape, a new refusal; nothing public changes meaning.
- **Docs:** README and README.pt-BR (configuration, exit codes, a "several domains" example),
  `docs/json-schema.md` (the two envelopes, examples built by the code), `docs/stability.md` (the
  configuration row and the JSON row), CHANGELOG, CLAUDE.md (architecture lines), `docs/stack.md`
  (the `idna` codec), `specs/README.md`.
- **CI:** nothing new.

## Risks

- **A one-domain regression.** The refactor touches the shared loop. Mitigation: the existing test
  suites run unchanged and are the first gate of stage 1 and 2; a golden comparison of the text and
  JSON of a one-domain run before and after (RNF-01).
- **IDNA 2003 refuses a real name** (a registry that allows `ß` or newer characters). Mitigation:
  the refusal says to write the `xn--` form, which works; the limit is documented in the README, not
  hidden.
- **The envelope is a second shape for a script.** Mitigation: one rule, "look for `domains`", the
  elements are the old document, and the page of the schema has an example of each.
- **A file with many domains is hard to read.** Mitigation: a failure names its entry
  (`domains[2].spf`); the loader never repairs.
- **Windows path length** for a page of a very long domain. Mitigation: the system's own error in
  `output_failed`.

## Tests

Following [specs/README.md](../README.md#how-a-spec-is-tested).

- **`test_config.py`:** the `[[domains]]` file (two domains, each with its own maps; the same
  selector mapped differently in two entries); every refusal of RF-01 (conflict with each top-level
  key, empty array, wrong type, no `domain` in an entry, duplicate domain, over the cap, unknown key in
  an entry with the suggestion, an `[spf]` key outside its own entry's domain but inside another's); the key
  prefix in a refusal; the one-domain file unchanged; `[fetch]` on a multi-domain file.
- **`check_domain`:** a table of inputs — accented lower and upper case, `xn--` form, the same name in
  both spellings, `ß`, `ς`, the Kelvin sign, `İ`, the ideographic full stop, a mixed-script name, a 64-
  character label, an unassigned character, a trailing dot — each with the expected domain or reason.
- **`test_reports_ingest*.py`:** `ingest_many` with three domains and a foreign one: each report to
  its domain, `other_domain` counts the foreign one only, a duplicate within a domain and the same
  ids in two domains, shared `skipped`; **a spy on `read_xml`/`parse_report` proves each file is
  opened once** (RF-04); `ingest` with one domain returns exactly the old result.
- **`test_verdict.py`:** `worst_answer` over all nine pairs and an empty input.
- **`test_render*.py`:** `join_blocks` (one block unchanged, several with the rule), `render_tally`
  in both languages and the plural cases, 80 columns and ASCII; `no_reports_message` for one and for
  several.
- **`test_cli_*.py`:** `main(argv)` with `capsys`: a three-domain run in text, in Portuguese, with
  `--json` (the envelope; each element equal to the one-domain document of the same data), with
  `--top`; `--domain` repeated, with a file (subset, order of the file, unlisted, repeat) and
  without; an internationalized `--domain` and file; the exit code for each mix of answers; a domain
  with no reports among others; no reports at all; `--html` with one domain (stdout and `--output
  FILE` as before), with several and no `--output`, with a file that is not a folder, and with a
  folder (the names, the pages equal to the one-domain page, a failing write); `fetch --config` on a
  `[[domains]]` file.
- **Compatibility:** the existing one-domain suites unchanged; the recorded `--help` goldens updated
  only for the `--domain` and `--output` lines.
- **Contract:** `test_json_schema_doc.py` extended; the examples of the envelope built by the code.
- **Isolation:** `test_offline_isolation.py` unchanged and still green.
- **Properties:** a Hypothesis case that a one-domain run through `ingest_many` equals `ingest`, and
  that no report is ever kept by two domains.
- **Synthetic only:** `example.com`, `example.net`, `.invalid`, an invented internationalized name,
  documentation address ranges (RNF-06).
- **Quality gate last:** `ruff` → `black --check` → `mypy` → `pytest --cov`, with its real result
  recorded in `tasks.md`.

## Refinements of the requirements

The design closes these points the requirements left to it; none changes a requirement's intent.

1. **Page names** are `mailvigil-<domain>.html`, not `<domain>.html` (RF-07, ADR-8), so that a domain
   such as `con.example` is not a reserved device name on Windows.
2. **The block heading** of RF-05 is the block's own title, which already names the domain; the
   blocks are set apart by a rule line (ADR-5).
3. **The cap** of RF-01 is 50 (ADR-10).
4. **The refusal reasons** of RF-01 are four new values of `ConfigReason` (`DOMAIN_CONFLICT`,
   `NO_DOMAINS`, `TOO_MANY_DOMAINS`, `DUPLICATE_DOMAIN`); a name the IDN conversion refuses reuses
   `NON_ASCII_DOMAIN` (ADR-2).
5. **`other_domain`** and **the shared parts** of a result are closed in ADR-4.
