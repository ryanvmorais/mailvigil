---
feature: HTML report — one static file with the summary and the verdict
status: done
date: 2026-10-28
related:
  - 004-summary/requirements.md
  - 005-reject-verdict/requirements.md
  - 006-output-and-exit-codes/requirements.md
origin: conception
---

# 008 — HTML report

## Context and problem

`mailvigil verdict` answers in text and in JSON. Text is the right answer for a terminal and JSON for
a script, but neither is something the owner of a domain can **show**: to the person who runs the
mail platform, to a manager who has to approve the move to `p=reject`, or to themselves in three
weeks. A table of 80 columns pasted into a chat loses its shape, and a JSON document is not read by
the people who decide.

The roadmap already holds the answer to "why not a dashboard": a server is a non-goal (see
[the permanent non-goals](../README.md#permanent-non-goals)). What fits the product is **one HTML
file** written to disk: the verdict first, each rule against its limit, the mix of messages and a
timeline of the days covered, openable by double click, attachable to an e-mail, archivable next to
the reports it came from. No server, no script, no network, no file besides itself.

The page is built from text that a third party controls (reporting organizations, selectors, source
IPs, domains inside reports). In a terminal that text is cleaned; in HTML it would become markup if
nothing stopped it. This is the same rule as in 002, in a more dangerous medium: every character that
comes from a report is escaped at the one place that writes HTML, and a test feeds it the attack.

The page has an interface, so it follows the global rule: the maintainer approved a mockup before any
code (decided on 2026-10-28, recorded in the roadmap: the verdict first, each rule as a meter
against its limit, the stacked bar of the message mix, WebVigil's visual language, a per-day
timeline in inline SVG). The mockup goes into the design; no HTML is written before the design is
approved.

## Goals

- **One self-contained `.html` file** with the verdict, its five rules, the senders, the failing
  sources, the notes and what was left out: the same facts as `verdict` and `summary`, no new
  judgment.
- **Open anywhere, offline:** no script, no external font, image, stylesheet or link that is
  followed; the file works from `file://` and when e-mailed.
- **Safe by construction:** nothing from a report reaches the page unescaped, and the page cannot
  run or load anything.
- **Readable by someone who is not a technician:** the answer and its reason come first; the numbers
  come with their limit; color is never the only signal.
- **English and Portuguese,** by the same `--lang` and the same message catalog as the text.

## Non-goals

- A server, a live page, auto-refresh, or anything that polls (permanent non-goal).
- JavaScript of any kind, including to sort tables, toggle sections or draw the charts: the charts
  are inline SVG written by Python.
- Printing layouts as a product (a `@media print` rule that keeps the page legible is enough, a PDF
  is the browser's job).
- Interactive filtering, drill-down by report, or showing individual records beyond what `summary`
  already shows.
- A theme switch or user-chosen colors: dark mode follows the system and nothing else.
- Embedding the raw reports, or links to the files they came from.
- A second judgment: the page shows the `Verdict` of 005 and never recomputes a rule.
- Sending the file anywhere (permanent non-goal).

## Personas

- As the **maintainer** (and any domain owner), I want a page I can send to whoever approves the
  change, so that "it is ready" comes with the reason and the numbers, not with my word.
- As the **person deciding** (not a DMARC specialist), I want to see the answer, the rule that
  decided it and how far each rule is from its limit, so that I understand without reading a table.
- As a **user with a screen reader or a colour-vision difference,** I want every status to carry a
  word and a shape as well as a colour, so that the page does not depend on seeing red and green.
- As a **security-minded user,** I want to open a file made from reports I did not write without
  worrying that one of them can run something in my browser.

## Functional requirements

### RF-01 — Ask for the page

- **Given** `mailvigil verdict` with the usual paths and domain
  **When** the user asks for the HTML format (flag closed in the design, see question 1)
  **Then** one HTML document is written to standard output and nothing else is written there.
- **Given** the HTML format and `--json` together
  **When** the arguments are parsed
  **Then** it is a usage error with exit code 2: a run has one format.
- **Given** the HTML format
  **When** the run ends
  **Then** the exit code is the one the verdict gives (0 ready, 3 too early, 4 not ready, 1 refused),
  decided before the format as in 006 RF-04.
- **Given** a run refused before any answer (no reports, bad configuration)
  **When** the HTML format was asked
  **Then** nothing is written to standard output, the refusal line goes to standard error and the
  exit code is 1, as in the text format.
- **Given** `--help`
  **When** it is read
  **Then** it says the HTML format exists and that the output is meant to be redirected to a file.

### RF-02 — What the page says, in order

- **Given** a verdict of any answer
  **When** the page is read from the top
  **Then** it shows, in this order: a header with the domain and the period; the answer, the
  one-sentence reason (the deciding rule, or that every rule passes) and the next step; the five
  rules; the mix of messages; the timeline of the days; the senders; the failing sources, the notes
  and what was left out (the three may sit side by side); a footer with the tool name and version.
- **Given** the answer is `READY`
  **When** the page is read
  **Then** there is no deciding rule, no failing-sources section with content, and the next step
  says what the text format says for that answer.
- **Given** the texts of the sections
  **When** they are written
  **Then** they come from the message catalog (`messages/`), the same sentences as the text format
  where the content is the same, never retyped in the HTML module.
- **Given** the HTML and the text formats for the same run
  **When** their facts are compared
  **Then** they agree: same answer, same figures per rule, same senders and failing sources. A test
  compares them.

### RF-03 — Each rule against its limit

- **Given** each of the five rules
  **When** the page shows it
  **Then** it shows the name, the value measured, the limit (`needed`), whether the rule passed, and
  a meter that places the value against the limit, with the status written as a word and an icon
  next to it.
- **Given** a rule that passes with a value far above the limit (28 days needed, 400 found)
  **When** the meter is drawn
  **Then** it is capped at the full width and the real value is printed; a meter never overflows
  its box.
- **Given** a "stay below" rule (rules 4 and 5)
  **When** the meter is drawn
  **Then** it is explicit that less is better: the limit is the end of the safe zone, and the label
  says so in words.
- **Given** a failed data rule
  **When** the page shows it
  **Then** it says how much is missing, in the unit of the rule (days or messages), as the text
  does.

### RF-04 — Mix of messages and timeline

- **Given** the totals of the summary
  **When** the mix is drawn
  **Then** a stacked bar splits all messages into the four situations of 004 (ok, DKIM only, SPF
  only, failing), each segment labelled with its count and its share, using the shares and rounding
  of the text format.
- **Given** the period of the reports
  **When** the timeline is drawn
  **Then** each UTC day from the first to the last is a column: a day with no report is drawn as a
  gap and named as one, not as zero.
- **Given** a day with messages
  **When** its column is drawn
  **Then** it is split by situation as the mix is, and a day with failing messages is told apart by
  more than colour.
- **Given** a period of many days (a year)
  **When** the timeline is drawn
  **Then** it stays legible and bounded: the number of drawn elements has a ceiling, closed in the
  design, and a longer period is grouped, never truncated silently.
- **Given** the timeline needs a figure per day that the `Summary` does not hold today
  **When** the design is written
  **Then** the per-day counts are computed once, in `summary.py`, with the same attribution rule as
  the days of the period (004 ADR-3), and the sum of the days equals the totals (see question 4).
- **Given** both charts
  **When** a person cannot see them
  **Then** each has a text alternative and the same numbers exist as text in a table.

### RF-05 — Senders, failing sources, notes, what was left out

- **Given** the senders of the summary
  **When** the page lists them
  **Then** every row of the summary is there, in the summary's order, with its situations; the
  list is a real table with header cells, and a wide table scrolls inside its own box at phone
  width instead of breaking the page.
- **Given** failing sources
  **When** the page lists them
  **Then** recognized and unrecognized sources are separated, as in the verdict, each with its IP,
  message count and the mechanisms that failed.
- **Given** the notes of the verdict
  **When** the page lists them
  **Then** each is there with its sentence; none is presented as changing the answer.
- **Given** files skipped, duplicates and reports of another domain
  **When** any is above zero
  **Then** the page says so, with the reasons counted as in the text format, and it says that the
  answer is about fewer reports than were given.

### RF-06 — Nothing from a report can become markup

- **Given** any text that comes from a report, a mail message, a path, the configuration or the
  command line (organization, selector, service name, domain, IP, file name, attachment name, the
  domain of `--domain`)
  **When** it is written to the page
  **Then** it goes through one escaping function at the one module that writes HTML, in text and in
  attribute positions, and no other module concatenates markup.
- **Given** a value containing `<script>`, `"`, `'`, `&`, `</style>`, `<!--`, `-->`, a `javascript:`
  string, a very long run, control characters or a bidirectional override
  **When** it reaches the page
  **Then** the file has no element, attribute or comment that the text could have created, and the
  visible text is the sanitized text of 002 (RF-05), not the raw one.
- **Given** the whole document
  **When** it is parsed with the standard library's HTML parser in a test
  **Then** it contains no `script` element, no event-handler attribute, no `href` or `src` that is
  not a fragment (`#…`) or a `data:` image the tool wrote, no `iframe`, `object`, `embed`, `form`,
  `link` to a stylesheet or `meta http-equiv="refresh"`.
- **Given** the page
  **When** it is opened
  **Then** a `Content-Security-Policy` meta tag forbids everything but inline styles
  (`default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'`), so that a
  mistake in the escaping still cannot load or run anything. The page has no image file or `data:`
  image: the icons and the charts are inline SVG and CSS.

### RF-07 — Readable and accessible

- **Given** the page at 390 px and at 1280 px wide
  **When** it is opened
  **Then** there is no horizontal scroll of the page itself, the text is not clipped, and the order
  of the sections is the same.
- **Given** any text and its background, in light and in dark
  **When** the contrast is measured
  **Then** it is at least 4.5:1 (3:1 for large text and for graphics that carry meaning).
- **Given** the system asks for dark mode
  **When** the page is opened
  **Then** it uses a dark palette defined by `prefers-color-scheme`; with no preference it is light.
- **Given** a status (passed, failed, too early, fragile…)
  **When** it is shown
  **Then** it carries an icon and a word as well as a colour.
- **Given** the document
  **When** a screen reader reads it
  **Then** it has `lang` set to the language of the run, one `h1`, headings in order, tables with
  `th scope`, and SVGs with a title and a description or marked decorative.
- **Given** the page is printed
  **When** the browser prints it
  **Then** the colours are kept as far as the browser allows, sections do not split across pages
  badly, and the dark palette is not used.

### RF-08 — Language and contract

- **Given** `--lang pt-BR`
  **When** the HTML is written
  **Then** every sentence is Portuguese from the catalog, `lang="pt-BR"`, and the same ASCII-only
  rule as the text holds for the catalog (see question 3 for the file itself).
- **Given** the HTML format
  **When** a new sentence is needed
  **Then** it is added to the `Messages` catalog in both languages, and the test that compares the
  two catalogs still passes.
- **Given** the page
  **When** the schema docs are read
  **Then** `docs/json-schema.md` is unchanged: the HTML is not a contract. The structure of the page
  may change between versions; only the exit codes and the JSON are public.
- **Given** the summary now holds per-day counts
  **When** `--json` runs
  **Then** the existing documents are unchanged unless the maintainer decides to expose the days
  (question 4); a field is never added by accident.

### RF-09 — Hostile and extreme input is tested, not assumed

- **Given** the test suite for this spec
  **When** it runs
  **Then** it contains, at least: the attack strings of RF-06 in every text field that reaches the
  page (organization, selector, service, domain, IP, skipped file name, attachment name); a report
  period of many years; one day with a very large count; zero messages in a situation; a verdict of
  each answer; all rules passing and all rules failing; and each expects a valid document that
  passes the checks of RF-06, never an exception out of the renderer.

## Non-functional requirements

### RNF-01 — Standard library only

- **Given** the project at any commit
  **When** `[project].dependencies` is read
  **Then** it is still empty. The page is written with string building and `html.escape`; no
  template engine, no charting library, no CSS framework.

### RNF-02 — No side effects, typed and immutable

- **Given** the new functions
  **When** they run
  **Then** they do not print, read `sys.argv`, call `sys.exit`, read the environment, read the clock
  or write a file; they take the `Summary`, the `Verdict` and a `Messages`, and return a `str`. The
  page shows no file-system path and no file name. `mypy` strict passes.

### RNF-03 — Deterministic

- **Given** the same reports and options
  **When** the page is written twice
  **Then** the two files are byte-identical: no generation time, no random id, no environment
  detail. The date on the page is the period of the reports, never the day it was made.

### RNF-04 — Self-contained and small

- **Given** a domain with a year of daily reports from a dozen providers
  **When** the page is written
  **Then** it is one file, with the style inline, below a size closed in the design (order of 200
  KB), produced in well under a second beyond the time to ingest.

### RNF-05 — Does not change what already ships

- **Given** the text and JSON formats
  **When** this spec is done
  **Then** their output for the same input is byte-identical to before, the exit codes are
  unchanged, and the existing tests pass without edits.

### RNF-06 — Fits the Python floor and the platforms

- **Given** Python `3.12` and the CI matrix
  **When** the renderer is written
  **Then** it uses nothing newer, passes on both, and the tests do not depend on the platform's line
  ending or console encoding.

### RNF-07 — Synthetic fixtures only

- **Given** the tests
  **When** they need reports
  **Then** they build them from invented domains and the documentation IP ranges, as in 002 RNF-07.
  A real report never enters the repository, and no real data is shown in the mockup.

## Open questions

1. **How the user asks for the page.** The roadmap says `--format html`. Today `--json` is a boolean
   flag, so a `--format` would be a second way to ask for JSON, unless `--json` becomes an alias. Two
   options: **(a)** `--html`, a sibling of `--json`, mutually exclusive, on `verdict` only (the page
   is the verdict plus the summary behind it); **(b)** `--format {text,json,html}` with `--json`
   kept as an alias. Recommended: **(a)**. It changes nothing that exists and is consistent with
   006; `--format` can come later if a fourth format ever does. The cost is that the roadmap line
   will be corrected to say `--html`.
2. **Does `summary` get the page too?** The page needs the verdict for its first screen, and a
   summary-only page would be a second layout to design and test. Recommended: **no**, the HTML is
   the verdict's. `summary --html` is refused as an unknown option.
3. **Encoding of the file.** The text and JSON are ASCII so that no console corrupts them. A page
   redirected with `>` in Windows PowerShell 5.1 is written in UTF-16 by the shell, which no spec
   here can fix. Recommended: keep the file **ASCII only**, with numeric character references for
   anything else (`&#233;`), and declare `<meta charset="utf-8">` anyway, so a legacy code page
   cannot corrupt it (cmd.exe, Git Bash, PowerShell 7), the Portuguese catalog stays ASCII, and a
   name from a report with an accent is still shown correctly. This does not make the bytes the same
   in every shell: Windows PowerShell 5.1 still rewrites the file as UTF-16 with a byte-order mark,
   which browsers read correctly (design ADR-7). The alternative is UTF-8 with accents, which reads
   better in the source but depends on how the user redirects.
4. **Per-day counts: internal only, or in the JSON too?** The timeline needs messages per day by
   situation, which the `Summary` does not hold. Recommended: add them to `Summary` (internal) and
   **not** to the `--json` documents in this spec: adding a field to a public contract is a decision
   of its own, and someone drawing their own chart may want it, but nobody has asked. How a report
   that spans two days is split (whole to its first day, or shared by the days it touches) is closed
   in the design; recommended: the whole report to the day its period begins, so that a daily report
   from midnight to midnight is exact and the sum of the days is the total.
5. **A `--output FILE` flag.** Non-goal of 006, and `> report.html` works. With question 3
   answered as recommended the shell stops mattering, so recommended: **still no flag**.
6. **Title and a name on the page.** The page shows the domain and the period. It should not invite a
   logo or a custom title (they would be more text to escape and to translate). Recommended: none.

## Resolved decisions

1. **One static file, no script, no network** (the roadmap line and the permanent non-goals).
2. **The interface was decided from a mockup on 2026-10-28:** the verdict first, each rule as a
   meter against its limit (alternative B), the stacked bar of the message mix (from C), WebVigil's
   visual language, a timeline drawn from the reports' own dates in inline SVG. The mockup is
   reconfirmed and attached to the design before any HTML is written.
3. **The page judges nothing.** It renders the `Verdict` of 005 and the `Summary` of 004.
4. **Escaping lives in one module.** No other module builds markup.

## Tests

Following [specs/README.md](../README.md#how-a-spec-is-tested):

- **Unit tests, no CLI:** the renderer is called with built `Summary` and `Verdict` values and the
  returned string is parsed with `html.parser` to check its structure.
- **Hostile input:** the attack strings of RF-06 in every field; the document is checked, never
  just searched for a substring.
- **CLI:** `main(argv)` with `capsys`, the exit codes asserted, `--html` with `--json` refused.
- **Parity:** the facts of the page equal the facts of the text format for the same run.
- **Accessibility and contrast:** the palette pairs are checked in a test against 4.5:1; the
  headings, `lang` and table headers are checked on the parsed document. The visual check at 390
  and 1280 px is done in a real browser during the interface stage.
- **Synthetic only:** every report is built in the test from the ranges in RNF-07.
- **Quality gate last:** `ruff` → `black --check` → `mypy` → `pytest --cov`, with its real result
  recorded in `tasks.md`.
