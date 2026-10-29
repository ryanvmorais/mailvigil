---
feature: Reject verdict — "is this domain ready for p=reject?", with the criterion stated
status: done
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

## Stage 5 — The two output gaps found by hand (RF-08, RF-09; issue #28)

Found by running the command on synthetic reports outside the repository. Tests first, as in the
other stages; the rules, the thresholds and the exit codes do not change.

- [x] `tests/test_render.py`: `share_tenths` returns the tenths of a percent, round half up, for no
  part, no whole, a part equal to the whole and a small part; `format_share` prints exactly what it
  printed before for the same inputs (the existing assertions pass untouched). — ADR-8
- [x] `tests/test_render_verdict.py`, written first, from built `Verdict` values. RF-08: rule 5 at
  151 and 160 of 30000 (both round to 0.5%) print `>0.5%` in the table and in the reason, 150 of
  30000 (passes) prints `0.5%`, and 170 of 30000 (rounds to 0.6%) prints `0.6%`; a rule 2 failure
  that rounds to 80.0% prints `<80%`; the counts stay beside the share; a hand-built `Rule` with
  `passed=False` and a share clearly over its limit prints as before. — RF-08, ADR-8
- [x] Same file, RF-09: no line when `left_out` is empty and the output is identical to the stage 3
  expectations; the line with each count alone and together, omitting the parts at zero, with
  singular and plural; no file name; at most 80 columns also with `10**12` counts; the line sits
  between the next step and the caveat, and also appears for `READY`. — RF-09, ADR-9
- [x] `tests/test_verdict.py`: `judge` copies `skipped`, `duplicates` and `other_domain` from the
  `Summary` into `Verdict.left_out`, whatever the answer; the answer and the rules are equal with and
  without them; `LeftOut` is frozen and `Verdict.left_out` defaults to all zero. — RF-09, ADR-9
- [x] `tests/test_cli_verdict.py`: with one good report plus a malformed file, a duplicate and a
  report of another domain, `verdict` prints the line with `1 file skipped, 1 duplicate, 1 report of
  another domain` (the exact words are fixed in the test), the answer and the code are those of the
  good reports alone; without them the output has no such line. — RF-09
- [x] `src/mailvigil/render.py`: `share_tenths`, and `format_share` calls it; no change of output.
  — ADR-8
- [x] `src/mailvigil/verdict.py`: `LeftOut`, `Verdict.left_out` with a default, filled by `judge`.
  — RF-09, ADR-9
- [x] `src/mailvigil/render_verdict.py`: the beyond-the-limit form for a failed share equal to its
  limit, in `_measured` and in the reason of rule 5, decided by `Rule.passed` and `share_tenths`;
  the left-out sentence. — RF-08, RF-09
- [x] Quality gate (`uv run ruff check .`, `uv run black --check .`, `uv run mypy`,
  `uv run pytest --cov`); then run `mailvigil verdict` by hand on synthetic reports outside the
  repository for the 151-of-30000 case and for a skipped file, and delete them. — result recorded
  when run: all green on 2026-10-28; 46 new tests (704 in all), coverage 100% (Python 3.12). By hand,
  on synthetic reports outside the repository (deleted afterwards): 151 failing of 30001 messages
  prints `151 (>0.5%)` beside `<= 0.5%  FAIL`, and a malformed file adds the line `Left out of this
  verdict: 1 file skipped.` with the answer and the code unchanged

## Stage 6 — Close the spec

- [x] Validate the layout and the thresholds by hand on the maintainer's own reports (they never
  enter the repository). Record only what was learned and changed, in a sentence, without domains,
  addresses or counts that identify them. If a threshold is wrong, change the constant, its tests
  and the requirements' Resolved decision, tests first. — Risk 1, RF-02 — result recorded when run
  (2026-10-28): the maintainer had no real report at hand, so this ran on 12 synthetic sets outside
  the repository (deleted afterwards): clean, short, recognized and unrecognized failures, the 0.5%
  edge, 28 days and 1000 messages on both sides, already at `p=reject`, `quarantine` with `pct` and
  `sp`, IPv6, a 100-character service name, mixed `.xml`/`.gz`/`.zip`, and skipped, duplicate and
  other-domain files. Answers, codes and the 80-column limit held and nothing needed a change. The
  thresholds were **not** checked against real traffic: revisit them on the first real set
- [x] Zero-dependency guard: `uv build`, then check the wheel metadata has no `Requires-Dist`, holds
  `verdict.py` and `render_verdict.py`, importable from the built wheel, and that
  `mailvigil verdict` runs from it on a synthetic report. — RNF-01
- [x] Run `/atualizar-docs`: the README gains the `mailvigil verdict` quick start with an invented
  example output and its status row, and keeps the exit codes as provisional; `CLAUDE.md`'s
  architecture block and status paragraph gain the two modules and the command; `docs/stack.md`
  gains `IntEnum`, integer comparison of thresholds and `argparse` parent parsers. — docs
- [x] Mark the three files `done` and move the roadmap row of `005` in `specs/README.md` to `done`.
  — all
- [ ] Quality gate and CI. — result recorded when run: local gate green on 2026-10-28 (704 tests,
  coverage 100%, Python 3.12); the CI run URL goes here once the PR is open. The built wheel declares
  no `Requires-Dist`, holds both new modules, imports in a clean environment, and `mailvigil verdict`
  on 28 synthetic daily reports prints `READY` with code 0

## Stage 9 — A note for old data

- [x] `verdict.py`: `STALE_AFTER`, `NoteKind.STALE` and the optional `now` of `judge`; texts in both
  languages, `render_verdict.py`, `docs/json-schema.md`. The CLI reads the clock in one function
  (`cli._now`) and the tests pin it. — RF-04
- [x] Quality gate. — result recorded when run: ruff, black and mypy clean; pytest passed with
  coverage 100% (Python 3.12, 2026-10-29).
