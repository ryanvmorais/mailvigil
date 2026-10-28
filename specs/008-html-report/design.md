---
feature: HTML report — one static file with the summary and the verdict
status: approved
date: 2026-10-28
related:
  - 008-html-report/requirements.md
  - 004-summary/design.md
  - 005-reject-verdict/design.md
  - 006-output-and-exit-codes/design.md
origin: conception
---

# 008 — HTML report — design

## Overview

`mailvigil verdict --html` writes one HTML document to standard output. It is a third way of
printing the same `Verdict` and `Summary`, next to the text and the JSON, and it follows the same
rule they follow: **the command decides the exit code first, the renderer only lays out**.

```text
ingest → summarize → judge ─┬→ render_verdict   (text, --lang)
                            ├→ verdict_document (JSON, no language)
                            └→ render_html      (HTML, --lang)        ← new
```

The renderer is a pure function: `render_html(summary, verdict, messages) -> str`. It prints
nothing, reads no clock, no environment, and no file. The page shows no file-system path and no
file name (the text format does not either), so a page e-mailed to a manager carries nothing of the
machine it was made on.

Two things the page needs do not exist yet and are added first, in small steps that change no
output that already ships:

1. **Per-day counts in the `Summary`** for the timeline (ADR-3).
2. **Public helpers in `render_verdict.py`** for the sentences the page shares with the text
   (ADR-2).

## Modules

```text
src/mailvigil/
  summary.py          # + DayCounts, Summary.days, Summary.covered (internal; --json unchanged)
  render_verdict.py   # the shared sentences become public: reason_sentence, next_sentence,
                      # measured_text, needed_text, missing_text, note_sentence
  htmlkit.py          # Safe, text(), el(), attr escaping, finish(): the ONLY place markup is built
  html_style.py       # the stylesheet and the palette tokens (light and dark), as data
  html_charts.py      # meter, stacked bar and timeline: pure functions returning Safe
  render_html.py      # render_html(): the sections, in order, from the catalog
  messages/model.py   # + HtmlMessages (en.py and pt_br.py fill it)
  cli.py              # + --html on `verdict`; refusal of --html with --json
```

`htmlkit.py` imports nothing of the project. `html_charts.py` and `render_html.py` import `htmlkit`
and never `html.escape` themselves. `summary.py` still imports no renderer.

## Data

### Per-day counts (internal)

```python
@dataclass(frozen=True, slots=True)
class DayCounts:
    day: date           # the UTC day a report's period begins on
    reports: int        # reports that begin that day
    counts: Counts      # their messages per situation

# on Summary, both defaulted so nothing else has to change:
days: tuple[DayCounts, ...] = ()                     # sorted by day, only days with a report
covered: tuple[tuple[date, date], ...] = ()          # merged [first, last] day intervals
```

Both are **sparse**: their size is bounded by the number of reports, never by the length of the
period (004 RNF-09: a report may span centuries). `covered` is the list `_period` already builds to
count `days_with_reports`; it is returned by the same helper, so rule 2 and the timeline cannot
disagree about which days have a report.

The invariant, tested: `sum(day.counts for day in days) == totals` and
`sum(day.reports for day in days) == reports`.

### Text of the page

`HtmlMessages` holds only the sentences that exist nowhere else: the eyebrow ("Ready for p=reject?"),
the two group titles of the rules, the section titles, the meter legend, the labels of the policy
box, the timeline captions, the accessible names and the footer. Everything the text format already
says (rule names, answers, reasons, next step, notes, left-out, kinds of source, situations) is read
from `common`, `summary` and `verdict` of the same catalog. A test iterates both languages so no key
is missing in one.

## Components (the page, top to bottom)

This is the order of the approved mockup (see "Interface record").

| # | Block | Source | Requirement |
|---|---|---|---|
| 1 | Header: shield mark, "MailVigil", `domain · first to last day · N reports from M reporters` | `Summary` | RF-02 |
| 2 | **Verdict banner**: eyebrow, answer (`h1`), one-sentence reason, next step, and the policy box (`p`, `sp`, `np` when present, `pct`) | `Verdict` | RF-02 |
| 3 | **The five rules**, in two groups ("Is there enough evidence?" for data rules, "Is anything wrong?" for problem rules): a meter per rule | `Verdict.rules` | RF-03 |
| 4 | **Mix of messages**: a stacked bar of the four situations, with a legend of counts and shares | `Summary.totals` | RF-04 |
| 5 | **Timeline**: one column per day (or per group of days), split by situation | `Summary.days`, `covered` | RF-04 |
| 6 | **Senders** table, with a total row | `Summary.senders` | RF-05 |
| 7 | Two columns: **Failing sources** (recognized, then unrecognized) · **Worth knowing** (notes) and **Left out of the numbers** | `Verdict` | RF-05 |
| 8 | Footer: "Generated offline by MailVigil {version}. This file has no scripts and makes no network requests." | catalog | RF-02 |

The next step lives **inside the banner** (block 2), as in the mockup, not as a separate section at
the end; the requirement's order is amended to match (see "Changes to the requirements").

Blocks 3 to 7 are `section` elements with an `aria-labelledby` heading; the document has one `h1`
(the answer), `h2` for sections and `h3` for the two rule groups.

## Interfaces

```python
# render_html.py
def render_html(summary: Summary, verdict: Verdict, messages: Messages = ENGLISH) -> str:
    """The whole document, ASCII only, ending in a newline."""

# htmlkit.py
Safe = NewType("Safe", str)            # markup that is already safe to concatenate
def text(value: str) -> Safe: ...      # escapes; the only way a str becomes Safe
def el(name: str, *children: Safe, **attrs: str) -> Safe: ...   # attribute values escaped
def raw(markup: str) -> Safe: ...      # for the constant CSS and the constant SVG paths; a test
                                       # greps the call sites so no variable reaches it
def finish(document: Safe) -> str: ... # ASCII with numeric character references
```

```python
# cli.py: on the verdict subparser only
verdict_parser.add_argument("--html", action="store_true",
    help="print one self-contained HTML page (redirect it to a file); not with --json")
```

`main` refuses the pair before any work:

```python
if args.command == "verdict" and args.json and args.html:
    parser.error("argument --html: not allowed with argument --json")   # exit 2
```

`summary --html` is an unknown option, so argparse already ends with exit 2 (question 2).

`_run_verdict` keeps its shape: load, `summarize`, `judge`, then print by format, and
`return _VERDICT_EXIT[verdict.answer]` is untouched. A refusal before an answer writes nothing to
standard output (RF-01).

## Architecture decision records

### ADR-1 — One module builds markup, and `mypy` enforces it

- **Decision:** `htmlkit.py` defines `Safe = NewType("Safe", str)`. `text()` is the only function
  that turns a `str` into a `Safe` (by escaping), `el()` accepts only `Safe` children, and the
  renderers never concatenate `str` into markup. The constant parts (the stylesheet, the SVG path
  data) enter through `raw()`, whose call sites are listed in a test.
- **Alternatives:** (a) call `html.escape` at each use; (b) a template string with `{}` holes and an
  autoescape pass; (c) a template engine.
- **Why:** with (a), the one place someone forgets is the vulnerability, and no tool notices. With a
  `NewType`, passing a raw `str` where markup is expected is a **type error**, which the strict
  `mypy` gate already runs on every commit (RF-06, RNF-01). It costs a few functions and no
  dependency.
- **Trade-off:** more verbose than an f-string, and `NewType` is erased at run time, so the test of
  RF-06 (parse the output, forbid scripts, handlers and external references) stays: the type is the
  first defense and the parsed document is the proof.

### ADR-2 — Share the sentences of the text format, do not retype them

- **Decision:** the helpers that already build the reason, the next step, the figures and the notes
  in `render_verdict.py` lose their underscore and are used by both renderers: `reason_sentence`,
  `next_sentence`, `measured_text`, `needed_text`, `missing_text`, `note_sentence`. `_why` of the
  text format is rewritten on top of `reason_sentence`, so the two cannot drift.
- **Alternatives:** copy the logic into `render_html.py`; or build one neutral "sentence" model that
  both renderers read.
- **Why:** the rounding rule of `_share` (never show `0.5%` beside `FAIL`) took a bug to get right
  (005 ADR-8); a copy would fork it. A neutral model is the larger rewrite and nothing asks for it.
- **Trade-off:** `render_html` imports from `render_verdict`. Acceptable: `render.py` already
  exports `fit`, `address`, `format_share` the same way. RNF-05 is the guard: a test records the
  text output of fixed inputs and the refactor must leave it byte-identical.

### ADR-3 — Timeline: sparse begin-day counts plus the covered intervals

- **Decision:** a report's messages are counted on the UTC day its period **begins** (`DayCounts`);
  which days **have a report** comes from `covered`, the merged intervals of the days a report
  touches, the same list rule 2 uses.
- **Alternatives:** (a) share each report's messages across the days it touches; (b) a dense list of
  one entry per day; (c) no per-day data, draw only `days_with_reports`.
- **Why:** a daily report runs from midnight to midnight and is exact under the chosen rule; (a)
  needs an arbitrary split that nobody can check against the report; (b) is unbounded for a report
  spanning centuries; (c) cannot show *when* something failed, which is the question the timeline
  answers ("did the failures stop?").
- **Trade-off:** a report that spans three days puts all its messages on the first. The other two
  days are in `covered`, so the page draws them as **covered, with no bar**, and a caption below the
  chart says that a report is counted on the day it begins. Rule 2 and the chart never disagree on
  whether a day has a report.

### ADR-4 — The timeline is bounded: at most 90 columns, grouped by the same size

- **Decision:** `MAX_COLUMNS = 90`. A period of up to 90 days draws one column per day; a longer one
  draws groups of `ceil(days_spanned / 90)` consecutive days, and the caption says "each column is
  N days". The renderer loops over the columns (at most 90), never over the days, and finds each
  column's counts by bisecting the sorted `days`.
- **Alternatives:** truncate to the last 90 days; scroll horizontally; calendar months.
- **Why:** truncating hides the beginning, which is where a problem that was fixed lives. A year is
  365 days, so a fixed 90-column ceiling means groups of 5; the number of SVG elements is bounded
  at roughly `90 × 4 + a few`, and the file stays small (RNF-04). Calendar months give uneven
  columns and a gap that is hard to read.
- **Trade-off:** inside a group the exact day is lost; the text alternative (ADR-9) lists the same
  groups, not the days.

### ADR-5 — Meter geometry: one integer rule, taken from the mockup

- **Decision:** each rule becomes a pair of integers `(value, limit)` in a common unit and the meter
  is drawn from them, in tenths of a percent of the width:

  | Rule | value | limit | Direction |
  |---|---|---|---|
  | 1 period | `measured` | `needed` | at least |
  | 2 coverage | `100 × measured` | `needed × whole` | at least |
  | 3 volume | `measured` | `needed` | at least |
  | 4 recognized failures | `measured` | `0` | at most |
  | 5 unrecognized failures | `1000 × measured` | `needed × whole` | at most |

  `scale = max(value, limit)` for "at least" and `max(value, 2 × limit)` for "at most"; fill is
  `value / scale`, the tick (the limit) is `limit / scale`; `scale == 0` draws an empty meter with
  the tick at 0.
- **Alternatives:** floats; or a fixed scale per rule.
- **Why:** it reproduces the numbers of the approved mockup (period: fill 100%, tick 96.5%; unrecognized
  failures: fill 65.5%, tick 50%) and keeps the project's rule of integer arithmetic. "At most"
  rules put the limit at the middle, so the zone on its right reads as "over" at a glance. It never
  overflows: the fill is capped at 100% by construction.
- **Trade-off:** rule 4 has a limit of 0, so its tick sits at the left edge and any failure fills
  the whole bar. That is the honest picture: "none allowed".

### ADR-6 — `--html` only on `verdict`, a sibling of `--json`

- **Decision:** as recommended in question 1 and 2 and approved: a `--html` flag on `verdict`, with a
  manual refusal of `--html --json` through `parser.error`.
- **Alternatives:** `--format {text,json,html}`; a `report` command; `--html` on both commands.
- **Why:** nothing that exists changes. argparse cannot declare a mutually exclusive group across a
  parent parser and a subparser's own argument, so the check is one line in `main`, before any work,
  and it exits 2 as every usage error does.
- **Trade-off:** the roadmap line saying `--format html` is corrected to `--html`.

### ADR-7 — ASCII output through numeric character references

- **Decision:** `finish()` encodes the whole document with `errors="xmlcharrefreplace"` and decodes
  it back, so a name with an accent becomes `&#233;`. The page still declares
  `<meta charset="utf-8">`. The catalog stays ASCII, like the other two formats.
- **Alternatives:** write UTF-8 with the characters; or emit UTF-8 bytes to `sys.stdout.buffer`.
- **Why:** the other two formats are ASCII "so that no console encoding can break the layout"
  (006). The same holds for a redirect (`> report.html`) under cmd.exe, Git Bash and PowerShell 7.
- **Trade-off, stated plainly:** this does **not** cure Windows PowerShell 5.1, whose `>` rewrites
  any output as UTF-16 with a byte-order mark. Browsers read that file correctly, but other tools
  may not. ASCII makes the page immune to a legacy code page; it does not make the bytes identical
  across shells. The `--help` text and the README suggest `| Out-File -Encoding ascii` for that
  shell. If it hurts in practice, a later spec adds `--output FILE` (question 5).

### ADR-8 — The document cannot run or load anything, and says so to the browser

- **Decision:** the `head` carries

  ```html
  <meta http-equiv="Content-Security-Policy"
        content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
  ```

  There is **no image of any kind** (the mark and the icons are inline SVG), so `img-src` is
  omitted and inherits `'none'`. This tightens RF-06, which allowed `data:` images. The page has no
  `link`, `base`, `form`, `iframe`, `object`, `embed` or `script`, and no `href` other than a `#`
  fragment (the page has none today; if a "skip to content" link is added it is `#main`).
- **Alternatives:** no CSP; CSP in an HTTP header (impossible for a file).
- **Why:** it is the second wall. If a future change lets a value through unescaped, the browser
  still refuses to run it. `'unsafe-inline'` is needed only for `style`: the stylesheet and the
  `style="width:…"` of the meters.
- **Trade-off:** inline styles cannot be locked down with a hash because the meters carry
  per-element widths. The risk is a style injection, which cannot execute code, and the escaping
  already stops it.

### ADR-9 — Charts are SVG and CSS with a text alternative

- **Decision:** the meters are `div`s with an inline `width`, as in the mockup. The stacked bar is a
  row of `i` elements with a legend. The timeline is one `svg` with `rect` columns coloured by CSS
  classes (so dark mode works through the same variables). Each chart has `role="img"` with an
  `aria-label` that states the numbers, and the timeline has a `<details>` with a real table of the
  same columns ("Show the numbers"), which needs no script.
- **Differences by more than colour (RF-04, RF-07):** the legend always prints the count next to the
  swatch; the segments are separated by a 2 px gap; a column with failing messages gets a mark
  above it (a small `!`-shaped glyph drawn in the SVG) and the failing segment is the one at the
  base, so its position is fixed.
- **Alternatives:** a `canvas` (needs script); an image (not allowed); only a table.
- **Trade-off:** hand-written SVG is more code than a library, and the project promised none.

### ADR-10 — The palette is data, and a test measures it

- **Decision:** `html_style.py` keeps the colour tokens as two dicts (light, dark) taken from the
  mockup, builds the `:root` and `prefers-color-scheme: dark` blocks from them, and a test computes
  the WCAG contrast of every text/background pair and of the graphics that carry meaning
  (4.5:1 and 3:1, RF-07).
- **Alternatives:** a hand-written stylesheet string with no check; a hand check in the browser.
- **Why:** a contrast regression is silent. The mockup states the intent; the test makes it a gate.
  If a pair of the mockup fails the test, the palette is corrected and the change is reported, not
  hidden.
- **Trade-off:** the stylesheet is built, not pasted, so it is a little harder to read than CSS.
  The rest of the CSS stays a constant string.

## Interface record

The interface was decided with the maintainer on 2026-10-28 from a mockup made in the Artifact
([MailVigil HTML report mockup](https://claude.ai/artifact/CBESgyFbFFdvrCkUPZQWwZ)), with invented
data (`example.com`, documentation IP ranges) and provisional texts.

| Board | What it tried | Outcome |
|---|---|---|
| A · Checklist | the five rules as a list with a mark per rule | not chosen: it says pass or fail but not how far |
| **B · Meters** | each rule as a meter against its limit, the limit marked on the bar | **chosen** for the rules: the reader sees the distance to the limit, which is the question |
| C · Cards | totals as number cards, a stacked bar of the mix, the rules as pills | the **stacked bar** is kept; the number cards and the pills are not |

Decisions carried over from the mockup: the verdict first and large; the colour of the banner follows
the answer; WebVigil's visual language (slate palette, 0.5 rem radius, icon plus word on every
badge, 4.5:1 contrast, dark mode from the system); the senders table scrolls inside its own box at
phone width; the max width of the page is 1040 px.

### The timeline and the four-situation bar (boards T1 and T2)

The roadmap recorded the timeline in words only, and board C drew three situations. Two boards
were added to the same Artifact, each at 1280 and 390 px, with the month of board B's data, a year
grouped by 5 days, and a run with a day without a report and days covered by a report that counts
on another day.

| Board | What it tried | Outcome |
|---|---|---|
| **T1 · Columns** | one stacked column per day; height is the volume, failing at the base, a triangle above a day with failures | **chosen by the maintainer on 2026-10-28** |
| T2 · Strip | one cell per day, red when any message failed | not chosen: it says whether a day had failures, not how many, and colouring by a threshold would make the tool judge |

Decisions fixed by T1, carried into ADR-9: failing is the base segment, with a minimum height of 3
units out of 100 so a day with two failures in 250 messages stays visible, and the triangle is
mandatory because that segment can still be small; SPF only is hatched, the others solid, so the
four situations differ by more than hue; a day with no report is a dashed ghost column; a day
covered by a report that counts on another day is a short dash on the baseline; x labels are the
first, the middle and the last date; the number table sits in a `details` under the chart.

### What was checked

The markup and CSS of T1 and T2 were rendered in Chrome at 1280 and at 390 px (inside a 390 px
frame, since a headless window cannot be that narrow), in light and in dark: no horizontal scroll,
legends wrap, the year at 73 columns stays legible at 390 px (about 4.6 px per column, the
triangles shrink to dots), the dark palette reads. **Not checked:** the boards inside the Artifact
canvas (the phone boards import the desktop ones through the canvas runtime, which a local browser
does not run), and the real page, which does not exist yet. The real page is checked in a browser,
at 390 and 1280 px and in both themes, in the stage that writes it.

### Other gaps, now closed

- **The page has no configuration path and no skipped file names,** which the mockup never showed
  either; the "Left out" block only counts, as in the verdict text.

## Changes to the requirements

Made together with this design, because the design found them:

- **RF-02:** the next step is inside the verdict banner, and the failing sources, the notes and
  what was left out sit in two columns, as in the mockup. The order of the facts is unchanged.
- **RF-06:** the Content-Security-Policy has no `img-src`, and the page has no `data:` image at all.
- **RNF-02:** the renderer takes the `Summary`, the `Verdict` and a `Messages`; it takes no
  configuration source.

## Impact

- `summary.py`: two new fields on a frozen dataclass, defaulted. Every existing construction and
  every existing test keeps working; `summary_document` builds its dict by name, so the JSON is
  byte-identical (tested).
- `render_verdict.py`: seven names become public; the text output is byte-identical (tested).
- `messages/`: one new dataclass and its two instances; the test that compares the catalogs covers
  it.
- `cli.py`: one argument and one check. Exit codes unchanged.
- Docs: README (usage), `docs/stack.md` (`html`, SVG, CSP and `NewType`, with what to study),
  `CLAUDE.md` (architecture block), `specs/README.md` (the flag name). `docs/json-schema.md` does
  not change.

## Risks

1. **The timeline attribution is surprising** for a provider that sends reports on a different
   window than a UTC day. Mitigated by the caption (ADR-3) and by drawing covered days with no bar
   instead of as gaps.
2. **A palette pair fails the contrast test.** Expected for muted text on tinted backgrounds. The fix
   is a darker token, decided in the stage that writes the test.
3. **The shared helpers are refactored under a passing suite.** Mitigated by the byte-identical test
   of the text output before the refactor starts.
4. **PowerShell 5.1 and `>`** (ADR-7): documented, not solved.
5. **A hostile value is long** (a 5 MiB organization name is impossible: the parser cuts text at 255
   characters, 002 RF-05), but the config and `--domain` come from the user. They are cut with the
   same `clean_text` the other formats use before they reach the page.

## Tests

| What | How | Requirement |
|---|---|---|
| Escaping of every field | built `Summary`/`Verdict` with attack strings; the output is parsed with `html.parser`; no `script`, no event handler, no `href`/`src` except `#…`, no `form`/`iframe`/`object`/`embed`/`link`/`base`, the CSP present, and every attack string shows up only as text | RF-06, RF-09 |
| `raw()` call sites | a test reads the module source and fails if `raw(` receives anything but a literal or a module constant | ADR-1 |
| Parity with the text format | same run, facts extracted from both; the answer, the five figures, the senders, the failing sources, the notes | RF-02 |
| Text output unchanged | recorded text of fixed inputs, compared before and after the refactor | RNF-05, ADR-2 |
| JSON unchanged | `summary_document` of a summary with days equals the one without | RF-08 |
| Meter geometry | the table of ADR-5 with the mockup numbers, zero, huge values, `whole == 0` | RF-03 |
| Per-day counts | sum of the days equals the totals; a report across midnight; a report of zero length; a report spanning centuries stays sparse | RF-04 |
| Timeline bounds | a period of a year and of a century: at most 90 columns and a bounded number of elements | RF-04, RNF-04 |
| Palette | WCAG contrast of every pair, light and dark | RF-07 |
| Structure | one `h1`, headings in order, `lang`, `th scope`, SVG titles | RF-07 |
| Languages | both catalogs fill `HtmlMessages`; `pt-BR` output is ASCII and has `lang="pt-BR"` | RF-08 |
| Determinism and size | two runs equal; a year of daily reports under the size ceiling | RNF-03, RNF-04 |
| CLI | `main(argv)`: `--html` exit codes 0/3/4, `--html --json` exit 2, `summary --html` exit 2, refusal writes nothing to stdout | RF-01 |
| Visual (manual, in a real browser) | 390 and 1280 px, light and dark, print preview, a screen-reader pass on headings | RF-07 |

## Open points for the maintainer

1. **The 90-column ceiling** (ADR-4): a first guess that fits a 1040 px page. The year board shows
   73 columns working at 390 px, so 90 is kept; it is a constant to adjust if the real page asks.
