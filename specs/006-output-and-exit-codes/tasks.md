---
feature: Output and exit codes — `--json`, the stable exit-code contract and the Portuguese text
status: in progress
date: 2026-10-28
related:
  - 006-output-and-exit-codes/requirements.md
  - 006-output-and-exit-codes/design.md
origin: conception
---

# 006 — Output and exit codes — Tasks

Each stage is one pull request (issue → branch → PR); Claude opens it and never merges. Inside a
stage, tests come first: write the test that feeds the input, watch it fail for the right reason,
then write the code. Values are built in the test with a small builder that has defaults (the
`make_summary` of `tests/test_verdict.py` is the model), so each test states only what it changes;
files are in `tmp_path`. Domains, services and addresses are invented (`example.com`,
`example.org`, `example.net`; `192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24`, `2001:db8::/32`).
No real report, address or domain enters a test, a doc or a commit message (RNF-06).

The stages go from the contract down to the words: first what a script can rely on (exit codes and
`--json`), then the behavior-neutral move of the English text into a catalog, then the Portuguese,
then the close. The 004 and 005 test files are never edited in this spec: if one fails, the code is
wrong (RNF-02). Per Resolved decision 6, if stage 3 outgrows this spec it becomes
`007-portuguese-text` and stages 1 and 2 close this one.

## Stage 1 — The contract: exit codes and `--json` (RF-01 to RF-05, RNF-01 to RNF-04)

- [x] `tests/test_render_json.py`, written first, with builders for `Summary` and `Verdict`. The
  summary document: the keys and their order; `schema_version` `1`, `command`, `domain` first;
  `period` and `policy` `null` without reports; `sp` and `np` `null` when empty; `config.source`
  `null` without a file; more senders and failing sources than the text limits (10 and 5) are all
  there; `skipped` carries the file name without its folder and no `detail`; `counts` has
  `ok`, `dkim_only`, `spf_only`, `failing` and `total`. — RF-02, RF-03
- [x] Same file, the verdict document: `answer`, `enforcing` (`null` without reports), `deciding`
  (`null` exactly when `ready`); five rules in order with the id words and the unit of each
  (`days`, `percent_of_days`, `messages`, `messages`, `per_mille_of_messages`) and `comparison`;
  a test iterating `RuleId` so a sixth rule cannot lack a word; both source lists complete; notes as
  `{kind, numbers, texts}`; `left_out`. The answer is the same under `reject` and under `none`.
  — RF-02, RF-04
- [x] Same file, the properties: two builds of the same input are byte-equal through `dumps`; the
  same reports through `summarize` in two orders give equal documents; a service name with a quote,
  a backslash, a control character and a non-ASCII letter round-trips through `json.loads` to the
  sanitized value and the output is ASCII; `dumps` has no trailing newline. — RF-01, RF-07
- [x] `src/mailvigil/render_json.py`: `summary_document`, `verdict_document` and `dumps`, with the
  small helpers of the design (`_counts`, `_sender`, `_source`, `_rule`, `_note`, `_period`,
  `_policy`, `_or_none`) and the two `RuleId` mappings. Frozen values in, `dict` out; nothing
  computed. Docstrings with `Args:` / `Returns:`; no import of `render` or `render_verdict`.
  — RF-02, RNF-03, RNF-04, ADR-2
- [x] `tests/test_cli_json.py`, written first, through `main(argv)` and `capsys` on synthetic files
  in `tmp_path`: `summary --json` and `verdict --json` print exactly one document and a newline,
  standard error empty; the document parses and has the right `command`; `--json` on a refusal
  (bad config, no domain, no report kept) leaves standard output empty, prints the same line as
  without `--json` and returns `1`; a `too early` and a `not ready` verdict print the full document
  and return `3` and `4`. — RF-01, RF-05
- [x] `src/mailvigil/cli.py`: `--json` (`store_true`) in the shared parent parser; the two
  `_run_*` functions end in the one branch of the design; the exit code is computed before the
  format. — RF-01, RF-04, RF-05
- [x] `tests/test_cli_exit_codes.py`, written first: one test per row of the table, each feeding the
  input that makes it and asserting the code (`0` summary printed, `0` ready, `1` refused config,
  `1` no report kept, `2` unknown option, `3` too early, `4` not ready); the enforcing forms return
  `4` and `0` (policy `reject`); every case with and without `--json` returns the same code; the
  constants in `cli.py` equal the table; the README's code table equals the constants (the test
  reads the table from `README.md`). — RF-04, RNF-02
- [x] `src/mailvigil/cli.py`: remove "provisional" from the comments and the `verdict` help; the
  constants are the one table. `README.md`: the exit-code paragraph becomes a table (the same five
  rows) with a three-line shell example that tells `1` from `4`, and the `--json` flag is
  documented; the roadmap row says so. `specs/004-summary` and `specs/005-reject-verdict`: no edit
  (finished specs); the README of `specs/` records the change. — RF-04
- [x] `docs/json-schema.md`: every field of both documents with its type and meaning, the
  compatibility promise (a field is added only inside a `schema_version`; renamed, removed or
  retyped only with a new one), the exit-code table and one example per command with invented data,
  in `json` code blocks. — RF-03
- [x] `tests/test_json_schema_doc.py`, written first: the examples are extracted from the page,
  rebuilt from the same input and compared with the real output field by field; the set of keys at
  every level equals the documented list, so an undocumented key fails the test. — RF-03
- [x] Quality gate (`uv run ruff check .`, `uv run black --check .`, `uv run mypy`,
  `uv run pytest --cov`). The 004 and 005 suites must pass untouched. — ruff, black and mypy clean; `pytest --cov` 772 passed, 100% coverage (2026-10-28).

## Stage 2 — The English text moves into a catalog (RF-06, RNF-02, RNF-05, ADR-3, ADR-4)

Behavior-neutral: the output is byte-equal to today's. No Portuguese is written in this stage.

- [x] Inventory (a list in the pull request description, not a file): every literal that reaches a
  reader in `render.py`, `render_verdict.py`, `no_reports_message` and the refusal lines of
  `cli.py`, grouped by area (`common`, `summary`, `verdict`, `refusals`). Everything dynamic
  (domain, service, address, selector) stays outside the templates. — RF-06
  Done: `messages/model.py` documents each field and the list is in the pull request description.
- [x] `tests/test_messages.py`, written first: `ENGLISH` is a `Messages`; every enum-keyed mapping
  (`Answer`, `RuleId`, `NoteKind`, `Outcome`, `Reason`, `ConfigReason`) covers its enum; no template
  is empty; every template formats with the placeholders its field declares and no others;
  `Plural.of` gives the singular for 1 and the plural for 0 and for 2; `language_by_code` accepts
  `en` in any case and rejects anything else. — RF-06, RF-07
  — plus the English configuration line equal to `str(error)` for every `ConfigReason`.
- [x] `src/mailvigil/messages/`: `model.py` (`Plural`, the nested frozen dataclasses), `en.py`
  (`ENGLISH`, the inventory moved verbatim), `__init__.py` (re-exports and `language_by_code`).
  Nothing imports a renderer. — ADR-3
  — the sentence labels `Why:` and `Next:` are catalog fields of their own (`why_label`,
  `next_label`), so the hanging indent of a wrapped sentence is `len(label) + 1` and not a typed 5
  and 6.
- [x] `src/mailvigil/render.py`: `render_summary`, `no_reports_message` and the private helpers take
  a last parameter `messages: Messages = ENGLISH` and read every sentence from it; `count_noun` goes
  through `Plural`; widths counted from an English prefix (`_WIDTH - 22`, `_WIDTH - 30`) are computed
  from the template. The 004 tests pass untouched. — RF-06, ADR-4
  — `count_noun` is removed instead of kept (nothing used it once the phrases went through
  `Plural`); `_REASON_PHRASES` stays as an alias of the English reasons because the 004 tests import
  it.
- [x] `src/mailvigil/render_verdict.py`: the same for `render_verdict`; the thresholds and limits in
  the sentences are passed as template values from the constants, never typed (RNF-05). The 005
  tests pass untouched. — RF-06, RNF-05
- [x] `src/mailvigil/cli.py`: the refusal lines come from the catalog; the configuration refusal in
  English stays `str(error)` (ADR-5). The CLI tests pass untouched. — RF-06, ADR-5
  — done without a language check: the English `config_reasons` are 003's own reason words and
  `config_detail` lists every reason, so the one builder gives `str(error)` in English and a
  Portuguese catalog only has to fill other values.
- [x] Quality gate. The suites of 002 to 005 and of stage 1 pass with no edit and the same count
  plus the new catalog tests. — ruff, black and mypy clean; `pytest --cov` 849 passed, 100% coverage
  (2026-10-28); no existing test file was edited.

## Stage 3 — Portuguese and `--lang` (RF-06, RF-07, ADR-5, ADR-6)

- [ ] `tests/test_messages.py`, written first, for `PORTUGUESE`: it has the same fields and the same
  placeholders per field as `ENGLISH`; every template and every mapping value encodes to ASCII;
  every enum-keyed mapping covers its enum; no template equals its English twin except the ones
  that are the same in both (`p=reject`, `DKIM`, `SPF`), listed in the test. — RF-06
- [ ] `src/mailvigil/messages/pt_br.py`: `PORTUGUESE`, ASCII only. Plain, short sentences; the same
  structure as the English ones; the words "seguro" and "ataque" are not used (the verdict reads
  reports, it does not certify a domain). Phrases that agree with the count are `Plural` of the
  whole phrase. — RF-06, Resolved decision 4
- [ ] `tests/test_render_pt.py`, written first, through the renderers with `PORTUGUESE`: the title,
  the answer word and the section order for each of the three answers and for the enforcing forms;
  the same numbers as the English text on the same input; every line within 80 columns and ASCII on
  the stress inputs the English tests use (long domain, long service name, many sources, extreme
  counts, skipped files of every reason); the closing sentence, the left-out line and the
  no-reports message. — RF-06, RF-07
- [ ] `tests/test_cli_lang.py`, written first: `--lang pt-BR` and `--lang pt-br` print the
  Portuguese text for `summary` and `verdict`; `--lang en` equals no `--lang`; `--lang fr` is a
  usage error (`2`); `--lang pt-BR --json` prints the same document as `--json`; every combination
  of `--json` and `--lang` returns the same exit code for the same input; a refusal under
  `--lang pt-BR` is a Portuguese line on standard error with standard output empty, and a
  configuration refusal is the phrase for its reason plus `[key]`, with the detail kept for
  `MALFORMED_TOML` and `UNKNOWN_KEY` only. — RF-04, RF-05, RF-06, ADR-5, ADR-6
- [ ] `src/mailvigil/cli.py`: `--lang` in the shared parent parser, case-insensitive, with the two
  codes as the only values; the chosen `Messages` goes to the renderers and to the refusal lines.
  `--help` stays in English (Risk 4). — RF-06
- [ ] Quality gate. — result recorded when run: ___

## Stage 4 — Validation and close (RF-07, RNF-06)

- [ ] Run both commands in both formats and both languages on invented report sets of the four
  kinds the 005 close used (a clean long set, a short set, a recognized failure, many unrecognized
  failures) and read the output: the Portuguese reads naturally, nothing overflows, the JSON is
  readable with `python -m json.tool`, the codes are the ones in the table. Record what was found
  and fix it in this stage. Real reports are never used or committed. — RF-06, RNF-06
- [ ] Run `/atualizar-docs`: `README.md` (flags, the Portuguese quick start with an invented
  example, the roadmap and status rows, "provisional" gone), `CLAUDE.md` (architecture block gains
  `render_json.py` and `messages/`; the language line is rewritten for `--lang`; the status
  paragraph loses "`--json` and the stable exit codes are not built yet"), `docs/stack.md` (the
  `json` module and the catalog pattern); then `/fechar-sessao`. — Resolved decision 2
- [ ] Mark the three files `done` and move the roadmap row of `006` in `specs/README.md` to `done`,
  with the note that "Exit codes and `--json` are public contract" now applies.
- [ ] Quality gate. — result recorded when run: ___
