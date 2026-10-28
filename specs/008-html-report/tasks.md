---
feature: HTML report — one static file with the summary and the verdict
status: in progress
date: 2026-10-28
related:
  - 008-html-report/requirements.md
  - 008-html-report/design.md
origin: conception
---

# 008 — HTML report — Tasks

Each stage is one pull request (issue → branch → PR); Claude opens it and never merges. Inside a
stage, tests come first: write the test, watch it fail for the right reason, then write the code.
`Summary` and `Verdict` values are built in the test (the `Summary` through `summarize` over
synthetic reports where the day matters). Domains, selectors and addresses are invented
(`example.com`, `example.net`; `192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24`, `2001:db8::/32`).
No real report, address or domain enters a test, a doc or a commit message (RNF-07).

The stages go from the bottom up, and the first two change nothing a user sees: first the shared
sentences become public with the text output pinned (ADR-2); then the `Summary` learns the days
(ADR-3); then the one module that builds markup and the palette (ADR-1, ADR-8, ADR-10); then the
catalog and the charts; then the renderer and the flag; then the close. The existing tests of 002
to 007 are only edited where the design says a signature or a name changed (the seven helpers of
`render_verdict.py`); if any other one fails, the code is wrong (RNF-05).

The interface was approved as a mockup on 2026-10-28 (design, "Interface record": board B for the
rules, C for the bar, T1 for the timeline). The renderer follows it; a deviation is shown to the
maintainer, not decided here.

## Stage 1 — The shared sentences become public (ADR-2, RNF-05)

- [x] `tests/test_render_verdict.py`, written first and green on the current code: the text of
  `render_verdict` for fixed verdicts, in English and in `pt-BR`, is pinned as exact strings: ready
  (with and without a still-failing unrecognized source), too early (no report kept, and with
  missing days and messages), not ready by recognized failures (one service, several services,
  more than the limit), not ready by unrecognized failures (the share that rounds to its limit),
  every `NoteKind` at least once, and what was left out. This is the guard of the refactor: it
  must pass before and after. — RNF-05, ADR-2
- [x] `tests/test_render_verdict.py`, the new public names, first: `reason_sentence` for each of
  the five cases (ready, too early, no report kept, recognized, unrecognized) returns the sentence
  without its label; `next_sentence` is empty for `READY` and one sentence otherwise;
  `measured_text`, `needed_text` and `missing_text` for each rule; `note_sentence` for every
  `NoteKind` (the test iterates the enum, so a kind added later cannot reach the page as a bare
  key). — RF-02, ADR-2
- [x] `src/mailvigil/render_verdict.py`: `reason_sentence`, `next_sentence`, `measured_text`,
  `needed_text`, `missing_text` and `note_sentence` lose their underscore (or are extracted from
  `_why`, `_next_step`, `_measured`, `_needed`, `_missing` and the note functions); `_why` and
  `_next_step` are rewritten on top of them, so the two renderers cannot drift. No text changes.
  Docstrings with `Args:` / `Returns:`. — ADR-2
- [x] Quality gate of the stage: `uv run ruff check .` → `uv run black --check .` → `uv run mypy` →
  `uv run pytest --cov`. Record the result here, with the number of tests and the coverage.
  **Result:** ruff, black, mypy strict clean; 1220 tests pass, coverage 100%. The text of 13
  fixed verdicts in both languages is pinned in `tests/render_verdict_golden.py` (recorded before
  the refactor, green after it, byte for byte).

## Stage 2 — The `Summary` learns the days (RF-04, RF-08, ADR-3)

- [ ] `tests/test_summary.py`, written first: `Summary.days` has one entry per UTC day on which a
  report begins, sorted, each with the reports that begin that day and their messages per
  situation; `sum(day.counts) == totals` and `sum(day.reports) == reports` for a month of daily
  reports, for a report from midnight to midnight, for one that crosses midnight (all its messages
  on the first day), for one of zero length and for two reports on one day; `covered` is the list
  of merged `[first, last]` intervals and its total length equals `period.days_with_reports`; a
  report spanning three days gives one `DayCounts` and one interval of three days; a report that
  spans centuries gives one entry and one interval (the size follows the reports, never the
  period); no reports gives empty tuples; a `Summary` built the old way has `days == ()` and
  `covered == ()`. — RF-04, ADR-3
- [ ] `tests/test_render_json.py`, first: `summary_document` of a summary with days equals the one
  of the same summary without them, byte for byte after `dumps`; the verdict document is
  unchanged. — RF-08, RNF-05
- [ ] `src/mailvigil/summary.py`: `DayCounts`; `Summary.days` and `Summary.covered`, defaulted;
  the merge of intervals that `_period` does becomes one helper both use, so rule 2 and the
  timeline read the same list; the tally by begin day in the existing loop over reports (no second
  pass over the records). Docstrings. — RF-04, ADR-3
- [ ] Quality gate of the stage (same four commands). **Result:** _to fill in when the stage
  runs._

## Stage 3 — The one module that builds markup, and the palette (RF-06, RF-07, ADR-1, ADR-7, ADR-8, ADR-10, RNF-01, RNF-02)

- [ ] `tests/test_htmlkit.py`, written first: `text()` escapes `<`, `>`, `&`, `"` and `'`;
  `el()` escapes attribute values, refuses a tag or an attribute name outside the allowlist
  (`script`, `iframe`, `object`, `embed`, `form`, `link`, `base`, `meta` outside the head helper,
  any `on…` attribute, `href` and `src` other than `#…`), and builds void and non-void elements
  correctly; `finish()` returns ASCII only, turns `é` into `&#233;` and an astral character into
  one reference, and a lone surrogate does not raise; `mypy` on a snippet that passes a `str` where
  a `Safe` is expected reports an error (run through `mypy.api` in the test). — RF-06, ADR-1,
  ADR-7
- [ ] `tests/test_htmlkit.py`, the source guards: an AST scan of `htmlkit.py`, `html_style.py`,
  `html_charts.py` and `render_html.py` finds every call to `raw(` and each argument is a string
  literal or an upper-case module constant; no module other than `htmlkit.py` imports `html` or
  calls `escape`; no module builds a tag with an f-string. — RF-06, ADR-1
- [ ] `tests/test_html_style.py`, first: every text and background pair of the palette (light and
  dark) is at least 4.5:1 and every graphic that carries meaning (the four segments, the limit
  tick, the failing marker, the gap outline) is at least 3:1 against its surface, computed with the
  WCAG formula; the stylesheet has the `prefers-color-scheme: dark` block and a print block, and
  no `url(`, `@import` or `expression(`; the CSP constant is exactly the string of ADR-8 and has no
  `img-src`. — RF-06, RF-07, ADR-8, ADR-10
- [ ] `src/mailvigil/htmlkit.py`: `Safe`, `text`, `el` with the allowlists, `raw`, `finish`, and the
  document helper that writes the `head` (charset, viewport, the CSP, the title). It imports
  nothing of the project. — RF-06, ADR-1, ADR-7, ADR-8
- [ ] `src/mailvigil/html_style.py`: the two palettes as dicts taken from the mockup, the
  stylesheet built from them (tokens on `:root`, dark by `prefers-color-scheme`, the rest of the
  CSS as a constant), the print rules. If a pair of the mockup fails the contrast test, the token
  is darkened and the change is listed here and reported, not hidden. — RF-07, ADR-10
- [ ] Quality gate of the stage (same four commands). **Result:** _to fill in when the stage
  runs._

## Stage 4 — The catalog and the charts (RF-03, RF-04, RF-07, RF-08, ADR-4, ADR-5, ADR-9)

- [ ] `tests/test_messages.py`, first: `HtmlMessages` exists in both languages and every
  `Mapping` and `Plural` in it is filled; the `pt-BR` catalog stays ASCII; no key of
  `HtmlMessages` repeats a sentence that `common`, `summary` or `verdict` already has. — RF-08
- [ ] `src/mailvigil/messages/model.py`, `en.py`, `pt_br.py`: `HtmlMessages` (the eyebrow, the two
  group titles of the rules, the section titles, the meter legend, the policy box labels, the
  timeline captions, the accessible names, the footer) and its two instances. Sentences the text
  format already has are read from the other dataclasses. — RF-08
- [ ] `tests/test_html_charts.py`, the meter, written first: the table of ADR-5 with the numbers of
  the approved mockup (period 29 against 28: fill 1000, tick 965; unrecognized failures 48 of
  7,323 against 0.5%: fill 655, tick 500), a value exactly at the limit, a value far above it
  (the fill is capped and the real value is printed), rule 4 with and without failures, `whole ==
  0`, a very large count; the fill never exceeds 1000; each meter has `role="img"`, an
  `aria-label` with the numbers, and the status as an icon and a word; a "stay below" meter says
  so in words; a failed data rule says how much is missing. — RF-03, ADR-5
- [ ] `tests/test_html_charts.py`, the stacked bar, first: the four situations with their counts
  and shares in the legend (the shares of the text format), a zero segment drawn with no width and
  still named in the legend, a tiny failing share keeps a minimum width, the `aria-label` states
  the figures. — RF-04
- [ ] `tests/test_html_charts.py`, the timeline, first: a month gives one column per day; a period
  of 90 days is one column per day and of 91 days groups of two; a year gives groups of 5 and a
  century gives at most 90 columns and a bounded number of elements, in bounded time (it must not
  loop over the days); the failing segment is the base of the column, never shorter than 3 units
  of 100 when there are failures, and a triangle sits above exactly the columns with failures; SPF
  only is the hatched segment; a day in `covered` with no begin is the short dash, a day in no
  interval is the dashed ghost column; the counts of the columns add up to the totals; the labels
  are the first, middle and last date; the `<details>` table has one row per column with the same
  figures; the caption says how many days a column is when grouped and that a report counts on
  the day it begins. — RF-04, ADR-3, ADR-4, ADR-9
- [ ] `src/mailvigil/html_charts.py`: `meter`, `stacked_bar`, `timeline`, each a pure function
  from the data and a `Messages` to a `Safe`; the geometry as small integer helpers a test can call
  alone; the SVG built with `htmlkit`. — RF-03, RF-04, ADR-4, ADR-5, ADR-9
- [ ] Quality gate of the stage (same four commands). **Result:** _to fill in when the stage
  runs._

## Stage 5 — The renderer and the flag (RF-01, RF-02, RF-05, RF-06, RF-07, RF-08, RF-09, RNF-03, RNF-04, ADR-6, ADR-8)

- [ ] `tests/test_render_html.py`, written first, the structure through `html.parser`: one `h1`
  (the answer), headings in order, `lang` equal to the language, tables with `th scope`, SVGs with
  a label, the sections in the order of the design for each answer; `READY` has no deciding rule
  and no failing-sources content; "Left out" appears only when a count is above zero; the policy
  box shows `np` only when present; the notes of the verdict are all there; the page has no path
  and no file name. — RF-02, RF-05, RF-07
- [ ] `tests/test_render_html.py`, parity and contract: for the same run, the answer, the five
  figures, the senders, the failing sources and the notes of the page equal those of
  `render_verdict` and `render_summary`; `pt-BR` gives `lang="pt-BR"` and ASCII only; two calls
  give the same string; a year of daily reports from a dozen senders stays under the size ceiling
  (about 200 KB); the output is ASCII and ends in a newline. — RF-02, RF-08, RNF-03, RNF-04
- [ ] `tests/test_render_html_hostile.py`, first: the attack strings of RF-06 (`<script>`, `"`,
  `'`, `&`, `</style>`, `<!--`, `-->`, `javascript:`, a long run, control characters, a
  bidirectional override) in every field that reaches the page (the domain, service names,
  selectors, addresses, override reasons, the `p`, `sp`, `np` and earlier `p` values); the parsed
  document has no `script`, no event-handler attribute, no `href` or `src` other than `#…`, no
  `iframe`, `object`, `embed`, `form`, `link`, `base` or refresh, carries the CSP, and each attack
  appears only as the text of a node; extreme inputs (a period of many years, one day with a huge
  count, zero messages in a situation, all rules passing, all failing) give a valid document and
  never an exception. — RF-06, RF-09, ADR-8
- [ ] `tests/test_cli_html.py`, first, through `main(argv)` and `capsys`: `verdict --html` ends in
  `0`, `3` and `4` for ready, too early and not ready and prints one document that starts with
  `<!doctype html>`; with `--lang pt-BR`; `--html` with `--json` is a usage error and exit `2`;
  `summary --html` is exit `2`; a refusal before an answer (no reports, bad domain) writes nothing
  to standard output and ends in `1`; `--help` names the format and says to redirect it; every
  existing CLI test passes untouched. — RF-01, RF-08, ADR-6
- [ ] `src/mailvigil/render_html.py`: `render_html(summary, verdict, messages)` with the sections of
  the design, in order, from the catalog and the helpers of stage 1; nothing but `htmlkit` builds
  markup. — RF-02, RF-05, RF-06
- [ ] `src/mailvigil/cli.py`: `--html` on the `verdict` subparser, the refusal of the pair with
  `--json` through `parser.error` before any work, the branch in `_run_verdict` (the exit code line
  untouched). The `--help` text mentions the redirect and, for Windows PowerShell 5.1, `|
  Out-File -Encoding ascii`. — RF-01, ADR-6, ADR-7
- [ ] Look at the real page in a browser, with the maintainer's mockup beside it: generate a page
  from synthetic reports with failures, with none and with a gap; capture 390 and 1280 px, light
  and dark, and the print preview; compare with boards B, C and T1 and list the three largest
  deviations; fix and capture again, at most three rounds. Run `auditar_proporcoes.py` and
  `auditar_navegador.py` (axe) from the `/auditoria-interface` skill on the file, and tab through
  the page: the senders table, the numbers table and the `details` take focus with a visible
  outline. Record what was found. — RF-03, RF-04, RF-07
- [ ] Quality gate of the stage (same four commands). **Result:** _to fill in when the stage
  runs._

## Stage 6 — Close (RF-01 to RF-09, all RNF)

- [ ] End-to-end with the real command: a folder of synthetic reports and an `.eml` through
  `uv run mailvigil verdict --domain example.com FOLDER --html > report.html` for each of the three
  answers; open each in a browser and read the answer, the rules and the timeline as the person
  deciding would. Check that the text and JSON output of `summary` and `verdict` for the same
  folder is byte-identical to the one of `main` before the spec. Record what was done. — RNF-05
- [ ] `README.md`: the flag, the redirect, one image of the page if the maintainer approves one (it
  is built from synthetic data), the PowerShell 5.1 note; `docs/stack.md`: inline SVG, CSP,
  `NewType` and `html.parser`, each with what to study first; `CLAUDE.md`: the architecture block
  (`htmlkit.py`, `html_style.py`, `html_charts.py`, `render_html.py`, `DayCounts`), the commands and
  the one-line warning that markup is built in `htmlkit.py` only; `specs/README.md`: the roadmap
  row to `done`. `docs/json-schema.md` is checked and unchanged. — RF-08
- [ ] `status:` of the three files of the spec to `done`, and the maintainer's memory of the
  project updated (the 008 closed, the next is 009), in the same session. — RNF-05
- [ ] `/atualizar-docs`, then `/fechar-sessao` (commit, push, PR; no merge).
- [ ] Final quality gate: the same four commands, plus `uv build` and the check that the wheel has
  no `Requires-Dist` (RNF-01). **Result:** _to fill in when the stage runs._
