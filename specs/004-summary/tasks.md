---
feature: Summary — per sender and per situation, failures highlighted, and the first command
status: done
date: 2026-10-27
related:
  - 004-summary/requirements.md
  - 004-summary/design.md
origin: conception
---

# 004 — Summary — Tasks

Each stage is one pull request (issue → branch → PR); Claude opens it and never merges. Inside a
stage, tests come first: write the test that feeds the input, watch it fail for the right reason,
then write the code. Records, reports and configurations are built in the test with the dataclasses
(`Record`, `Report`, `Config`) and the files in `tmp_path`, from invented domains (`example.com`,
`example.org`, `example.net`), invented service names and the documentation address ranges
`192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24` and `2001:db8::/32` (RNF-07). No real report,
address or domain enters a test, a doc or a commit message.

The stages go from the ground up: the one change to finished code (`check_domain`, which touches
003 and so comes first and alone), then the computation in two parts, then the text, then the
command, then the close. The computation (`summary.py`) never imports `render` (RNF-03).

## Stage 1 — Share the domain rules (ADR-7)

- [x] `tests/test_config.py`, written first: `check_domain` returns `example.com` for
  `" Example.COM. "`; it refuses with the loader's reasons the same inputs the loader refuses
  (`INVALID_DOMAIN` for an integer, empty, `https://example.com`, `a..com`, `localhost`, a
  64-character label; `NON_ASCII_DOMAIN` for `exämple.com` and the Kelvin sign U+212A); the
  `ConfigError.key` is the `key` argument (`"--domain"`), cleaned like any key; the default key is
  `domain`. — RF-08
- [x] `src/mailvigil/config.py`: extract `check_domain(value: object, key: str = "domain") -> str`
  from `_read_domain`, which keeps the "missing" test and delegates. The 003 suite must pass
  **unchanged**; if one of its tests needs an edit, stop and ask. — ADR-7
- [x] Quality gate (`uv run ruff check .`, `uv run black --check .`, `uv run mypy`,
  `uv run pytest --cov`). — result recorded when run: all green on 2026-10-27; 340 passed (329
  before, 11 new), coverage 100% (Python 3.12)

## Stage 2 — Classify and add up the traffic (RF-01, RF-02, RF-04, RNF-03, RNF-04)

- [x] `tests/test_summary.py`, vocabulary first: `Situation` members are unique strings; `Counts`
  gives `fragile = dkim_only + spf_only` and `total = ok + fragile + failing`; every dataclass of
  the model raises `FrozenInstanceError` on assignment; every collection field is a tuple. — RNF-04
- [x] `src/mailvigil/summary.py`, part 1: `Situation`, `Counts`, `SenderRow`, `FailingSource` and
  the types that `Summary` will hold, with the docstrings of the design. `Summary` holds no string
  built for display; a test compares its field names and types with the design. — RNF-03, RNF-04
- [x] Tests for classification, written first: both `pass` is `ok`; only DKIM is `fragile` with
  `dkim_only`; only SPF is `fragile` with `spf_only`; neither, both empty and `error` are
  `failing`; `PASS`, ` pass ` and `Pass` count as pass; `disposition` and override reasons change
  nothing. — RF-01, Resolved decisions 1 and 13
- [x] `summary.py`, part 2: `classify(record)`. — RF-01
- [x] Tests for rows, written first, calling `summarize` with built `IngestionResult` and `Config`
  values: two selectors of one service share a row; one `KNOWN` service from two IPs is one row; one
  IP seen as `FOREIGN_DOMAIN` and as `UNKNOWN` is two rows and neither carries a service name; a
  non-`KNOWN` row lists its selectors sorted; a record with count zero adds nothing and makes no
  row; rows are ordered by total descending then label; the totals per situation and
  `recognized_messages` add up; the same reports in three orders give equal `Summary` values. —
  RF-01, RF-02, RNF-05
- [x] `summary.py`, part 3: `summarize`, the one pass of the design (row key, tallies, totals,
  sorting), with `period`, `policy`, `earlier_p`, `skipped` and the counts left at their empty
  values until Stage 3. — RF-02, ADR-1
- [x] Tests for failing sources, written first: a failing source appears once per IP, with its
  failing message count; a `KNOWN` service failing from two IPs gives two entries; `dkim` is
  `unaligned` when a block passed, `fail` when blocks exist and none passed, `none` when there is no
  block, and likewise `spf`; two records of one source with different reasons give both, sorted;
  override reason types are kept and the free-text comment is not; the order is messages descending
  then label, IP and outcome; a source with no failing message is not listed. — RF-04, ADR-2
- [x] `summary.py`, part 4: the failing-source accumulator and the per-mechanism reasons. — RF-04,
  ADR-2
- [x] Immutability and scale tests: 50,000 synthetic records over 200 sources give 200 rows and
  at most 200 failing entries, and the `Summary` holds no per-message structure (checked by its
  contents, not by timing). — RNF-04, RNF-09
- [x] Quality gate. — result recorded when run: all green on 2026-10-27; 382 passed (340 before,
  42 new), coverage 100% (Python 3.12)

## Stage 3 — Period, policy and what was left out (RF-03, RF-05)

- [x] Tests for the period, written first: from the earliest begin to the latest end; a report from
  midnight to the next midnight touches one day, and one ending at 23:59:59 the same; a report that
  crosses midnight touches two; a gap day lowers `days_with_reports` below `days_spanned`;
  overlapping reports are not counted twice; `last_day` is the last day touched, not the day of the
  latest `end` when that is a midnight; a zero-length period counts the day of `begin`; a report
  with a period of 500 years is summarized at once and shows the long span. — RF-03, ADR-3, RNF-09
- [x] `summary.py`: `Period` and the merged day intervals. — RF-03, ADR-3
- [x] Tests for the policy and the counts, written first: one policy gives `p`, `sp`, `np` and `pct`
  of the latest report; a changed `p` fills `earlier_p`, oldest first and without repeats, and the
  latest wins whatever the order of the input; the number of reports; two reporters with one
  repeated count as two, and an absent reporter (`?`) as one; no reports gives zero totals and a
  `None` period and policy. — RF-03
- [x] `summary.py`: `policy`, `earlier_p`, `reports`, `reporters`, `selectors_configured`, and the
  empty-input result. — RF-03
- [x] Tests for what was left out, written first: `duplicates` and `other_domain` copied from the
  `IngestionResult`, also at zero; `skipped` ordered by path whatever the input order;
  `skipped_by_reason` ordered by count descending then reason; the order does not change when the
  discovery order does. — RF-05, RNF-05
- [x] `summary.py`: the left-out fields. — RF-05
- [x] Quality gate. — result recorded when run: all green on 2026-10-27; 401 passed (382 before,
  19 new), coverage 100% (Python 3.12)

## Stage 4 — The text (RF-04, RF-05, RF-06, RF-09, RF-10, RNF-08)

- [x] `tests/test_render.py`, shares first: `format_share` gives `95.4%` for 11900 of 12480; `0%`
  for no part; `<0.1%` for 4 of 10000; `99.9%` for 9997 of 10000; `100%` only for the whole; `0%`
  when the whole is zero; the result does not depend on a float. — RF-06, ADR-5
- [x] `src/mailvigil/render.py`, part 1: `format_share`. — RF-06, ADR-5
- [x] Tests for the helpers, written first: `_fit` cuts to the width with `...` and leaves a short
  text alone; it removes an escape sequence, a line break and U+202E before cutting; a phrase exists
  for every `Reason` (the test iterates the enum); the label of a row is the service name or
  `IP (kind)` with the three kinds; an empty address reads as no address. — RF-05, RF-09, RNF-08
- [x] `render.py`, part 2: `_fit`, the reason phrases and the row labels. — RF-09, RNF-08
- [x] Tests for the header, the situations and the senders table, written first, on a built
  `Summary`: the sections come in order; the header shows config, period, reports, policy (with `sp`
  and `np` when present, and the earlier values when it changed) and messages with the recognized
  share; an empty map adds the note; a row with failing messages starts with `!`; every `KNOWN` row
  is shown and 12 unrecognized rows print 10 and one remainder line with its sources, messages and
  failing count; the numbers print as exact integers beside each percentage; plural and singular
  (`1 of 1 day`, `1 reporter`). — RF-03, RF-06, RF-09, Resolved decision 12
- [x] `render.py`, part 3: the header, the situations and the senders table, with the column widths
  taken from the data. — RF-03, RF-09, ADR-6
- [x] Tests for the failures and the left-out sections, written first: the title carries the failing
  messages and the number of sources; recognized sources come before unrecognized ones and an empty
  group is not printed; each source takes two lines with the IP, the messages, `dkim: …, spf: …` and
  the override types, several reasons joined with `/`; a foreign or failing-signature source names
  its selector; 12 sources in a group print 10 and a remainder with their failing messages; none
  prints `No failing messages.`; skipped files list 10 and a remainder, with counts per reason, and a
  name carrying an escape sequence is shown cleaned; duplicates and other domains print even at
  zero. — RF-04, RF-05, RNF-08
- [x] `render.py`, part 4: the failures and the left-out sections, and `render_summary`. — RF-04,
  RF-05, RF-09
- [x] Tests for the layout limits, written first: no line is over 80 columns with a 100-character
  service name, an IPv6 address, a count of `10**12` and 40 override types; the output is ASCII
  apart from names; the same `Summary` rendered twice is equal text. — RF-09, RNF-05, ADR-6
- [x] Tests for the empty-result message, written first: `no_reports_message` names the domain, the
  counts of skipped files per reason, the duplicates and the reports of other domains. — RF-10
- [x] `render.py`, part 5: `no_reports_message`. — RF-10
- [x] Quality gate. — result recorded when run: all green on 2026-10-27; 478 passed (401 before,
  77 new), coverage 100% (Python 3.12)

## Stage 5 — The command (RF-07, RF-08, RF-10, RNF-02, RNF-08)

- [x] `tests/test_cli_summary.py`, written first, through `main(argv)` and `capsys`, with reports
  written as synthetic files in `tmp_path` (the fixtures of `conftest.py`): a run with `--config`
  prints the summary, returns 0 and writes nothing to standard error; no path is a usage error
  with code 2 before any file is read; `--version` still prints the version; no command prints the
  help to standard error and returns 2. — RF-07, RF-10
- [x] `src/mailvigil/cli.py`: the `summary` subparser and the dispatch in `main`; update
  `tests/test_smoke.py::test_no_arguments_exits_zero` to the new behavior, the one test that changes
  on purpose. — RF-07
- [x] Tests for the configuration and the domain, written first: `--config` loads the file, and an
  explicit missing file is refused without trying `mailvigil.toml`; `mailvigil.toml` in the current
  folder (`monkeypatch.chdir`) is read and named in the header; a folder named `mailvigil.toml` is
  refused, not ignored; none gives `config  none` and an empty map; `--domain` alone works; the
  same domain in the flag and the file passes, a different one is refused naming both; an invalid
  `--domain` is refused with the loader's reason; neither source is refused with the hint to pass
  `--domain` or `--config`; a refused configuration names its path, cleaned. — RF-08, Resolved
  decisions 10 and 11
- [x] `cli.py`: `resolve_config` and the refusal lines. — RF-08, ADR-7
- [x] Tests for the exit codes, written first: a summary with failing traffic still returns 0; each
  refusal prints one line to standard error, nothing to standard output and returns 1, with no
  traceback; no kept report (nothing found, every file refused, all of another domain) prints the
  counts of what was skipped and filtered and returns 1; the command writes nothing under
  `tmp_path` besides the inputs. — RF-10, RNF-02
- [x] Tests for the encoding, written first: a service name with a character the stream cannot
  encode prints `?` and does not raise, on a stream built with `encoding="ascii"`; a stream with no
  `encoding` attribute falls back to UTF-8. — RNF-08, ADR-4
- [x] `cli.py`: `_write` and the exit-code mapping, and the wiring `ingest → summarize →
  render_summary`. — RF-10, ADR-4
- [x] Quality gate. — result recorded when run: all green on 2026-10-28; 505 passed (478 before, 27 new), coverage 100% (Python 3.12)

## Stage 6 — Close the spec

- [x] Hostile-input audit (RF-11): list the cases of the requirement and point each to its test;
  add whichever is missing. — RF-11. Result on 2026-10-28, all 14 cases already had a test, none
  added: zero messages (`test_a_record_with_no_messages_adds_nothing_and_makes_no_row`); empty and
  upper-case result (`test_a_record_is_ok_fragile_or_failing`, `test_pass_ignores_case_and_surrounding_spaces`);
  one IP under two kinds (`test_one_address_under_two_outcomes_is_two_rows_without_a_service`); two
  selectors of one service (`test_two_selectors_of_one_service_share_a_row`); more rows than the
  limit with a failing one among the small (`test_every_known_row_is_shown_and_twelve_other_rows_print_ten_and_a_remainder`);
  share under 0.1% (`test_a_tiny_failing_share_is_not_rounded_to_zero`); policy changed
  (`test_a_changed_policy_lists_the_earlier_values_oldest_first_without_repeats`); other order
  (`test_the_same_reports_in_any_order_give_an_equal_summary`); crosses midnight
  (`test_a_report_that_crosses_midnight_touches_two_days`); absurdly long period
  (`test_a_period_of_five_hundred_years_is_summarized_at_once`); name wider than its column
  (`test_a_known_row_name_wider_than_the_column_is_cut`) and one the stream cannot encode
  (`test_a_name_the_stream_cannot_encode_prints_a_question_mark`); conflicting domain
  (`test_a_different_domain_in_the_flag_is_refused_naming_both`); missing `--config`
  (`test_explicit_missing_config_is_refused_without_trying_the_default`); no reports kept
  (`test_every_file_refused_prints_the_skipped_counts`, `test_all_reports_of_another_domain_print_the_filtered_count`);
  escape sequence in a skipped name (`test_a_skipped_file_name_with_an_escape_sequence_is_shown_cleaned`)
- [x] Validate the layout by hand: run `mailvigil summary` against the maintainer's own reports
  (outside the repository, never committed or pasted into a spec, issue or PR) and record only
  whether the output reads well and what was changed in `render.py` as a result. — Risk 1 of the
  design. Done on 2026-10-28 with invented reports instead (the maintainer had lost the real ones):
  nine files outside the repository, with two reporters per format, a policy change, a gap day, a
  duplicate, a report of another domain, a malformed file, an unsafe one and 14 small sources.
  Three things read badly and were changed, tests first: (1) the label column was capped at 30, so
  `198.51.100.99 (failing signature)` lost its address; the cap is now 35, the longest IPv4 address
  with the longest kind; (2) every unrecognized failing source opened with the same line,
  `! unrecognized`, before the address; it now opens with the address and the second line starts at
  the messages (foreign domain and failing signature keep their kind line); (3) a folder holding
  files that do not follow the provider naming got "No .xml, .gz or .zip file was found", which
  was untrue; the message now says that a folder is searched only for `provider!domain!begin!end.zip`
  names and that a file named directly is read whatever its name. The requirements example and
  ADR-6 follow. Everything else read well
- [x] Zero-dependency guard: `uv build`, then check the wheel metadata has no `Requires-Dist` and
  holds `summary.py` and `render.py`, importable from the built wheel, and that
  `uv run mailvigil summary` runs from it. — RNF-01. Result on 2026-10-28: the wheel has no
  `Requires-Dist`, holds both modules, and `mailvigil summary` ran from it in an isolated
  environment (`uv run --isolated --no-project --with <wheel>`) on a synthetic report, exit 0
- [x] Run `/atualizar-docs` (done on 2026-10-28; the README also gained the folder naming rule): the README gains the `mailvigil summary` quick start with an invented
  example output, its "Summary" row, and keeps the exit codes as "not defined yet"; `CLAUDE.md`'s
  architecture block and status paragraph gain the two modules and the command; `docs/stack.md`
  gains the subcommands of `argparse`, `datetime` and interval merging, and integer rounding. —
  docs
- [x] Mark the three files `done` and move the roadmap row of `004` in `specs/README.md` to `done`.
  — all
- [x] Quality gate and CI. — result recorded when run: local gate all green on 2026-10-28; 507
  passed (505 before, 2 new), coverage 100% (Python 3.12), `uv lock --check` ok; the CI runs on
  the pull request
