---
feature: Summary — per sender and per situation, failures highlighted, and the first command
status: done
date: 2026-10-27
related:
  - 001-foundation/requirements.md
  - 002-report-ingestion/requirements.md
  - 003-config-and-senders/requirements.md
origin: conception
---

# 004 — Summary

## Context and problem

After [002](../002-report-ingestion/) and [003](../003-config-and-senders/) the library can read a
pile of attachments into typed records and say, for each record, which configured service signed it.
Nothing yet adds the records up, and no command runs any of it: `mailvigil` still answers only
`--version`. A person with two hundred reports still has the wall of numbers MailVigil exists to
replace.

This spec adds the step between "typed records" and "an answer": the **summary**. It groups the
traffic of one domain by *sender* and by *situation*, and puts the problems where they cannot be
missed. It is also the first spec with a command, so it settles the questions 003 left to "the
command": where the configuration file and the domain come from, and what happens when either is
missing or wrong.

Two splits carry the whole summary:

- **Situation**, from what the receiver reported about authentication: `ok` (DKIM and SPF both
  aligned and passing), `fragile` (only one of them), `failing` (neither). DMARC passes when either
  one does, so a `fragile` sender still gets through today, but it is one expired key or one changed
  IP away from `failing`. That is what makes it worth a column of its own.
- **Sender**, from 003: a *recognized* sender is a configured service whose signature passed under
  the owner's domain; everything else is *unrecognized*. A recognized sender that fails is a service
  the owner forgot to fix, and it would be blocked under `p=reject`. An unrecognized source that
  fails may be a stranger spoofing the domain or a service nobody wrote down, and the report cannot
  tell which. The summary shows both, apart, and never guesses.

The summary does **not** say whether it is safe to move to `p=reject`. That is the verdict (spec
`005`), and it needs a declared criterion. What this spec owes the verdict is the figures it will be
built on (period, days covered, totals per situation, the share of recognized traffic), computed
once and exposed as data.

The repository is public and nothing is published yet. The output format below is a first version,
validated by hand against the maintainer's own reports (which never enter the repository); the
text language, `--json` and the exit-code contract arrive with `006`.

## Goals

- **Add up the records of one domain** into an immutable, typed `Summary`: totals, per situation, per
  sender, plus what was left out.
- **Make failures impossible to miss**: every source with failing messages is listed, recognized
  senders apart from unrecognized sources, ahead of the rest of the detail.
- **Make unrecognized traffic easy to name**: the owner can read the table, see which sources are
  still unrecognized, and add their selectors to `[senders]`.
- **Hand spec `005` its inputs** (period, days with reports, totals per situation, per-sender
  counts, the published policy) without it recomputing anything.
- **Wire the first command**, `mailvigil summary`, from paths to text, with the configuration and
  the domain resolved explicitly and every refusal explained.

## Non-goals

- Saying whether it is safe to move to `p=reject`, any threshold, minimum window or minimum volume:
  spec `005`. The summary never uses the words "safe" or "ready".
- `--json`, the stable exit-code contract, the Portuguese text, locale-aware numbers: spec `006`.
  This spec keeps its text in one place so `006` can replace it (see RNF-03).
- Color, box-drawing characters, terminal control codes or a width wider than 80 columns.
- Looking up anything outside the files: reverse DNS, geolocation, who owns an IP (offline is the
  product promise), or grouping IPs into ranges.
- Identifying a sender by SPF domain or IP (003, Resolved decision 7).
- Trends: per-day breakdowns, comparing two periods, a per-reporter table (only the count of
  reporters is shown).
- Exporting files (HTML, CSV) or any output besides standard output and standard error.
- Creating or editing the configuration file (`mailvigil init` and the like).

## Personas

- As the **owner of a domain who is deciding whether to enforce DMARC**, I want to see in one screen
  who sends as my domain, how much of it passes, and exactly what fails, so that I act on the
  failures and not on a hunch.
- As a **first-time user with no configuration**, I want to run the command with only my domain and
  get a useful table where everything is "unrecognized", so that I learn what to put in `[senders]`
  from the output itself.
- As a **contributor to the next specs**, I want one `Summary` I can build from `Report` values and
  a `Config`, so that the verdict and the JSON output are unit-tested without XML, files or a
  terminal.

## What the output looks like

A sketch with invented data (documentation IP ranges, `example.com`). The sections, their order and
the failure markers are the contract of this spec; the exact spacing is not.

```text
MailVigil summary for example.com
  config    mailvigil.toml (2 selectors)
  period    2026-10-01 to 2026-10-28 (27 of 28 days have a report)
  reports   54 from 4 reporters
  policy    p=none, pct=100
  messages  12480 (12300 from recognized senders, 98.6%)

Situations
  ok         11900   95.4%
  fragile      540    4.3%
  failing       40    0.3%

Senders
  sender                             ok  fragile  failing   total
! Example Mailer (newsletters)     9100      300       12    9412
  Example Mail (staff mailboxes)   2700      188        0    2888
! 198.51.100.77 (unrecognized)      100       52        3     155
! 203.0.113.50 (foreign domain)       0        0       25      25

! FAILING: 40 messages in 3 sources
  Recognized senders that fail
  ! Example Mailer (newsletters)
      192.0.2.10  12 messages  dkim: unaligned, spf: fail
  Unrecognized sources that fail
  ! unrecognized, foreign domain (selector newsletter)
      203.0.113.50  25 messages  dkim: unaligned, spf: none
  ! 198.51.100.77
      3 messages  dkim: fail, spf: fail; forwarded

Left out of these numbers
  skipped files  2 (1 too large, 1 not a report)
  duplicates     3
  other domains  0
```

## Functional requirements

### RF-01 — The situation of a record

- **Given** a record whose `policy_evaluated` DKIM and SPF are both `pass`
  **When** it is classified
  **Then** its situation is `ok`.
- **Given** a record where exactly one of the two is `pass`
  **When** it is classified
  **Then** its situation is `fragile`.
- **Given** a record where neither is `pass` (`fail`, empty, or any other value)
  **When** it is classified
  **Then** its situation is `failing`. A result that is missing is not proof of a pass, and reading
  it as a failure is the safe direction (Resolved decision 13).
- **Given** the values `PASS`, ` pass ` or `Pass`
  **When** they are compared
  **Then** they count as `pass`: case and surrounding spaces do not matter.
- **Given** a record
  **When** it is classified
  **Then** only the two evaluated results decide: `disposition` and the override reasons do not
  change the situation (under `p=none` everything is delivered, which says nothing about
  authentication). The override reasons are kept to be shown (RF-04).
- **Given** a record with `count` zero
  **When** the report is summarized
  **Then** it adds nothing and creates no row.

### RF-02 — Group by sender

- **Given** records identified as `KNOWN` (003)
  **When** they are grouped
  **Then** there is one row per service name, whatever the selector and the source IP; two
  selectors that map to the same name share a row.
- **Given** records that are not `KNOWN` (`FOREIGN_DOMAIN`, `FAILING_SIGNATURE`, `UNKNOWN`)
  **When** they are grouped
  **Then** there is one row per source IP and kind, labeled with the IP and a short note on the
  kind (`unrecognized`, `foreign domain`, `failing signature`); the same IP under two kinds has two
  rows. Such a row never carries a service name (Resolved decision 9).
- **Given** a row
  **When** it is built
  **Then** it carries the message counts for `ok`, `fragile` and `failing`, and their total.
- **Given** the same set of reports in any order
  **When** the rows are ordered
  **Then** the order is the same: total messages descending, ties by label ascending (RNF-05).
- **Given** more than 10 unrecognized rows
  **When** the table is printed
  **Then** the 10 with the most messages are shown, followed by one line with the number of other
  sources, their messages and how many of those messages are failing. The limit may hide a row, but
  never its failing messages: they stay counted in that line and in the totals (see Resolved
  decision 12).

### RF-03 — Totals, period and policy

- **Given** the reports kept by `ingest`
  **When** the summary is built
  **Then** it states the total messages, the totals per situation with their share, the number of
  reports and of distinct reporting organizations.
- **Given** the same reports
  **When** the period is built
  **Then** it runs from the earliest `begin` to the latest `end`, in UTC dates, and it states how
  many of the calendar days in that span have at least one report (a report that crosses midnight
  counts for each day it touches). Missing days are a fact the verdict will need.
- **Given** the reports
  **When** the recognized share is built
  **Then** it is the messages of `KNOWN` records over all messages, with both numbers shown.
- **Given** reports whose published policy is the same
  **When** the policy line is built
  **Then** it shows `p`, and `sp`, `np` and `pct` when present, from the most recent report.
- **Given** reports whose `p` differs between them (the owner changed the policy in the period)
  **When** the policy line is built
  **Then** it shows the latest and says that the policy changed during the period, with the
  earlier values.
- **Given** a `Summary`
  **When** another spec reads it
  **Then** every figure above is a field of the dataclass, not text to be parsed.

### RF-04 — Failures are highlighted

- **Given** records in the `failing` situation
  **When** the failures section is built
  **Then** every source with failing messages is listed, once, with the failing message count, its
  source IP, and why each mechanism did not count, most messages first. A failing record failed
  both by definition, so the useful detail is the reason per mechanism: `fail` (a signature or
  check ran and failed), `unaligned` (it passed, but for a domain other than the `From` domain, so
  DMARC did not count it) or `none` (no signature or check was reported).
- **Given** failing sources
  **When** they are listed
  **Then** they are in two groups, in this order: **recognized senders that fail** (a configured
  service that would be blocked under `reject`) and **unrecognized sources that fail**. The second
  group is described neutrally; the summary does not call it an attack.
- **Given** a failing source whose records carry override reasons (`forwarded`, `mailing_list`…)
  **When** it is listed
  **Then** the reason types are shown next to it, without the receiver's free-text comment. The
  situation stays `failing`; the reason is information for the owner, and for the verdict.
- **Given** a recognized sender with a failing record
  **When** it is listed
  **Then** it appears in the first group even when its DKIM signature passed: the signature passed
  but DMARC did not count it (the alignment case of 003, ADR-3), which is the finding that matters.
- **Given** a source of kind `FOREIGN_DOMAIN` or `FAILING_SIGNATURE`
  **When** it is listed
  **Then** the configured selector involved is shown, so the owner can tell a copied selector from
  a broken one.
- **Given** more than 10 failing sources in a group
  **When** the section is printed
  **Then** the first 10 are shown, followed by one line with the number of other sources and their
  failing messages, so the section is never silently shortened.
- **Given** no failing message at all
  **When** the section is built
  **Then** it says so in one line, instead of disappearing.
- **Given** a row of the senders table with failing messages
  **When** the table is printed
  **Then** the row begins with `!`, so the marker survives a pipe, a log and a monochrome screen.

### RF-05 — What was left out

- **Given** the `IngestionResult`
  **When** the summary is built
  **Then** it states the number of skipped files, duplicate reports and reports of other domains,
  even when they are all zero (a line saying nothing was left out is information).
- **Given** skipped files
  **When** they are shown
  **Then** the counts per reason are shown, and the first 10 files with their reason, followed by a
  line with how many more. A file name is shown with its control and format characters removed,
  as every other text is (RNF-08): it comes from a folder listing, which 002 does not clean, and
  could carry a terminal escape sequence.

### RF-06 — A small number is never rounded away

- **Given** a share that is above zero and below 0.1%
  **When** it is printed
  **Then** it reads `<0.1%`, never `0.0%`.
- **Given** a share of exactly zero
  **When** it is printed
  **Then** it reads `0%`.
- **Given** a share that is below 100% but would round to `100.0%`
  **When** it is printed
  **Then** it reads `99.9%`: `100%` is printed only when every message is in it.
- **Given** any count
  **When** it is printed
  **Then** it is the exact integer, with no abbreviation (`12480`, not `12k`) and no separator, and
  a percentage is never printed without the count beside it.

### RF-07 — The command

- **Given** `mailvigil summary PATH [PATH ...] [--config FILE] [--domain DOMAIN]`
  **When** it runs
  **Then** it reads the files and folders as 002's discovery does, builds the summary and prints it
  to standard output (Resolved decision 8).
- **Given** no path
  **When** it runs
  **Then** it is a usage error with the usual message, before any file is read.
- **Given** `mailvigil --version`
  **When** it runs
  **Then** it still prints the version, as in 001.
- **Given** `mailvigil` with no command
  **When** it runs
  **Then** it prints the help and exits with the usage code.

### RF-08 — Where the domain and the configuration come from

- **Given** `--config FILE`
  **When** the command runs
  **Then** that file is loaded with 003's loader; if it is refused, the run stops with the loader's
  reason, and no other file is tried.
- **Given** no `--config` and a file named `mailvigil.toml` in the current folder
  **When** the command runs
  **Then** that file is loaded, and the header says so (Resolved decision 10). No other folder is
  searched: not the parents, not the home directory.
- **Given** no `--config` and no such file
  **When** the command runs
  **Then** the selector map is empty, and the header says `config  none`.
- **Given** `--domain DOMAIN`
  **When** it is read
  **Then** it is normalized and validated by the same rules as the configuration's `domain` (003
  RF-02); an invalid one is refused with the same reason.
- **Given** both a configuration `domain` and a `--domain` that differ after normalization
  **When** the command runs
  **Then** the run is refused, naming both values (Resolved decision 11). If they are equal, the run
  continues.
- **Given** no `--domain` and no configuration file (neither `--config` nor `mailvigil.toml`)
  **When** the command runs
  **Then** the run is refused with a message that says to pass `--domain` or `--config`.

### RF-09 — The text

- **Given** the summary
  **When** it is printed
  **Then** the sections come in this order: header, situations, senders, failures, left out; each
  with a title line, blank-line separated.
- **Given** any output
  **When** it is written
  **Then** every line is at most 80 columns, uses only ASCII for the layout (no box-drawing, no
  emoji), contains no color and no terminal control code, and aligns its columns.
- **Given** a service name or a label wider than its column
  **When** it is printed
  **Then** it is cut with `...`; the complete name is still the one in the `Summary`.
- **Given** a configured service name with characters the terminal cannot encode
  **When** it is printed
  **Then** the run does not crash: the character is replaced with `?` (RNF-08).
- **Given** the numbers in the output
  **When** they are printed
  **Then** they use plain digits and a dot for the decimal; localizing them is spec `006`'s.
- **Given** a first run with an empty selector map
  **When** the header is printed
  **Then** it says that no selectors are configured, so every sender is unrecognized, and points to
  the README's configuration section.

### RF-10 — Refusals and the provisional exit codes

- **Given** a summary was printed
  **When** the command ends
  **Then** the exit code is `0`, even when there is failing traffic: whether the situation is
  acceptable is the verdict's call, not the summary's.
- **Given** a configuration that is refused, an invalid or conflicting domain, or no domain at all
  **When** the command runs
  **Then** nothing is written to standard output, one line naming the cause goes to standard error
  (no traceback), and the exit code is `1`.
- **Given** no report kept for the domain (nothing found, every file refused, or all of another
  domain)
  **When** the command runs
  **Then** nothing is written to standard output, standard error says what was read, skipped and
  filtered out so the cause is visible, and the exit code is `1`.
- **Given** a usage error
  **When** it happens
  **Then** the exit code is `2`, argparse's own.
- **Given** the codes above
  **When** the README is written
  **Then** they are not documented as stable: they are provisional until spec `006` fixes the
  contract.

### RF-11 — Hostile and mistaken input is tested, not assumed

- **Given** the test suite for this spec
  **When** it runs
  **Then** it contains, at least: a record with zero messages; an empty and an upper-case evaluated
  result; one IP under two kinds; two selectors of the same service; more unrecognized sources than
  the limit with one failing source among the small ones; a share between 0 and 0.1%; a policy that
  changed during the period; the same reports in a different order; a report that crosses
  midnight; a report whose period is absurdly long; a service name wider than its column and one
  the stream cannot encode; a conflicting domain; a missing `--config` file; no reports kept; and
  a skipped file whose name carries an escape sequence (shown cleaned). Each one expects the
  stated rows, text or refusal.

## Non-functional requirements

### RNF-01 — Standard library only

- **Given** the project at any commit
  **When** `[project].dependencies` is read
  **Then** it is still empty: the layout is plain `str` formatting, with no table library.

### RNF-02 — Read-only and offline

- **Given** any input
  **When** the command runs
  **Then** it reads the paths and the configuration, writes only to standard output and standard
  error, and touches no network.

### RNF-03 — Computation apart from text

- **Given** the layer
  **When** it is read
  **Then** `summarize` takes an `IngestionResult` and a `Config` and returns a frozen `Summary`
  with no printable text; a separate renderer turns the `Summary` into lines, and the command only
  wires. Spec `006` replaces the renderer (language, `--json`) without touching the computation,
  and spec `005` reads the `Summary` without rendering anything.

### RNF-04 — Typed and immutable

- **Given** the model
  **When** `mypy` runs in strict mode
  **Then** it passes, and `Summary` and its parts are frozen dataclasses with tuples, never lists
  or dicts exposed.

### RNF-05 — Deterministic

- **Given** the same reports, in any order, and the same configuration
  **When** they are summarized and rendered twice
  **Then** the `Summary` and the text are equal. Nothing depends on the clock, the locale or the
  order of discovery.

### RNF-06 — Fits the Python floor

- **Given** the Python floor `3.12` set in [001](../001-foundation/)
  **When** the layer is written
  **Then** it uses nothing newer, and the CI matrix (3.12 and the newest stable) passes.

### RNF-07 — Synthetic fixtures only

- **Given** the tests and the docs
  **When** they need a report, an address or a domain
  **Then** they use `example.com`, `example.org`, `example.net` and the documentation ranges
  `192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24` and `2001:db8::/32`. No real report, IP or
  domain of the maintainer enters the repository, the specs or the README.

### RNF-08 — Safe to print

- **Given** the text of a report or of the configuration
  **When** it reaches the output
  **Then** it is already sanitized (002 RF-05, 003 RF-05) and the summary adds no raw text of its
  own; writing never raises an encoding error, whatever the console's code page: what cannot be
  encoded becomes `?`.
- **Given** text that does not come from a report or the configuration (a file name from a folder
  listing, the path given to `--config`)
  **When** it reaches the output
  **Then** the renderer cleans it with the shared `clean_text` first.

### RNF-09 — One pass

- **Given** many records
  **When** they are summarized
  **Then** the work is one pass over them with memory proportional to the number of distinct
  sources, not to the number of messages, and the printed output is bounded by the limits of
  RF-02, RF-04 and RF-05.

## Open questions

None. Questions 1 to 7 were answered on 2026-10-27 (the maintainer accepted the recommendations)
and are Resolved decisions 7 to 13.

## Resolved decisions

1. **The situation is what the receiver evaluated**, not a re-check of the DKIM and SPF blocks. The
   receiver judged alignment under the published policy, and nothing can be re-verified offline.
2. **The summary is data first** (RNF-03): `Summary` is the contract for `005` and `006`, and the
   text is one renderer among others.
3. **The summary does not judge.** No "safe", "ready", "attack" or "spoofing" appears in the
   output: it states counts, kinds and what failed, and the criterion is the verdict's (spec
   `005`).
4. **Failures come with the table and again apart.** The marker in the table is for scanning, the
   section for acting; the section never depends on color.
5. **English only in this spec.** The text is in one place so `006` can add Portuguese and `--json`
   without a second implementation of the summary.
6. **Exit codes are provisional** (RF-10) and `0` does not mean "healthy", only "an answer was
   printed".
7. **`fragile` is one bucket in the table.** The `Summary` also keeps the DKIM-only and SPF-only
   counts (an SPF-only pass is the more fragile, since forwarding breaks SPF), so `005` and the
   JSON can use the difference without a new pass.
8. **The command is `mailvigil summary PATH...`.** When `005` lands it chooses between adding the
   verdict to this output and a sibling `verdict` command; nothing is a contract before `0.1`.
9. **A failing signature does not name the service.** A spoofer can sign badly with the owner's
   `d=` and a copied selector and the report looks identical, so the source is shown as
   `failing signature` with the selector. Naming it later is one change; a wrong name shown as
   fact is hard to take back.
10. **`mailvigil.toml` in the current folder is read without being asked**, and the header always
    says which file was used or `none`, so it is never invisible. No other folder is searched.
11. **`--domain` and the configuration's `domain` that disagree are refused.** The selector map is
    trusted under the configured domain, so a silent override would change who is named as
    legitimate (the reason 003 makes unknown keys errors).
12. **Lists stop at 10, and the limit hides rows, never failures.** Unrecognized table rows,
    failing sources per group and skipped files each show 10 and then one line with the rest and,
    for traffic, how many of its messages fail. The complete data is in the `Summary` and, later,
    in `--json` (006). An `--all` flag is not added now.
13. **A missing evaluated result counts as not passing**: `failing` when both are missing,
    `fragile` when one passes. It is the safe direction for a decision about blocking mail; a
    fourth state `unclear` would have no room in the table and the verdict would have to interpret
    it.

## Tests

Following [specs/README.md](../README.md#how-a-spec-is-tested):

- **Unit tests, no CLI:** `summarize` is called with built `IngestionResult` and `Config` values,
  and the renderer with a built `Summary`; classification, grouping, ordering, the limits and the
  rounding are asserted on values.
- **The CLI through `main(argv)` and `capsys`:** the sections of the output, standard error on each
  refusal, and the exit codes `0`, `1` and `2`; reports are synthetic files in `tmp_path`.
- **Hostile and mistaken input:** the cases of RF-11, each expecting the stated rows, text or
  refusal.
- **Synthetic only:** documentation IP ranges and invented domains (RNF-07).
- **Quality gate last:** `ruff` → `black --check` → `mypy` → `pytest --cov`, with its real result
  recorded in `tasks.md`.
