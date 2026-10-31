---
feature: Several domains in one run, and internationalized domains typed as written
status: done
date: 2026-10-30
related:
  - 010-multiple-domains/requirements.md
  - 010-multiple-domains/design.md
origin: conception
---

# 010 — Multiple domains — Tasks

Each stage is one pull request (issue → branch → PR); Claude opens it and never merges. Inside a
stage, tests come first: write the test that feeds the input, watch it fail for the right reason,
then write the code. Every domain in a test is invented (`example.com`, `example.net`, `.invalid`,
an invented internationalized name) and every address is in a documentation range (RNF-06).

The stages go from the bottom up: the domain rule (IDN), the reading that serves many domains, the
vocabulary nothing calls yet, then the configuration and the command that wire them for text and
exit codes, then the two outputs that need more (`--json`, `--html`), then the close. **The rule of
the whole spec is RNF-01:** the existing test files for one domain are edited only where a
signature changed (`load_config`, `resolve_config`); if any other one fails, the code is wrong.
The release (1.6.0) is the maintainer's act and is prepared apart, with `/preparar-release`.

## Stage 0 — The spec (RF-01 to RF-08, RNF-01 to RNF-06)

- [x] `requirements.md` written and approved by the maintainer (2026-10-30).
- [x] `design.md` written and approved by the maintainer (2026-10-30).
- [x] `tasks.md` approved (2026-10-30); `specs/README.md` row 010 at `approved`. The three files go in one
  documentation PR (issue #79), without code, so the quality gate does not apply to this stage.

## Stage 1 — Internationalized domains (RF-03, RNF-04, ADR-2)

- [x] `tests/test_config.py`, written first: a table for `check_domain` — accented lower and upper
  case (`bücher.example`, `BÜCHER.example`) give `xn--bcher-kva.example`; the `xn--` form is
  accepted unchanged and equals the Unicode spelling; a trailing dot and surrounding spaces are
  ignored; `faß.example`, a Greek final sigma, the Kelvin sign (U+212A), `İ`, the ideographic full
  stop (U+3002) inside a name, an unassigned character, a 64-character label, an empty label and a
  name with a prohibited character are each refused with `NON_ASCII_DOMAIN` (or `INVALID_DOMAIN`
  where the converted name fails the label rules), naming the key; a mixed-script look-alike
  converts to a name that is not the Latin one; the same table through an `[spf]` key (it must be
  within the domain after conversion) and through `--domain`. — RF-03
- [x] `src/mailvigil/config.py`: `check_domain` converts a non-ASCII value with the `idna` codec and
  accepts it only when the way back gives the typed name under the case rule of ADR-2; every
  `UnicodeError` becomes a refusal; the phrase of `NON_ASCII_DOMAIN` in both languages says the
  name could not be converted as written and to write it in its `xn--` form (`messages/`). The
  ASCII path is untouched. — RF-03, ADR-2
- [x] `tests/test_cli_*.py`: `summary --domain bücher.example` and a file with the same domain run,
  and print the `xn--` form (text and the `domain` field of `--json`); a refused name prints the
  line of the language. — RF-03
- [x] Quality gate of the stage: `uv run ruff check .` → `uv run black --check .` → `uv run mypy` →
  `uv run pytest --cov`. Record the result here, with the number of tests and the coverage. — RNF-01, RNF-06
  Result (2026-10-30): ruff, black and mypy clean; 3165 passed, 4 skipped (POSIX modes and symbolic
  links on Windows); coverage 100%. Two things differ from the plan: the `idna` codec does not refuse
  unassigned code points, so `_label_to_ascii` checks them with `stringprep.in_table_a1` (ADR-2
  amended); and the conversion runs label by label. The old tests that pinned `exämple.com` as
  refused now pin `faß.example`, because that name converts.

## Stage 2 — One reading for many domains (RF-04, RNF-02, ADR-3, ADR-4)

- [x] Compatibility first: check that the existing suites pin the exact text, JSON and result of a
  one-domain run over a folder with a foreign report, a duplicate and a refused file; if a case is
  missing, add it **before** the refactor and see it pass on the current code. — RNF-01
- [x] `tests/test_reports_ingest_many.py`, written first: three wanted domains and a foreign one —
  each report goes to its own domain, a report is in exactly one result, `other_domain` counts only
  the foreign one and is the same in every result, `skipped` and `passed_over` are the same in
  every result, results come in the order of the wanted domains; a duplicate within a domain is
  counted there, the same reporter and id under two domains is **not** a duplicate; an empty list or
  an empty name raises `ValueError`; **a spy on the XML reader and the parser shows each file opened
  and each report parsed once** whatever the number of domains; `ingest` with one domain equals
  `ingest_many` with that one. A Hypothesis case in `test_properties.py`: no report is ever kept by
  two domains, and a one-domain `ingest_many` equals `ingest`. — RF-04, RNF-02
- [x] `src/mailvigil/reports/ingest.py` and `reports/__init__.py`: `ingest_many`, with `ingest` as its
  call for one domain. — RF-04, ADR-3
- [x] Quality gate of the stage (as above). Record the result here. — RNF-01, RNF-06
  Result (2026-10-30): ruff, black and mypy clean; 3186 passed, 4 skipped (POSIX modes and symbolic
  links on Windows); coverage 100%. The compatibility case was missing and was added first
  (`test_a_one_domain_run_over_a_mixed_folder_has_the_whole_result_pinned`), green on the old code.
  The only edit to an old test is the new name in the public-API list. `ingest_many` keys its
  results by the normalized name and collapses a repeated domain into one.

## Stage 3 — Vocabulary: worst answer, joining, tally, sentences (RF-05, RF-06, ADR-5, ADR-6, ADR-11)

- [x] `tests/test_verdict.py`, `tests/test_render.py`, `tests/test_render_verdict.py`,
  `tests/test_messages.py`, written first: `worst_answer` over every combination of the three
  answers and an empty input (`ValueError`); `join_blocks` returns one block unchanged and joins
  several with a blank line, the 80-character rule and a blank line; `render_tally` in both
  languages for 1, 2 and 5 domains and for each mix, zero counts omitted, 80 columns, ASCII;
  `no_reports_message` for one domain is today's text byte for byte and for several names the count
  and keeps the diagnostic lines; every new sentence exists in both languages and is ASCII. — RF-05,
  RF-06, ADR-11
- [x] `src/mailvigil/verdict.py`, `render.py`, `render_verdict.py`, `messages/model.py`, `en.py`,
  `pt_br.py`: `worst_answer`, `RULE`, `join_blocks`, `render_tally`, `no_reports_message(result,
  domains, messages)` and the sentences `domain_not_listed`, `no_reports_many`, `html_needs_folder`,
  `output_not_folder` and `tally`. Nothing calls them yet except the tests. — RF-05, RF-06
- [x] Quality gate of the stage (as above). Record the result here. — RNF-01, RNF-06
  Result (2026-10-30): ruff, black and mypy clean; 3251 passed, 4 skipped (POSIX modes and symbolic
  links on Windows); coverage 100%. Two things differ from the plan: the `tally` sentence is a
  `Plural` plus three parts (`tally_ready`, `tally_early`, `tally_not_ready`), because a zero count
  has to be left out and one template with three placeholders cannot do that; and
  `no_reports_message` takes a sequence of domains (the callers and the old tests pass a list of
  one), which is the only edit to an old test.

## Stage 4 — The configuration and the command (RF-01, RF-02, RF-04 to RF-06, RF-08, ADR-1, ADR-9 to ADR-11)

The largest stage: the file and the command that reads it are tested together, in text.

- [x] `tests/test_config.py`, written first: a `[[domains]]` file of two domains, each with its own
  `senders`, `spf` and `ips`, the same selector mapped to different names; the entries come in file
  order; each refusal of RF-01 — a top-level `domain`, `senders`, `spf` or `ips` beside `domains`
  (`DOMAIN_CONFLICT`, naming the key), an empty array (`NO_DOMAINS`), `domains` not an array of
  tables (`WRONG_TYPE`), an entry without `domain` (`MISSING_DOMAIN`), two entries with the same
  domain, the Unicode and the `xn--` spelling of one name (`DUPLICATE_DOMAIN`), 51 entries
  (`TOO_MANY_DOMAINS`), an unknown key in an entry with the suggestion, `fetch` inside an entry, an
  `[spf]` key that is within another entry's domain but not its own; the key of a refusal is
  prefixed `domains[N].`; the one-domain file is read as before; `[fetch]` at the top level reaches
  every `Config`; a bad entry never yields a partial tuple. — RF-01, ADR-1, ADR-10
- [x] `src/mailvigil/config.py`: `load_configs` (replacing `load_config`), the entry reader reusing
  `_read_domain`/`_read_senders`/`_read_spf`/`_read_ranges`, `MAX_DOMAINS`, the four reasons in
  `ConfigReason`, their phrases in both languages, `domains` in the allowed keys. `cli_fetch`
  becomes `load_configs(path)[0].fetch`. The 27 test calls of `load_config` move to a `load_one`
  helper, mechanically. — RF-01, RF-08, ADR-1
- [x] `tests/test_cli_summary.py`, `tests/test_cli_verdict.py`, `tests/test_cli_domains.py`, written
  first: `--domain` repeated with a file (the subset in file order, a repeat once, an unlisted value
  refused with `domain_mismatch` for a one-domain file and `domain_not_listed` for several, a bad
  value refused before the file is read) and without a file (each distinct value with empty maps, in
  the order given; 51 values refused); a three-domain run of `summary` in text and in Portuguese —
  blocks equal to the one-domain text of the same data, set apart by the rule, exit `0`; of `verdict`
  — the tally line, and the exit code for each mix (all ready `0`; one too early `3`; one not ready
  and one too early `4`); a domain with no reports among others (its block says so, its answer is
  `too early`, the run is not refused); no reports for any (exit `1` with the line of
  `no_reports_many`); a report of domain B in the folder is not "other domain" in A's block; a refused
  file appears in each block; `fetch --config` on a `[[domains]]` file; the isolation test still
  green. — RF-02, RF-04, RF-05, RF-06, RF-08, ADR-4, ADR-9, ADR-11
- [x] `src/mailvigil/cli.py`: `--domain` repeatable (its help text, and `help_golden.py` regenerated
  only for that line), `resolve_configs` replacing `resolve_config`, `_load` over `ingest_many`, the
  loops in `_run_summary` and `_run_verdict`, `_VERDICT_EXIT[worst_answer(...)]`. The one-domain
  path goes through the same loops. — RF-02, RF-05, RF-06, ADR-6, ADR-9
- [x] Quality gate of the stage (as above). Record the result here. — RNF-01, RNF-06
  Result (2026-10-31): ruff, black and mypy clean; 3332 collected, 4 skipped (POSIX modes and
  symbolic links on Windows), the rest passed; coverage 100%. Three things differ from the plan:
  (1) the key of a refusal inside an entry counts the entries from 1 (`domains[2].spf`), as the
  person counts the blocks; (2) until stages 5 and 6 exist, `--json` and `--html` with two or more
  domains are refused before any report is read (`_load`, one English line, no message key), so
  main never prints one domain's answer for a run of several; stages 5 and 6 delete that guard and
  its test; (3) the `fetch --config` test lives in `test_cli_fetch.py`, next to its fixtures.

## Stage 5 — `--json` with several domains (RF-07, ADR-7)

- [x] `tests/test_render_json_domains.py`, `tests/test_cli_domains.py`, `tests/test_json_schema_doc.py`,
  written first: `summaries_document` and `verdicts_document` produce the envelope with the keys in
  the documented order; each element equals the one-domain document of the same data, byte for byte
  after `dumps`; `answer` is the worst one and matches the exit code; `--top N` trims inside each
  element and each carries its own `top` key; one domain still prints today's document (no
  `domains` key); the examples of `docs/json-schema.md` for the envelope are built by the code and
  compared with the page. — RF-07
- [x] `src/mailvigil/render_json.py` and `cli.py`: the two envelope functions, used when the run has
  two or more domains. — RF-07, ADR-7
- [x] `docs/json-schema.md`: the envelope for `summary` and `verdict`, the rule "look for `domains`",
  the examples. — RF-07
- [x] Quality gate of the stage (as above). Record the result here. — RNF-01, RNF-06
  Result (2026-10-31): ruff, black and mypy clean; 3355 collected, 4 skipped (POSIX modes and
  symbolic links on Windows), the rest passed; coverage 100%. Two things differ from the plan:
  (1) `tests/test_json_schema_doc.py` also walks the two envelopes (`summaries`, `verdicts`) against
  the tables of the page, and the page has two examples, `Several summaries` and `Several verdicts`,
  with a sentence under each block because the test reads the block right below the heading; (2) the
  temporary guard of stage 4 now refuses `--html` only, with its own line, and stage 6 deletes it.

## Stage 6 — `--html` with several domains (RF-07, RNF-05, ADR-8)

- [x] `tests/test_cli_html_domains.py`, written first: one domain with stdout and with `--output FILE`
  exactly as before; several domains with no `--output` refused before any report is read (the line
  of `html_needs_folder`, exit `1`: it depends on the file, so it is a refusal and not a usage error); with a path that is not a folder or does not
  exist (`output_not_folder`); with a folder — one `mailvigil-<domain>.html` per domain, each equal
  to the page of a one-domain run of the same data, ASCII, no script, no network; a domain named
  `con.example` gets a safe name; an internationalized domain gets its `xn--` name; a read-only
  folder or a failing write ends in `output_failed` naming that file, nothing is printed, and the
  pages written before it are complete; `--json` with `--html` still refused. — RF-07, RNF-05, ADR-8
- [x] `src/mailvigil/cli.py`: the decision of where the pages go, right after the configs and before
  the reports are read; all pages rendered first, then each written with `_write_page`. — RF-07
- [x] Quality gate of the stage (as above). Record the result here. — RNF-01, RNF-06
  Result (2026-10-31): ruff, black and mypy clean; 3371 collected, 4 skipped (POSIX modes and
  symbolic links on Windows), the rest passed (3367); coverage 100%. Three things differ from the
  plan: (1) the decision lives in `_load` through `_pages_refusal`, which stage 4's temporary guard
  and its test (`test_cli_domains.py`) gave way to; (2) the write loop is `_write_pages`, shared by
  the one-file and the folder paths, so the refusal line of `output_failed` is built once; (3) the
  `--output` metavar is now `FILE|FOLDER` and its help says what the folder gets, so
  `help_golden.py` was regenerated from the live text.

## Stage 7 — Documentation and close (RNF-01, RNF-04)

- [x] `README.md` and `README.pt-BR.md` (the headings stay in step; `tests/test_readme_pt_br.py`):
  the `[[domains]]` form with an example, `--domain` repeated, internationalized names and the IDNA
  2003 limit, the exit code as the worst answer, `--json` with several, `--html --output FOLDER`.
  The exit-code table keeps its eight rows (a test compares it with `cli_common.py`). — RF-01 to RF-07
- [x] `docs/stability.md` (the configuration row gains `[[domains]]`, the JSON row the envelope, the
  commands row `--domain` repeatable), `CHANGELOG.md` (under `[Unreleased]`: Added), `CLAUDE.md`
  (architecture lines for `ingest_many`, `load_configs`, `worst_answer`, and the ⚠️ that the one-domain
  path is the loop of one), `docs/stack.md` (the `idna` codec and its IDNA 2003 limit),
  `specs/README.md` (010 `done`, the delivery column, the maintenance note). Run `/atualizar-docs`.
- [x] A last compatibility pass: the full suite with the one-domain files untouched except the
  signature edits of stages 4 and the `--help` golden; the wheel declares no `Requires-Dist`
  (`uv build` and the `package` check); `status: done` in the three files. — RNF-01, RNF-04
- [x] Quality gate of the stage (as above), the real result recorded; then `/preparar-release` for
  1.6.0 as a separate PR (publishing is the maintainer's). — RNF-01, RNF-06
  Result (2026-10-31): ruff, black and mypy clean; 3371 collected, 4 skipped (POSIX modes and
  symbolic links on Windows), the rest passed; coverage 100%. The wheel declares no `Requires-Dist`
  (`uv build`). The documentation changes are the README pair (a `### Several domains` section
  under Configuration, the Quick start line, the HTML folder, the worst-answer paragraph under the
  exit codes, the envelope under JSON), `docs/stability.md`, the CHANGELOG, `CLAUDE.md` (the
  `ingest_many`, `load_configs` and `worst_answer` lines and the ⚠️ on the loop of one), `docs/stack.md`
  (the `idna` codec) and `specs/README.md`. `/preparar-release` for 1.6.0 stays a separate PR.
