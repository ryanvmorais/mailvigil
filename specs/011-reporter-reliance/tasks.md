---
feature: A note when the answer rests on one reporting organization
status: in progress
date: 2026-11-14
related:
  - 011-reporter-reliance/requirements.md
  - 011-reporter-reliance/design.md
origin: conception
---

# 011 — Reporter reliance — tasks

Each stage is one pull request (issue → branch → PR). Inside a stage, tests come first: write the
test that feeds the input, watch it fail for the right reason, then write the code. Every report,
organization and domain in a test is invented, and every address is in a documentation range
(RNF-06).

The stages go from the bottom up: the figures in the summary, which nothing reads yet; the check and
the note in the verdict; the text and the three outputs; then the documentation and the close. **The
rule of the whole spec is RF-04 and RNF-01:** an existing test changes only when it builds a `ready`
verdict that rests on one organization, and each one that changes is named in the result of its
stage; if any other one fails, the code is wrong. The release (a minor version) is the
maintainer's act and is prepared apart.

## Stage 0 — The spec (RF-01 to RF-04, RNF-01 to RNF-06)

- [x] `requirements.md` written and approved by the maintainer (2026-11-14).
- [x] `design.md` written and approved by the maintainer (2026-11-14).
- [x] `tasks.md` approved (2026-11-14); `specs/README.md` gains row 011 at `approved`, with no
  delivery yet. The three files go in one documentation PR, without code, so the quality gate does
  not apply to this stage.

## Stage 1 — The measures without each organization (RF-01, RNF-02, ADR-2, ADR-3)

- [x] Measure once, before any change: the time of `summarize` on a synthetic run of ten thousand
  reports, each from its own organization, built by a throwaway script outside the repository.
  Record it in the result of this stage. — RNF-02
  Result (2026-11-14): 224 ms (median of seven runs; 206 ms the fastest), three records per
  report.
- [x] `tests/test_summary.py`, written first: an oracle helper that runs `summarize` on the result
  without one organization's reports and reads the five measures from it (days spanned, days with a
  report, messages, recognized and unrecognized failing messages); `Summary.without_reporter` must
  equal it, entry by entry and in the order of `reporter_activity`, on a table of report sets: one
  organization; two that overlap; two that alternate days; a day covered half by each; periods that
  touch at midnight; a zero-length report; records with `count` 0; failures under a known sender and
  under an unknown one. A run with no reports has no entry. — RF-01, ADR-2
- [x] `tests/test_summary.py`: hand-built edges of the sweep, with the expected days written out: an
  organization whose exclusive time is whole days in the middle of the period; one whose exclusive
  time is a few hours at each end of a day the others cover partly; one that covers nothing alone;
  one that sets the earliest `begin`, and one that sets the last day touched. — ADR-3
- [x] `src/mailvigil/summary.py`: `WithoutReporter` and `Summary.without_reporter` (internal, with
  its docstring entry); in the loop of `summarize`, the three `Counter[str]` keyed by the reporter
  (messages, failing under `Outcome.KNOWN`, all failing) and, per organization, the earliest `begin`,
  the last day touched and its periods. — RF-01, ADR-2
- [x] `src/mailvigil/summary.py`: split `_covered` so that its per-day seconds are readable, with
  the merged intervals it returns today unchanged; then `_without_reporter()`: the two sorted bounds
  for the period, the sweep for the exclusive time (only the first and the last day of a stretch
  visited; the whole days between counted), and the subtraction from the totals. — ADR-3
- [x] `tests/test_render_json.py` and `tests/test_cli_json.py`: no `--json` document carries the new
  field (the existing goldens stay byte for byte). — RNF-01
- [x] `tests/test_summary.py`: the run of ten thousand organizations gives ten thousand entries.
  Measure the time of `summarize` again on the same throwaway run, and record both timings. — RNF-02
  Result (2026-11-14): 224 ms before, 332 ms after (medians of seven runs on one machine; the
  fastest were 206 ms and 295 ms). The work added is a sort and one sweep over the
  reports, so it grows with the reports and the organizations, not with their product.
- [x] Quality gate of the stage: `uv run ruff check .` → `uv run black --check .` → `uv run mypy` →
  `uv run pytest --cov`. Record the result here, with the number of tests and the coverage. — RNF-06
  Result (2026-11-14): ruff, black and mypy clean; 3672 passed, 7 skipped (POSIX modes and
  symbolic links on Windows); coverage 100%. Besides the table of report sets, 200 seeded random
  runs (periods on the hour, overlapping and touching, up to four organizations) must also equal
  the oracle. `_covered` now takes the merged periods and also returns the per-day seconds, so
  `summarize` merges once for the coverage and the sweep. The existing tests that changed are
  the three that list the parts of the model in `tests/test_summary.py`:
  `test_every_part_of_the_model_is_frozen`,
  `test_summary_has_the_fields_of_the_design_and_no_display_text` and
  `test_every_collection_of_a_summary_is_a_tuple` each gained the new field or type; no other
  test changed.

## Stage 2 — The check and the note (RF-01, RF-02, RF-04, RNF-03, ADR-1, ADR-4, ADR-5)

- [ ] `tests/test_verdict.py`, written first: a `ready` summary where the answer rests on one
  organization through each rule that can turn it (period, coverage, volume, the unrecognized
  share), each giving the note with its numbers (its messages, all messages, organizations, the rule
  id) and texts (its name, `too_early` or `not_ready`); a test that rule 4 cannot turn a `ready`; the
  largest organization named when two qualify, and the name deciding a tie; one organization alone;
  no note when the answer rests on none; no note on `too_early` and `not_ready`. — RF-01, RF-02,
  ADR-4
- [ ] `tests/test_verdict.py`: the answer, the deciding rule, the five rules, the failing sources
  and `left_out` are equal to a verdict built with `without_reporter` emptied; a threshold of
  `verdict.py` patched in the test (`monkeypatch`) makes the note appear or go. — RF-04, RNF-03
- [ ] `src/mailvigil/verdict.py`: `_answer(rules)` taken out of `judge`, which calls it as before;
  `NoteKind.REPORTER_RELIANCE` after `SILENT_REPORTER`, documented on the kind; `_notes` receives the
  answer of the run and, on `READY`, walks `summary.without_reporter` with `_rules` and `_answer` and
  stops at the first entry that is not `READY`. — RF-01, RF-02, ADR-1, ADR-4, ADR-5
- [ ] Quality gate of the stage (as above), with the real result recorded. A test that now fails
  because it builds a `ready` verdict resting on one organization is updated in this stage only if
  it compares the notes of the verdict; every one is named here. — RF-04, RNF-01

## Stage 3 — The text and the outputs (RF-02, RF-03, RNF-01, RNF-05)

- [ ] `tests/test_render_verdict.py` and `tests/test_messages.py`, written first: both sentences in
  both languages, as in the table of the design; `{words}` from `words` and from `words_enforcing`
  (a domain already at `p=reject`); a long name cut by `fit`; the Portuguese folded to ASCII on a
  stream without accents (`tests/test_messages_fold.py`); every `NoteKind` has its sentence. — RF-02
- [ ] `src/mailvigil/messages/model.py` (`reliance_alone`), `messages/en.py` and `messages/pt_br.py`
  (the two sentences), `src/mailvigil/render_verdict.py` (`_reliance` in the table of note texts).
  — RF-02
- [ ] `tests/test_cli_verdict.py`, `tests/test_cli_json.py`, `tests/test_cli_html.py` and the files
  for several domains (`tests/test_render_json_domains.py`, `tests/test_cli_html_domains.py`): the
  note in text, in `--json` (`kind` `reporter_reliance`) and in the notes card of `--html`, for one
  domain and for several, where each domain gets its own note or none; the exit codes are the same
  as without the note. — RF-03, RF-04
- [ ] `tests/test_render_html_hostile.py`: an organization name with markup and control characters
  reaches the note cleaned in text and escaped on the page. — RNF-05
- [ ] `docs/json-schema.md`: the kind in the `note` table with its numbers and texts, the rule that
  a consumer must accept a note `kind` it does not know, and an example built by the code;
  `tests/test_json_schema_doc.py` sees the new kind. — RNF-01, ADR-5
- [ ] The goldens that carry a `ready` run resting on one organization
  (`tests/render_verdict_golden.py` and any other the gate names) are regenerated from the live
  output and the change is read line by line: only the note line is new. — RNF-01
- [ ] Quality gate of the stage (as above), with the real result recorded and every changed
  existing test named. — RNF-01, RNF-06

## Stage 4 — Documentation and close (RNF-01, RNF-04)

- [ ] `README.md` and `README.pt-BR.md` (the headings stay in step; `tests/test_readme_pt_br.py`):
  the "It trusts the numbers in the reports" limit says that the verdict notes when a `ready` rests
  on one organization; the list of notes, if the README has one, gains the new note. — RF-02
- [ ] The README demo: run `docs/demo/build_demo.py` and rebuild `docs/demo/verdict.cast` and its
  picture with the commands in its docstring, adjusting the height if the note adds a line; read the
  new frames; the alt text stays true. — RF-03
- [ ] `docs/stability.md` (the JSON row: a new note kind is a minor change), `CHANGELOG.md` (under
  `[Unreleased]`: Added), `specs/README.md` (011 `done`, the next milestone in the delivery column).
  `CLAUDE.md` and `docs/stack.md` change only if a line of theirs is no longer true. — RNF-01
- [ ] A last compatibility pass: the full suite; the wheel declares no `Requires-Dist` (`uv build`
  and the `package` check); `status: done` in the three files. — RNF-01, RNF-04
- [ ] Quality gate of the stage (as above), the real result recorded; then the preparation of the
  minor version as a separate PR (publishing is the maintainer's). — RNF-06
