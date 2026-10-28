---
feature: Reject verdict — "is this domain ready for p=reject?", with the criterion stated
status: in progress
date: 2026-10-28
related:
  - 005-reject-verdict/requirements.md
  - 005-reject-verdict/design.md
origin: conception
---

# 005 — Reject verdict — Tasks

Each stage is one pull request (issue → branch → PR); Claude opens it and never merges. Inside a
stage, tests come first: write the test that feeds the input, watch it fail for the right reason,
then write the code. `Summary` values are built in the test with a small builder that has defaults,
so each test states only what it changes; files are in `tmp_path`. Domains, services and addresses
are invented (`example.com`, `example.org`, `example.net`; `192.0.2.0/24`, `198.51.100.0/24`,
`203.0.113.0/24`, `2001:db8::/32`). No real report, address or domain enters a test, a doc or a
commit message (RNF-06).

The stages go from the ground up: the one rename in finished code (alone, behavior-neutral), then
the rules, then the text, then the command, then the close. `verdict.py` never imports a text
module (RNF-03).

## Stage 1 — Make the shared text helpers public (ADR-5)

- [x] `src/mailvigil/render.py`: rename `_fit`, `_address` and `_count` to `fit`, `address` and
  `count_noun`, with every call site; update their docstrings only where the name appears. No
  behavior change. — ADR-5
- [x] `tests/test_render.py`: follow the rename. The assertions stay as they are. — ADR-5
- [x] Quality gate (`uv run ruff check .`, `uv run black --check .`, `uv run mypy`,
  `uv run pytest --cov`). The 004 suite must pass untouched apart from the names. — result recorded
  when run: all green on 2026-10-28; 507 passed (the same as before, no
  new test), coverage 100% (Python 3.12). The rename had one trap: `_label` held a local named
  `address`, which would have shadowed the renamed function, so the local became `text`

## Stage 2 — The rules and the answer (RF-01 to RF-05, RF-07, RNF-02, RNF-03, RNF-04, RNF-05)

- [x] `tests/test_verdict.py`, written first, with a `Summary` builder (period, totals, senders,
  failing sources, policy, `earlier_p`) whose defaults are a clean, long, busy domain. Rules, each
  at the threshold and at the value beside it: 28 and 27 days spanned; 23 and 22 days with a report
  of 28; 1000 and 999 messages; 0 and 1 failing message under a recognized sender; unrecognized
  failures at exactly 0.5% of the total and just over, built with totals large enough for the
  arithmetic to be exact. — RF-02
- [x] Same file, the answers: a clean table with a short window is `TOO_EARLY`; a recognized failure
  with a short window is `NOT_READY` (not `TOO_EARLY`); every rule passing is `READY`; a failed rule
  of each kind together is `NOT_READY`; `deciding` is the first failed rule of the deciding kind and
  `None` for `READY`. — RF-01, ADR-2
- [x] Same file, empty input: a `Summary` with no reports is `TOO_EARLY` with rules 1 to 3 failed,
  rule 5 passing and no division by zero; reports present with zero messages is `TOO_EARLY`;
  `missing` is the days or messages short (rounding up for rule 2) and 0 for a problem rule.
  — RF-01, RF-02, ADR-4
- [x] Same file, the sources: `recognized_failing` and `unrecognized_failing` split `summary.failing`
  by outcome (`KNOWN` against the other three), keep its order, and are filled whatever the answer;
  a `KNOWN` source whose DKIM signature passed but was not aligned counts as recognized failing; the
  two failing counts add up to `totals.failing`. — RF-03, RF-02
- [x] Same file, the notes: fragile traffic gives `FRAGILE` with the numbers, `pct` below 100 gives
  `PARTIAL_POLICY`, a non-empty `earlier_p` gives `POLICY_CHANGED`, an `sp` or `np` different from
  `p` gives `SUBDOMAIN_POLICY` and `quarantine` gives `CURRENTLY_QUARANTINE`; each alone gives only
  its note, in `NoteKind` order when several apply, and none changes the answer. — RF-04
- [x] Same file, the policy: `enforcing` is lower case and trimmed (`" REJECT "` becomes `reject`),
  `?` and `none` give no note and the same answer as the same traffic under `reject`. — RF-05
- [x] Same file, the properties: the same `Summary` judged twice, and a `Summary` built from the same
  reports in two orders (through `summarize`), give equal verdicts; `Verdict`, `Rule` and `Note`
  raise `FrozenInstanceError` on assignment and expose only tuples; `mailvigil.verdict` imports no
  text module (`render*`). — RNF-02, RNF-03, RNF-04
- [x] `src/mailvigil/verdict.py`: `Answer`, `RuleKind`, `RuleId`, `Rule`, `NoteKind`, `Note`,
  `Verdict`, the four threshold constants with their units documented, and `judge` as in the design
  (integer arithmetic only). Docstrings with `Args:` / `Returns:`, full annotations. — RF-01 to
  RF-05, ADR-1 to ADR-4
- [x] Quality gate. — result recorded when run: all green on 2026-10-28; 59 new tests in
  `tests/test_verdict.py`, coverage 100% (Python 3.12). `judge` takes the recognized failing messages
  from the sum of the `KNOWN` entries of `summary.failing`, not from the `senders` rows: the two are
  equal by construction (004 RF-04) and this one needs no second table in a test `Summary`

## Stage 3 — The text (RF-03, RF-04, RF-05, RNF-05)

- [x] `tests/test_render_verdict.py`, written first, from built `Verdict` values. The title for each
  answer, and the reject wording under `p=reject` (`NO PROBLEM SEEN`, `BLOCKING REAL MAIL`); the
  words "safe" and "attack" never appear in any output of the module. — RF-03, RF-05
- [x] Same file, the reason: rule 4 names each recognized source with its failing messages, its IP
  and the override types, and more than 10 print 10 and a remainder line; rule 5 prints the share
  and the first 5 unrecognized sources, with `foreign domain (selector s)` and `failing signature
  (selector s)` labels, and a remainder line with the failing count of the others; `TOO_EARLY`
  names each failed data rule with what is missing (`need 1 more day`, `need 120 more messages`)
  and, with no reports, says that none was kept; `READY` prints `every rule passes`, and lists the
  first 5 unrecognized failing sources under the limit when there are any. — RF-03, ADR-3
- [x] Same file, the table and the rest: the five rules with id, name, measured, needed and result
  (`pass`, `FAIL`, `fail (too early)`); a share printed with `format_share` and beside its count
  (`27 of 28`); the notes only when present; the next step by `deciding` and absent for `READY`;
  the closing sentence always. — RF-03, RF-04
- [x] Same file, the layout: no line over 80 columns, also with a 100-character service name, an
  IPv6 address and a count of `10**12`; ASCII apart from names; a name wider than its column is
  cut with `...`; the output has no color and no control code. — 004 RF-09 applied here
- [x] Same file, the criterion cannot drift: monkeypatching each of the four constants changes the
  "needed" column and the explanation. — RNF-05
- [x] `src/mailvigil/render_verdict.py`: `render_verdict(verdict)` and its English text, using
  `fit`, `address`, `count_noun` and `format_share` from `render.py`. — RF-03 to RF-05, ADR-5
- [x] Quality gate. — result recorded when run: all green on 2026-10-28; 79 new tests in
  `tests/test_render_verdict.py` (645 in all), coverage 100% (Python 3.12). The "needed" column and
  the limit in the explanation are read from the `Rule` fields that `judge` builds from the four
  constants, not from the constants directly, so a hand-built `Verdict` renders what it says; the
  test moves each constant, judges again and reads the text. The measured column of rules 2 and 5
  carries the count and the share (`27 of 28 (96.4%)`, `12 (0.3%)`); a title too wide for one line
  puts the answer on a second line

## Stage 4 — The command (RF-06)

- [x] `tests/test_cli_verdict.py`, written first, through `main(argv)` and `capsys`, with synthetic
  reports in `tmp_path`: a long, clean, busy set gives `READY`, code 0; a clean set that is short
  gives `TOO_EARLY`, code 3; a set with a recognized failure gives `NOT_READY`, code 4, and the
  output names the source. — RF-06, ADR-6
- [x] Same file, the shared refusals: a refused configuration, a conflicting `--domain`, no domain
  at all and no kept report each print the same line as `summary` on standard error, nothing on
  standard output, and code 1; no path is a usage error, code 2, before any file is read; the
  codes are not documented as stable. — RF-06
- [x] Same file and `tests/test_cli_summary.py`: `mailvigil summary` prints the same output and
  returns the same codes as before (the existing tests pass untouched); `--help` lists both
  commands; `--version` still works. — RF-06
- [x] `src/mailvigil/cli.py`: a parent parser with `paths`, `--config` and `--domain`, passed to both
  subcommands; `_load(args)` extracted from `_run_summary`; `_run_verdict`; `EXIT_TOO_EARLY = 3` and
  `EXIT_NOT_READY = 4` with the comment that they are provisional until spec 006. — RF-06, ADR-6
- [x] Quality gate. — result recorded when run: all green on 2026-10-28; 13 new tests in
  `tests/test_cli_verdict.py`, coverage 100% (Python 3.12). `tests/test_cli_summary.py` passes
  untouched. A recognized failing source needs a passing `s1` signature with a failing DMARC
  evaluation (a failing signature is `FAILING_SIGNATURE`, not recognized), so the test builder
  signs correctly and fails SPF and the evaluation

## Stage 5 — Close the spec

- [ ] Validate the layout and the thresholds by hand on the maintainer's own reports (they never
  enter the repository). Record only what was learned and changed, in a sentence, without domains,
  addresses or counts that identify them. If a threshold is wrong, change the constant, its tests
  and the requirements' Resolved decision, tests first. — Risk 1, RF-02
- [x] Zero-dependency guard: `uv build`, then check the wheel metadata has no `Requires-Dist`, holds
  `verdict.py` and `render_verdict.py`, importable from the built wheel, and that
  `mailvigil verdict` runs from it on a synthetic report. — RNF-01
- [x] Run `/atualizar-docs`: the README gains the `mailvigil verdict` quick start with an invented
  example output and its status row, and keeps the exit codes as provisional; `CLAUDE.md`'s
  architecture block and status paragraph gain the two modules and the command; `docs/stack.md`
  gains `IntEnum`, integer comparison of thresholds and `argparse` parent parsers. — docs
- [ ] Mark the three files `done` and move the roadmap row of `005` in `specs/README.md` to `done`.
  — all
- [ ] Quality gate and CI. — result recorded when run: local gate green on 2026-10-28 (658 tests,
  coverage 100%, Python 3.12); the CI run URL goes here once the PR is open. The built wheel declares
  no `Requires-Dist`, holds both new modules, imports in a clean environment, and `mailvigil verdict`
  on 28 synthetic daily reports prints `READY` with code 0
