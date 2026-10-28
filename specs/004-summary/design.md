---
feature: Summary — per sender and per situation, failures highlighted, and the first command
status: done
date: 2026-10-27
related:
  - 004-summary/requirements.md
  - 003-config-and-senders/design.md
  - 002-report-ingestion/design.md
origin: conception
---

# 004 — Summary — design

## Overview

Two new modules, one small change to `config.py` and the command wired in `cli.py`:

```text
paths ──ingest──▶ IngestionResult ─┐
(002)                              ├─summarize──▶ Summary ──render_summary──▶ text
file/--domain ──resolve──▶ Config ─┘   (RF-01..06)   │          (RF-06, RF-09)
(RF-08)                                              └──────────▶ spec 005 reads it (RNF-03)
```

- **summarize** adds up the records of an `IngestionResult` under a `Config` into a frozen
  `Summary`: totals per situation, one row per sender, one entry per failing source, the period,
  the policy and what was left out. It holds the *complete* data; it prints and limits nothing.
- **render_summary** turns a `Summary` into text: the five sections, the 80-column layout, the
  limits of 10, the shares. All the English text of the command lives in `render.py`, so spec `006`
  replaces one module (Resolved decision 5).
- **cli.py** gets the `summary` subcommand: it resolves the domain and the configuration (RF-08),
  calls `ingest`, `summarize` and `render_summary`, and maps every refusal to a line on standard
  error and an exit code (RF-10). It contains no counting and no layout.

`summarize` is one pass over the records, with memory proportional to the number of distinct
sources (RNF-09). It does no I/O, prints nothing and never raises on report content, which is
already sanitized (RNF-03, RNF-08).

## Module layout

```text
src/mailvigil/
  summary.py       # Situation, Counts, SenderRow, FailingSource, Period, Summary,
                   # classify, summarize                                       (RF-01..05)
  render.py        # render_summary, no_reports_message, format_share and the English text
                   #                                                           (RF-06, RF-09, RF-10)
  config.py        # + check_domain: the domain rules of the file, now callable on a flag value
  cli.py           # + the `summary` subcommand, resolve_config, the exit codes (RF-07, RF-08, RF-10)
tests/
  test_summary.py          # RF-01..05, RF-11, RNF-04, RNF-05, RNF-09
  test_render.py           # RF-04, RF-05, RF-06, RF-09, RF-11, RNF-08
  test_cli_summary.py      # RF-07, RF-08, RF-10, through main(argv) and capsys
  test_config.py           # + check_domain
  test_smoke.py            # `main([])` now prints the help and exits 2 (RF-07)
```

The dependency points one way: `cli → render → summary → senders → config → text`, and
`summary → reports.model`. `render` imports from `summary` and `reports.errors` (the `Reason` it
translates) and never the reverse, so `005` can import `summary` without pulling in any text.
`summary.py` and `render.py` are modules, not a package: each is one idea in a few hundred lines.

## Data model

All types are `@dataclass(frozen=True, slots=True)` and every collection is a tuple (RNF-04).

```python
class Situation(StrEnum):
    OK = "ok"              # DKIM and SPF both evaluated pass
    FRAGILE = "fragile"    # exactly one of them
    FAILING = "failing"    # neither

class Counts:
    ok: int = 0
    dkim_only: int = 0     # fragile: DKIM passed, SPF did not   (Resolved decision 7)
    spf_only: int = 0      # fragile: SPF passed, DKIM did not
    failing: int = 0
    # properties: fragile = dkim_only + spf_only;  total = ok + fragile + failing

class SenderRow:
    outcome: Outcome                   # from 003: KNOWN, FOREIGN_DOMAIN, FAILING_SIGNATURE, UNKNOWN
    service: str                       # the service name when KNOWN, else ""
    source_ip: str                     # the IP when not KNOWN, else ""
    selectors: tuple[str, ...]         # configured selectors seen on a non-KNOWN row, sorted
    counts: Counts

class FailingSource:
    outcome: Outcome
    service: str                       # as in SenderRow
    selectors: tuple[str, ...]         # as in SenderRow, for this source only
    source_ip: str                     # always set: the IP the failing messages came from
    messages: int                      # failing messages, at least 1
    dkim: tuple[str, ...]              # reasons seen, sorted: "fail", "none", "unaligned"
    spf: tuple[str, ...]               # same vocabulary
    override_reasons: tuple[str, ...]  # receiver override types, sorted, unique, comments dropped

class Period:
    begin: datetime                    # earliest `begin`, UTC
    end: datetime                      # latest `end`, UTC
    first_day: date                    # the UTC day `begin` falls on
    last_day: date                     # the last UTC day any report touches (see ADR-3)
    days_spanned: int                  # first_day to last_day, inclusive
    days_with_reports: int             # days in that span touched by at least one report

class Summary:
    domain: str
    selectors_configured: int          # len(config.senders)
    reports: int
    reporters: int                     # distinct reporting organizations, as given
    period: Period | None              # None only when there are no reports
    policy: PolicyPublished | None     # the latest report's, None only when there are no reports
    earlier_p: tuple[str, ...]         # other `p` values seen in the period, oldest first
    totals: Counts
    recognized_messages: int           # messages of KNOWN records
    senders: tuple[SenderRow, ...]     # every row, ordered: total desc, label asc
    failing: tuple[FailingSource, ...] # every failing source, ordered: messages desc, label asc
    skipped: tuple[SkippedFile, ...]   # ordered by path
    skipped_by_reason: tuple[tuple[Reason, int], ...]   # count desc, reason value asc
    duplicates: int
    other_domain: int
```

`Summary` carries no printable text: not a label, not a percentage, not a plural (RNF-03). Names and
IPs are data and are already sanitized. The label a row prints (`IP (foreign domain)`) is
`render.py`'s. `earlier_p` non-empty is "the policy changed during the period" (RF-03), so there is
no separate flag to keep in step with it.

## Components

### summary.py — classification (RF-01)

`classify(record: Record) -> Situation` is public, so the rule is tested alone. A mechanism passes
when `value.strip().lower() == "pass"`; empty, `fail` and anything else do not (RF-01, Resolved
decision 13). DKIM and SPF are read from `record.dkim_evaluated` and `record.spf_evaluated`, never
from the raw blocks, and `disposition` and the override reasons play no part (Resolved decision 1).

### summary.py — `summarize` (RF-02 to RF-05)

`summarize(result: IngestionResult, config: Config) -> Summary`. One pass over
`result.reports` and, inside each, over `report.records`, with these accumulators (plain mutable
objects, private, frozen into the dataclasses at the end):

1. **Skip empty records.** `record.count == 0` adds nothing and creates nothing (RF-01).
2. **Classify and identify.** `situation = classify(record)`; `ident = identify_sender(record,
   config)` from 003.
3. **Row key.** `KNOWN` → `(KNOWN, service)`, so two selectors with one service name share a row;
   any other outcome → `(outcome, source_ip)`, so the same IP under two outcomes has two rows
   (RF-02). A non-`KNOWN` row never gets a service name (Resolved decision 9). The row tallies
   `ok`, `dkim_only`, `spf_only` and `failing` by `count`, and, when it is not `KNOWN`, collects
   `ident.selector` into a set.
4. **Totals.** The same tally, and `recognized_messages += count` when `KNOWN`.
5. **Failing sources.** When `situation is FAILING`, a second accumulator keyed by `(row key,
   source_ip)` adds `count`, the DKIM and SPF reasons of this record (below) and its override reason
   types. For a non-`KNOWN` row the key repeats the row's IP; for a `KNOWN` row it is how a service's
   failing messages are split by the IP they came from (RF-04).
6. **Reasons per mechanism (ADR-2).** For a record that is failing, each mechanism is read from the
   raw blocks: a block with result `pass` means the check ran and passed but DMARC did not count it,
   `unaligned`; blocks present and none passing is `fail`; no block is `none`.

After the loop, the accumulators become tuples and are sorted (RNF-05):

- `senders` by `(-counts.total, label, outcome.value)` where `label` is the service name or the IP;
- `failing` by `(-messages, label, source_ip, outcome.value)`;
- `skipped` by `str(path)`, and `skipped_by_reason` by `(-count, reason.value)`.

**Period (ADR-3).** For each report, `first = begin.date()` and `last = (end - 1 µs).date()` when
`end > begin`, else `begin.date()`: the end of a period is exclusive, so a report that runs from
midnight to the next midnight touches one day, as one that ends at 23:59:59 does. Both datetimes are
already UTC and timezone-aware (002). The intervals are sorted and merged, and `days_with_reports`
is the sum of the merged lengths; `days_spanned` is `(max last - min first).days + 1`.

**Policy.** Reports are ordered by `(end, begin, reporter, report_id)`; the last one's
`PolicyPublished` is `policy`; `earlier_p` is the distinct `p` values of the others that differ from
the latest `p`, in that order. `reporters` is the number of distinct `report.reporter` strings, `?`
(absent) counted as one.

With no reports the result has zero totals and `period` and `policy` set to `None`; deciding that
this is an error is the command's (RF-10), as it is for `ingest` (002).

### render.py — text (RF-04, RF-05, RF-06, RF-09)

`render_summary(summary: Summary, config_source: str | None) -> str` returns the whole text, without
a trailing newline. `config_source` is the path as the command resolved it, `None` for "no file"; it
is run metadata, not part of the data. Sections, in order, separated by one blank line:

1. **Header.** `MailVigil summary for DOMAIN`, then `config`, `period`, `reports`, `policy` and
   `messages` lines with a 10-column key. With an empty selector map the `config` line is followed
   by one line saying no selectors are configured, so every sender is unrecognized, and pointing at
   the README's configuration section (RF-09).
2. **Situations.** `ok`, `fragile`, `failing`: count and share.
3. **Senders.** A table with the marker column (`!` when `counts.failing > 0`), the label, `ok`,
   `fragile`, `failing` and `total`. Every `KNOWN` row is shown (their number is the size of the
   owner's own map); of the other rows, the first 10 in `summary.senders` order are shown, then one
   line: `... and N other sources: M messages, F failing` (Resolved decision 12). The label is the
   service name for `KNOWN` and `IP (kind)` otherwise, with kind `unrecognized`, `foreign domain` or
   `failing signature`.
4. **Failing.** Title `! FAILING: M messages in N sources`, or `No failing messages.` when none. Two
   groups (`Recognized senders that fail`, `Unrecognized sources that fail`), each limited to 10
   with a remainder line `... and N other sources: M failing messages`; an empty group is not
   printed. Each source takes two lines: `  ! WHO` and `      IP  N messages  dkim: R, spf: R[;
   OVERRIDES]`. `WHO` is the service name or `unrecognized`, followed for the two selector kinds by
   `, foreign domain (selector s)` or `, failing signature (selector s)`. Several reasons for one
   mechanism are joined with `/`.
5. **Left out.** `skipped files`, `duplicates` and `other domains`, always printed. After the skipped
   count, the first 10 skipped files as `name: phrase` and a line with how many more.

**Helpers.**

- `format_share(part, whole) -> str` (ADR-5): `0%` for no part, `<0.1%` below one in a thousand,
  `99.9%` rather than `100.0%` when a part is short of the whole, `100%` only for the whole, one
  decimal otherwise.
- `_fit(text, width) -> str`: the text cleaned and cut to `width` with `...` (the cut keeps the line
  inside 80 columns, RF-09). Every dynamic string passes through `clean_text` here before it is
  placed in a line, so the file name of a skipped file, the path given to `--config` and any other
  text that did not come from a report or the configuration is inert (RF-05, RNF-08).
- A fixed phrase for every `Reason`, e.g. `FILE_TOO_LARGE` → `too large`, `NOT_A_REPORT` → `not a
  DMARC report`. A test iterates `Reason` and fails on a missing entry, so a reason added by a later
  spec cannot reach the output as a bare key.
- Number columns are as wide as their longest value or header, and the label column takes what is
  left of 80 columns, between 10 and 30 (ADR-6).

`no_reports_message(result: IngestionResult, domain: str) -> str` builds the standard-error text for
RF-10: the domain, the counts of skipped files per reason, duplicates and reports of other domains,
so the cause of an empty result is visible.

### cli.py — the command (RF-07, RF-08, RF-10)

```text
mailvigil [--version] summary PATH [PATH ...] [--config FILE] [--domain DOMAIN]
```

`build_parser()` adds a `summary` subparser (`paths` with `nargs="+"` and `type=Path`, `--config`
as a `Path`, `--domain` as a string); the subcommand is optional at the parser level so that `main`
can choose what a missing one means. `main(argv)`:

1. `args = parser.parse_args(argv)`. A usage error or `--version` raises `SystemExit`, as in 001.
2. No command: the help goes to standard error and the code is `2` (RF-07). This replaces 001's
   "no arguments exits 0", which was a skeleton behavior.
3. `summary`: `resolve_config(args.config, args.domain)` → `(Config, source)`; any `ConfigError` or
   conflict becomes a `_Refusal` carrying one line, printed to standard error with code `1`.
4. `result = ingest(args.paths, config.domain)`. No `result.reports` → `no_reports_message` on
   standard error and code `1`; nothing on standard output (RF-10).
5. `summary = summarize(result, config)`; `render_summary(summary, source)` to standard output; code
   `0` (RF-10: exit `0` means "an answer was printed", not "healthy").

**`resolve_config(config_path, domain)`** (RF-08), in this order:

1. `domain` given → `check_domain(domain, key="--domain")`; a `ConfigError` is refused with its
   reason.
2. `config_path` given → that file. Not given and `Path("mailvigil.toml").exists()` → that file
   (relative to the current folder; no parent and no home directory is searched). `exists()`, not
   `is_file()`, so a folder with that name is refused as unreadable by the loader instead of being
   silently ignored.
3. A file → `load_config(path)`; a `ConfigError` is refused naming the path. If `--domain` was also
   given and differs from the file's `domain`, the run is refused naming both; equal is fine
   (Resolved decision 11).
4. No file → `--domain` is required, else refused with the message "pass `--domain` or `--config`";
   with it, `Config(domain, MappingProxyType({}))` is built directly: an empty `[senders]` is a
   legitimate first run (003 RF-03), and `load_config` requires a file, so it is not reused here.

`source` is the display path of the file used, or `None`.

**Writing.** `_write(stream, text)` encodes the text with the stream's own encoding and
`errors="replace"`, decodes it back, and writes it with a newline, so a character the console cannot
encode becomes `?` and never raises (ADR-4).

### config.py — one public function

`check_domain(value: object, key: str = "domain") -> str` is the body of today's `_read_domain`
after the missing-key test: string type, ASCII, `normalize_domain`, then the host-name rules, with
the `ConfigError` carrying `key`. `_read_domain` keeps the "missing" check and delegates. Behavior
and the 003 tests do not change; the loader and the `--domain` flag now share one definition of a
plausible domain (ADR-7).

## Interfaces

| Contract | Shape |
|---|---|
| `mailvigil summary PATH... [--config FILE] [--domain DOMAIN]` | the command; summary on standard output, causes on standard error |
| exit codes | `0` a summary was printed; `1` it could not be made; `2` usage error. Provisional until `006` |
| `mailvigil.summary.summarize(result, config)` | `IngestionResult, Config -> Summary` |
| `mailvigil.summary.classify(record)` | `Record -> Situation` |
| `mailvigil.summary.Summary` and its parts | the frozen dataclasses above; the input of `005` and `006` |
| `mailvigil.render.render_summary(summary, config_source)` | `Summary, str \| None -> str` |
| `mailvigil.config.check_domain(value, key)` | `object, str -> str`; raises `ConfigError` |

Nothing here is a public contract yet: there is no release. The field names of `Summary`, the
vocabulary of `dkim` and `spf` reasons and the exit codes become one at the first version, which is
why the codes are kept provisional until `006`.

## ADRs

### ADR-1 — The `Summary` is complete; the limits belong to the renderer

**Decision.** `summarize` returns every row, every failing source and every skipped file. The limit
of 10 and its "and N more" lines are applied in `render.py`.
**Alternatives.** Cap inside `summarize`; add an `--all` flag now.
**Why.** The verdict (`005`) must see all the traffic, and `--json` (`006`) must print all of it. A
cap in the computation would make the JSON a lie or force a second code path. The cap exists to keep
the *terminal* readable, which is the renderer's concern (RNF-03, RNF-09, Resolved decision 12).
**Trade-off.** The `Summary` of a report flood holds many small objects. They are one per distinct
source, bounded by the input size that 002 already caps, and nothing is retained per message.
(RF-02, RF-04, RF-05)

### ADR-2 — Failing sources are explained per mechanism, from the raw blocks

**Decision.** For each failing source the output says, for DKIM and for SPF, `fail`, `unaligned` or
`none`, derived from the `auth_results` blocks of the record, not "what failed".
**Alternatives.** Print `dkim+spf fail` as the requirements first said; print the raw results.
**Why.** A record is `failing` only when *both* evaluated results are not `pass`, so "what failed"
would read the same on every line and tell the owner nothing. What differs, and what the owner acts
on, is the *reason*: a service that signs with its own domain passes DKIM and is `unaligned` (the
usual third-party case, fixed by a custom signing domain), a broken signature is `fail`, and a
sender with no signature is `none`. The blocks are already in the model (002).
**Trade-off.** A deviation from the first wording of RF-04, decided here and recorded in the
requirements. One source may show several reasons for one mechanism (`fail/none`), joined with `/`.
(RF-04)

### ADR-3 — The period is counted from merged day intervals, with an exclusive end

**Decision.** `days_with_reports` is the size of the union of `[first, last]` day intervals, one per
report, where `last` is the day of `end` minus one microsecond.
**Alternatives.** Build a `set` of every day each report touches; use `end.date()` as the last day.
**Why.** Reporters differ: some end a period at 23:59:59, others at the next midnight, and the
second would otherwise claim an extra day and make a gap look covered. A set is wrong for another
reason: a hostile report with a period of centuries is valid under 002 and would allocate a day per
entry, while interval merging is `O(n log n)` in the number of reports and uses constant memory per
interval (RNF-09). The span is then truthful, and the long period is shown as the odd fact it is.
**Trade-off.** A report that ends exactly at `begin` (zero length) counts for the day of `begin`,
a choice, not a measurement. (RF-03)

### ADR-4 — Make the text writable by encoding it, not by reconfiguring the stream

**Decision.** `_write` encodes with `stream.encoding` and `errors="replace"`, decodes and writes.
**Alternatives.** `sys.stdout.reconfigure(errors="replace")`; leave it to the platform.
**Why.** On a Windows console with a legacy code page, a configured service name such as
`Café ★` would raise `UnicodeEncodeError` halfway through the output and lose the summary.
`reconfigure` changes the process-wide stream and would leak into whoever calls `main` (a test, a
wrapper); encoding locally changes nothing outside the function and works on any stream with an
`encoding` attribute, falling back to UTF-8.
**Trade-off.** An unencodable character shows as `?`; the layout characters are ASCII, so only
names from the configuration can be affected. (RNF-08, RF-09)

### ADR-5 — Shares are integer arithmetic with two guards

**Decision.** `format_share` computes tenths of a percent as `(2000 * part + whole) // (2 * whole)`
(round half up, no float), then applies: no part is `0%`; a part with zero tenths is `<0.1%`; a part
short of the whole that rounds to 1000 tenths is `99.9%`; the whole is `100%`.
**Alternatives.** `f"{part / whole:.1%}"`.
**Why.** The float format rounds `0.04%` to `0.0%` and `99.97%` to `100.0%`, the two ways a failing
handful of messages disappears from a table whose job is to show it (RF-06). Integers also keep
the text identical across platforms and Python versions (RNF-05, RNF-06).
**Trade-off.** Two special cases in a function that would be one line. Each has its own test.
(RF-06)

### ADR-6 — A fixed 80-column layout, with widths taken from the data

**Decision.** Lines are built by padding to computed widths, ASCII only, with the label column
between 10 and 35 characters (the longest IPv4 address with the longest kind) and the number columns as wide as their longest value; anything wider
is cut by `_fit`.
**Alternatives.** A constant width per column; reading the terminal size; wrapping.
**Why.** A constant width breaks the first time a count has a digit more than the header. The
terminal size is not known when the output is piped, a log or a CI job, which is where this output
will often be read, and wrapping would make the failure lines hard to scan. A rule of "never more
than 80, cut with `...`" is simple and testable on the longest value (RF-09, RNF-05).
**Trade-off.** A very long service name is shown cut (the complete name stays in the `Summary`).
(RF-09)

### ADR-7 — Share the domain rules by making them callable

**Decision.** `check_domain` becomes public in `config.py` and the command uses it for `--domain`.
**Alternatives.** Duplicate the checks in `cli.py`; build a throwaway TOML string and load it;
move the rules to `text.py`.
**Why.** "A plausible domain" is a security-adjacent rule that must have one definition, the same
argument as 003's ADR-4. The throwaway-TOML route re-parses a string to validate one value and its
errors name the wrong thing. `text.py` is about characters and equality, and the host-name grammar
is the configuration's rule.
**Trade-off.** One more public name in `config.py`, behind a refactor that the existing tests
cover. (RF-08)

## Impact on existing code

- **New files:** `src/mailvigil/summary.py`, `render.py` and three test files.
- **Changed:** `config.py` (`check_domain` extracted; behavior-neutral), `cli.py` (the subcommand,
  `resolve_config`, `_write`; `--version` unchanged).
- **A test that changes on purpose:** `test_smoke.py::test_no_arguments_exits_zero` asserted the
  skeleton's `main([]) == 0`. It becomes "no command prints the help to standard error and returns
  `2`" (RF-07).
- **`pyproject.toml`:** no change; `dependencies` stays empty.
- **Docs:** the README's status rows (Summary: library and command built; Quick start gains
  `mailvigil summary` with an invented example; the exit codes stay "not defined yet"),
  `docs/stack.md` (`argparse` subcommands, `datetime`, `dataclass` properties, integer rounding),
  `CLAUDE.md` (the two modules and the command in the architecture block and the status paragraph).
  `/atualizar-docs` at the end. The `specs/README.md` row moves to `in progress`, then `done`.
- **The site repository's script** is not changed.

## Risks

1. **The layout is a first version.** The sketch is validated by hand on the maintainer's own
   reports before the spec closes (they never enter the repository). If a real run shows a
   table that does not read well, the change is in `render.py` alone, which is the point of
   ADR-1 and RNF-03.
2. **`unaligned` can be wrong for an exotic record.** A `pass` block under a different domain is
   what alignment failure looks like in a report; but a receiver that omits the blocks of a failing
   record shows `none` for a signature that existed. The text states what the *report says*, and
   nothing in the output claims the sender did or did not sign.
3. **A flood of single-message sources** (a spoofing burst) makes `Summary.failing` long. The
   terminal shows 10 and a remainder with the failing message count, the data is complete for the
   JSON, and the memory is bounded by the input cap (ADR-1).
4. **`Identification` is narrow on purpose** (003, ADR-3): a `KNOWN` record can be `failing`
   (signature passed, not aligned). Row counts stay by situation, so this appears as the `!` on a
   recognized sender and as `unaligned` in its failing source, which is the finding RF-04 wants.
5. **The command name is not final.** `005` may fold the verdict into the same output (Resolved
   decision 8). The command is a thin wiring of three calls, so a rename or a merge costs a few
   lines and a test update.
6. **Windows paths and encodings.** The tests write files with `tmp_path` and explicit bytes, assert
   on text with `\n` only, and use a stream with a legacy encoding to prove ADR-4.

## Test strategy

Following [specs/README.md](../README.md#how-a-spec-is-tested): the logic is called with built
inputs, the CLI through `main(argv)` and `capsys`. Records and reports are built with the
dataclasses, the files in `tmp_path`; domains, services and addresses are invented (RNF-07:
`example.com`, `192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24`, `2001:db8::/32`).

| Requirement | Tests |
|---|---|
| RF-01 | both pass is `ok`; one is `fragile` (and `dkim_only`/`spf_only` split correctly); neither, empty and `error` are `failing`; `PASS` and ` pass ` count; `disposition` and an override reason change nothing; a record with count 0 adds nothing and makes no row |
| RF-02 | two selectors with one service share a row; one `KNOWN` service from two IPs is one row; one IP as `FOREIGN_DOMAIN` and `UNKNOWN` is two rows and neither has a service; a non-`KNOWN` row lists its selectors sorted; the same reports reversed give an equal `Summary`; 12 unrecognized rows print 10 and a remainder with its failing count |
| RF-03 | totals per situation and `recognized_messages`; period from earliest begin to latest end; a gap day lowers `days_with_reports`; a report ending at the next midnight touches one day; a report across midnight touches two; a century-long period is summarized in constant time and shown; one policy shows `p`, `sp` and `pct`; a changed `p` fills `earlier_p`, oldest first; two reporters, one repeated; no reports gives zero totals and `None` period and policy |
| RF-04 | a source with failing messages appears once per IP; recognized sources come before unrecognized ones; `dkim: unaligned` when a block passed under another domain; `fail` and `none` likewise; override types shown and the comment never; a `KNOWN` service with a failing IP is in the first group; a foreign selector shows its name; 12 failing sources print 10 and a remainder; none prints `No failing messages.`; a table row with failing starts with `!` |
| RF-05 | skipped, duplicate and other-domain counts, also at zero; counts per reason; 12 skipped files print 10 and "2 more"; a file name with an escape sequence is shown cleaned; a phrase exists for every `Reason` |
| RF-06 | `<0.1%` for 4 in 10000; `0%` for none; `99.9%` for 9997 of 10000; `100%` only for the whole; `95.4%` for 11900 of 12480; a count is printed beside every percentage |
| RF-07 | no path is a usage error with code 2 before any file is read; `--version` still works; no command prints the help and returns 2 |
| RF-08 | `--config` loads the file; an explicit missing file is refused and `mailvigil.toml` is not tried; `mailvigil.toml` is read from the current folder (`monkeypatch.chdir`) and named in the header; none gives `config  none` and an empty map; `--domain` alone works; `--domain` equal to the file's passes, a different one is refused naming both; an invalid `--domain` is refused with the loader's reason; neither source is refused with the hint |
| RF-09 | the sections come in order; no line is over 80 columns, also with a 100-character name, an IPv6 address and a count of `10**12`; the output is ASCII apart from names; a name the stream cannot encode prints `?` and does not raise (a stream with `encoding="ascii"`); the empty-map note appears |
| RF-10 | summary printed is code 0 even with failing traffic; each refusal prints one line on standard error, nothing on standard output, code 1, no traceback; no kept report prints the counts of what was skipped and filtered; the README and the output do not call the codes stable |
| RF-11 | the hostile and mistaken rows above are the RF-11 list |
| RNF-03 | `summarize` and `render_summary` are called with no CLI; `Summary` holds no `str` built for display (a test checks the fields against the dataclass definition) |
| RNF-04 | `Summary` and its parts raise `FrozenInstanceError` on assignment and expose only tuples |
| RNF-05 | the same reports in three orders, and the same text twice, are equal |
| RNF-09 | 50,000 synthetic records over 200 sources give 200 rows, with no per-message structure retained (checked by the size of `Summary`, not by timing) |
| 003 | the unchanged 003 suite passes after `check_domain` is extracted |

The quality gate (`ruff` → `black --check` → `mypy` → `pytest --cov`) closes each stage of
`tasks.md`, with its real result recorded.
