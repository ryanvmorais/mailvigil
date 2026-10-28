---
feature: Config and senders — a TOML file with the domain and a DKIM selector to service name map
status: done
date: 2026-10-27
related:
  - 003-config-and-senders/requirements.md
  - 002-report-ingestion/design.md
origin: conception
---

# 003 — Config and senders — design

## Overview

Two small modules and one shared helper, each testable alone:

```text
file ──load_config──▶ Config ─┐
                              ├─identify_sender──▶ Identification
Record (from 002) ────────────┘
        (RF-01..05, 07)              (RF-06)
```

- **load_config** turns one TOML file into an immutable `Config`, or raises `ConfigError` with a
  typed reason and the key it concerns.
- **identify_sender** takes one `Record` and a `Config` and says which configured service sent it,
  or why none could be named.
- **text.py** holds the rules about text and domain names that 002 and 003 must agree on, so there
  is one definition of "dangerous characters" and one of "the same domain".

Nothing prints, exits, reads `sys.argv` or the environment, or searches for a file (RNF-03); the
path is an argument. The file is read once, capped, as bytes, then decoded and parsed by `tomllib`
(standard library since 3.11, inside the 3.12 floor; RNF-01). Nothing in it is interpolated or
included (RNF-02).

## Module layout

```text
src/mailvigil/
  text.py          # clean_text, has_dropped_characters, normalize_domain, is_within_domain
  config.py        # ConfigReason, ConfigError, Config, load_config          (RF-01..05, RF-07)
  senders.py       # Outcome, Identification, identify_sender                (RF-06)
  reports/parser.py   # _clean now delegates to text.clean_text (behavior unchanged)
  reports/ingest.py   # the domain argument is normalized by text.normalize_domain
tests/
  test_text.py          # shared rules
  test_config.py        # RF-01..05, RF-07, RF-08 (loading)
  test_senders.py       # RF-06, RF-08 (identification)
```

`config.py` and `senders.py` are modules, not a package: each is one idea in a few hundred lines,
and `senders.py` is the only one that imports from `mailvigil.reports` (the `Record` type), so the
dependency points one way: `senders → config`, `senders → reports.model`, `reports → text`,
`config → text`. `cli.py` is not touched (Non-goal: the command is spec `004`).

## Data model

All types are `@dataclass(frozen=True, slots=True)` (RNF-04).

```python
class ConfigReason(StrEnum):
    UNREADABLE = "unreadable"                  # missing, no permission, folder, not a regular file
    FILE_TOO_LARGE = "file_too_large"          # over 64 KiB
    NOT_UTF8 = "not_utf8"
    MALFORMED_TOML = "malformed_toml"          # includes a document too deeply nested to parse
    UNKNOWN_KEY = "unknown_key"                # top-level key or table the format does not define
    MISSING_DOMAIN = "missing_domain"
    INVALID_DOMAIN = "invalid_domain"          # not a string, empty, not a plausible host name
    NON_ASCII_DOMAIN = "non_ascii_domain"      # write the xn-- form
    WRONG_TYPE = "wrong_type"                  # `senders` is not a table
    INVALID_SELECTOR = "invalid_selector"
    DUPLICATE_SELECTOR = "duplicate_selector"  # two keys differing only by case
    INVALID_SERVICE_NAME = "invalid_service_name"   # not a string, blank, too long, nested value
    FORBIDDEN_CHARACTER = "forbidden_character"     # control, format or separator in a name

class ConfigError(Exception):
    reason: ConfigReason
    key: str        # the key it concerns, cleaned and cut by clean_text; "" for file-level reasons
    detail: str     # short English, for logs

class Config:
    domain: str                     # normalized: lower case, no trailing dot
    senders: Mapping[str, str]      # selector (lower case) -> service name; a read-only view

class Outcome(StrEnum):
    KNOWN = "known"                         # a configured selector, passing, under the owner's domain
    FOREIGN_DOMAIN = "foreign_domain"       # a configured selector signed under someone else's domain
    FAILING_SIGNATURE = "failing_signature" # a configured selector, owner's domain, signature not "pass"
    UNKNOWN = "unknown"                     # no configured selector at all

class Identification:
    outcome: Outcome
    service: str = ""      # the service name when KNOWN, else ""
    selector: str = ""     # the configured selector that matched; "" when UNKNOWN
```

`ConfigError` has the same shape as 002's `ReportRefused` plus the `key` (RF-07), and `ConfigReason`
values are the stable keys spec `006` translates, so they never change once released. `key` is
passed through `clean_text` because it comes straight from the file: a mistyped key is arbitrary
text, and a terminal must never be asked to print it raw (RF-05's spirit applied to the error
itself).

`Config.senders` is a `types.MappingProxyType` over a dict built in sorted key order, so it cannot
be mutated and two loads of the same content compare equal whatever the order in the file
(RNF-05; equality of two proxies was checked on 2026-10-27). The dataclass is therefore not
hashable, and nothing hashes it. `Identification` carries no printable text: the label for an
unknown sender is spec `006`'s (Non-goals).

## Components

### text.py — rules shared with 002

- `DROPPED_CATEGORIES = frozenset({"Cc", "Cf", "Zl", "Zp"})`, moved from `reports/parser.py`.
- `clean_text(value, limit)`: the body of 002's `_clean` (tab, CR and LF become a space; dropped
  categories removed; stripped; cut to `limit`). `parser._clean` becomes
  `clean_text(value, MAX_TEXT)`; `MAX_TEXT` stays in `parser.py` and the existing parser tests pass
  unchanged.
- `has_dropped_characters(value) -> bool`: whether any character is in `DROPPED_CATEGORIES`.
  Tab, CR and LF are `Cc`, so they count: a configuration name with a line break is refused.
- `normalize_domain(value) -> str`: `value.strip().lower().rstrip(".")`, the exact expression
  `ingest` uses today. `ingest` calls it, so the configured domain and the argument to `ingest`
  can never disagree (RF-02).
- `is_within_domain(candidate, parent) -> bool`: after normalizing the candidate, true when it
  equals `parent` or ends with `"." + parent`. A plain suffix test would accept `notexample.com`
  (RF-06); the dot is the difference. `parent` is already normalized.

### Loader (RF-01 to RF-05, RF-07)

`load_config(path: Path) -> Config`, raising `ConfigError`. The checks run in this fixed order, and
the first failure is the one reported (RF-07):

1. `path.stat()`: any `OSError`, or not a regular file → `UNREADABLE`. (The `stat` check keeps a
   named pipe from blocking the run, as in 002's reader.)
2. Read with `path.open("rb")` and `read(MAX_CONFIG_BYTES + 1)`; more than `MAX_CONFIG_BYTES`
   (`64 * 1024`) → `FILE_TOO_LARGE`. The cap acts on the bytes actually read, not on the size from
   `stat`, which could change between the two calls. An `OSError` here → `UNREADABLE`.
3. `data.decode("utf-8-sig")`; `UnicodeDecodeError` → `NOT_UTF8`. The `-sig` variant drops a byte
   order mark, which Windows editors add and which `tomllib` would otherwise reject as an invalid
   statement (checked on 2026-10-27).
4. `tomllib.loads(text)`; `tomllib.TOMLDecodeError` → `MALFORMED_TOML`, with the parser's message
   as `detail` (it carries `at line L, column C`, checked on 2026-10-27). `RecursionError` →
   `MALFORMED_TOML` too: a 64 KiB file of nested arrays is within the size cap and raises it
   (checked on 2026-10-27), so it is caught and tested, not left to crash the run.
5. **Unknown keys.** The allowed top-level keys are `domain` and `senders`. Any other, in sorted
   order, → `UNKNOWN_KEY` with `key` set; `detail` suggests `difflib.get_close_matches(key,
   allowed, n=1)` when it finds one (RF-04).
6. **Domain.** Absent → `MISSING_DOMAIN`. Not a `str` → `INVALID_DOMAIN`. Then `normalize_domain`
   and, in order: non-ASCII → `NON_ASCII_DOMAIN`; empty, longer than 253, fewer than two labels, or
   a label that does not match `^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$` → `INVALID_DOMAIN`. The label
   rule excludes spaces, `:`, `/`, `@`, empty labels and control characters in one test, and a
   scheme or a path fails it because `:` and `/` are not letters, digits or hyphens.
7. **Senders.** Absent → empty map. Present but not a table → `WRONG_TYPE`. Otherwise the items are
   visited in the order `(key.lower(), key)`, so the first problem found does not depend on the
   order in the file (RNF-05):
   - the key must match `^[A-Za-z0-9._-]+$`, else `INVALID_SELECTOR`;
   - the lower-cased key must not have been seen, else `DUPLICATE_SELECTOR`;
   - the value must be a `str` (a nested table or a list is not) → else `INVALID_SERVICE_NAME`;
   - `has_dropped_characters(value)` → `FORBIDDEN_CHARACTER`;
   - the stripped value must be non-empty and at most `MAX_SERVICE_NAME = 100` characters, else
     `INVALID_SERVICE_NAME`. The stripped value is what is stored.

   A dotted key such as `a.b = "x"` is read by TOML as a nested table, so it lands in the "nested
   value" rule; a selector with a dot is written quoted (`"a.b" = "x"`), and the example in the
   README says so.
8. `Config(domain, MappingProxyType(dict_in_sorted_order))`.

Control characters in `domain` end up as `INVALID_DOMAIN` through the label rule, so `domain` needs
no separate check for RF-05; the names are the only values that can be printed later and have their
own reason.

### Identification (RF-06)

`identify_sender(record: Record, config: Config) -> Identification`. One pass over
`record.dkim` in document order, each block classified independently:

```text
for block in record.dkim:
    selector = block.selector.strip().lower();  signer = block.domain
    if not selector or not signer or selector not in config.senders:  skip      # RF-06, last bullet
    if not is_within_domain(signer, config.domain):   candidate FOREIGN_DOMAIN
    elif block.result.strip().lower() != "pass":      candidate FAILING_SIGNATURE
    else:                                             return KNOWN(first such block, immediately)
```

The domain test comes before the result test, so a foreign signature that also failed is reported
as foreign. The first block of each non-`KNOWN` kind is remembered, and when no block is `KNOWN`
the answer is, in this precedence, the first `FOREIGN_DOMAIN`, else the first `FAILING_SIGNATURE`,
else `UNKNOWN` (ADR-2). `service` is `config.senders[selector]` for `KNOWN` only. The function
does not read `dkim_evaluated`, `header_from` or the IP (ADR-3).

## Interfaces

| Contract | Shape |
|---|---|
| `mailvigil.config.load_config(path)` | `Path -> Config`; raises `ConfigError` |
| `mailvigil.config.Config` | `domain: str`, `senders: Mapping[str, str]` |
| `mailvigil.config.ConfigError.reason` | a `ConfigReason`; the stable key spec `006` translates |
| `mailvigil.config.MAX_CONFIG_BYTES`, `MAX_SERVICE_NAME` | module constants (64 KiB, 100) |
| `mailvigil.senders.identify_sender(record, config)` | `Record, Config -> Identification` |
| `mailvigil.senders.Outcome` | `KNOWN`, `FOREIGN_DOMAIN`, `FAILING_SIGNATURE`, `UNKNOWN` |
| `mailvigil.text.normalize_domain(value)` | `str -> str` |

The file format, as the README will show it (the `[senders]` keys below are invented):

```toml
domain = "example.com"

[senders]
newsletter = "Example Mailer (newsletters)"
mailbox = "Example Mail (staff mailboxes)"
"k1.v2" = "Example Campaigns"
```

None of this is a public contract yet: there is no release. `ConfigReason`, `Outcome`, the key
names `domain` and `senders` and the model fields become one at the first version.

## ADRs

### ADR-1 — Refuse a bad configuration, never repair it

**Decision.** Every problem in the file (unknown key, bad domain, duplicate selector, control
character in a name) is a refusal that stops the load. Nothing is cleaned and kept.
**Alternatives.** (a) Clean names as 002 cleans report text. (b) Warn about unknown keys and carry
on. (c) Collect every problem and report them all.
**Why.** A report is third-party text that must be shown *despite* being dirty, so 002 cleans it. A
configuration is written on purpose by the person who will act on the answer, and a silent repair
or a skipped key changes who is named as legitimate, which feeds a security decision. The file is a
handful of lines, so (c) buys little: fix one thing and run again.
**Trade-off.** A user with three mistakes sees them one at a time. (RF-01 to RF-05, RF-07)

### ADR-2 — Foreign beats failing in the "no service" answer

**Decision.** When no block is `KNOWN`, the result is `FOREIGN_DOMAIN` if any configured selector
was signed under someone else's domain, otherwise `FAILING_SIGNATURE`, otherwise `UNKNOWN`.
**Alternatives.** Document order across the three kinds; report the failing one first.
**Why.** The two answers mean different things to the owner, and when a record has both, the
foreign one is the one that may be a stranger. Showing the more suspicious reading first is the
safe failure; the failing signature of the owner's own service is visible the moment the stranger
is dealt with. Within a kind, the first block in document order keeps the answer deterministic
(Resolved decision 8, RNF-05).
**Trade-off.** A record that has a broken signature of the owner's service and an unrelated foreign
one reads as foreign. The rarity of that record is the reason it is acceptable. (RF-06)

### ADR-3 — Identity comes from the block, not from the record's evaluated results

**Decision.** `identify_sender` looks only at each DKIM block's selector, signer domain and result.
`policy_evaluated/dkim`, `header_from` and the source IP are not consulted.
**Alternatives.** Require `record.dkim_evaluated == "pass"`; require `header_from` to equal the
domain; add the IP to the key.
**Why.** `dkim_evaluated` is a verdict about the whole record with the receiver's alignment mode
and does not say which block passed; the block's own `result` and `d=` say exactly that and are
enough to answer "who signed". `header_from` is the same domain for every record of a report. The
summary (spec `004`) combines the sender with the evaluated results; keeping identification narrow
lets it do that without re-opening this decision.
**Trade-off.** A record can be `KNOWN` while its evaluated result is `fail` (the owner's service
signed correctly but under a domain that the policy treats as unaligned, in strict mode). That is
the summary's to flag, and it is information this function would otherwise hide. (RF-06)

### ADR-4 — One shared text module, and 002's domain rule moves with it

**Decision.** `text.py` holds the dropped-character categories, `clean_text`, `normalize_domain`
and `is_within_domain`. 002 imports from it; behavior and tests of 002 do not change.
**Alternatives.** (a) Duplicate the constant and the expression in `config.py`. (b) Import the
private `_clean` from `reports.parser`.
**Why.** "Which characters can hide text" and "when two domains are the same" are security
decisions that must have one definition; two copies drift. (b) makes `config` depend on a private
name of another package. The change to 002 is a delegation and one import, covered by the tests it
already has.
**Trade-off.** A small refactor of finished code. (RF-02, RF-05, RF-06)

### ADR-5 — The selector map is a read-only view, not a tuple of pairs

**Decision.** `Config.senders` is a `MappingProxyType` over a dict.
**Alternatives.** A sorted `tuple[tuple[str, str], ...]` (hashable, trivially ordered); a frozen
dict type of our own.
**Why.** `identify_sender` runs once per record, and thousands of records per run make a tuple scan
or a rebuilt dict a waste; a proxy gives constant-time lookup and cannot be changed through the
`Config` (RNF-04). Equality and order-independence follow from building the dict in sorted order.
**Trade-off.** `Config` is not hashable, and a caller who builds a `Config` by hand (tests do)
must give lower-case selectors; the loader guarantees it for loaded ones. (RF-03, RNF-04, RNF-05)

### ADR-6 — Compare domains with the exact-or-subdomain rule, no public suffix list

**Decision.** A signer domain belongs to the owner when it is the configured domain or ends in
`.` plus the configured domain.
**Alternatives.** Organizational-domain comparison with the Public Suffix List, as DMARC's relaxed
alignment does.
**Why.** The PSL is a data file that changes and would be a dependency or a vendored copy
(RNF-01 of 001). The configured domain is already the owner's chosen boundary, so "under it" is
exactly what the owner means; no PSL is needed to know that.
**Trade-off.** If the owner configures a subdomain (`mail.example.com`) and a service signs with the
parent (`example.com`), which relaxed alignment would accept, the result is `FOREIGN_DOMAIN`. That
reads as a false alarm, the safe direction, and the fix is to configure the parent domain. (RF-06)

## Impact on existing code

- **New files:** `src/mailvigil/text.py`, `config.py`, `senders.py` and three test files.
- **Changed, behavior-neutral:** `reports/parser.py` (`_clean` delegates; `_SPACING`,
  `_DROPPED_CATEGORIES` and the `unicodedata` import move out) and `reports/ingest.py` (one call).
  The existing 002 tests are the safety net and must pass unchanged.
- **`pyproject.toml`:** no change; `dependencies` stays empty. `tomllib` and `difflib` are standard
  library.
- **`.gitignore`:** `mailvigil.local.toml` is already ignored; tests build their files in
  `tmp_path`.
- **Docs:** README gains the file format and a quick-start line (status stays "planned" until the
  command exists); `docs/stack.md` gains `tomllib`, `difflib` and `types.MappingProxyType`;
  `CLAUDE.md` gains the three modules in its architecture block. `/atualizar-docs` at the end. The
  `specs/README.md` row moves to `in progress`, then `done`.
- **The site repository's script** is not changed.

## Risks

1. **The selector map can still be wrong.** The owner may map a selector to the wrong service, or
   forget one. Mitigation: nothing here can know; an unlisted sender is shown as unknown, which is
   the point of the product. The README example says to start with an empty `[senders]` and fill it
   from what the first summary shows as unknown.
2. **A shared selector name.** If the owner maps `default` and two unrelated services sign with it
   under the owner's domain, both are named alike. Mitigation: Resolved decision 4 of the requirements
   (no built-in table) keeps the ambiguity the owner's, and the README warns that a selector must
   identify one service.
3. **The `Identification` shape feeds spec `004`.** If the summary needs more (for instance, every
   matching selector, not only the first), the dataclass gets a field with a default; nothing here
   forbids it.
4. **`tomllib` error text.** `detail` for `MALFORMED_TOML` is the parser's message, which was
   checked to carry line and column on Python 3.12 only. The CI matrix covers the newest version,
   and a test asserts that the detail mentions `line`; if a version changes the wording, the test
   shows it.
5. **Windows paths and encodings.** BOM handled (step 3); the tests write the files with explicit
   bytes, so the newline style of the platform does not matter.

## Test strategy

Following [specs/README.md](../README.md#how-a-spec-is-tested): functions are called directly with
built inputs; no CLI, no subprocess, no network. Files are written in `tmp_path` from invented
domains (`example.com`, `example.org`, `example.net`) and invented service names (RNF-07); records
are built with the `Record` and `DkimResult` dataclasses.

| Requirement | Tests (each refusal expects `ConfigError` and checks `.reason` and `.key`) |
|---|---|
| RF-01 | minimal valid file; missing path; a folder as path; 64 KiB + 1 bytes (refused unparsed); exactly 64 KiB valid; non-UTF-8 bytes; UTF-8 with a byte order mark accepted; malformed TOML whose detail mentions the line; 40,000-deep nested array refused, not a crash |
| RF-02 | `Example.COM.` and padded input give `example.com`; `normalize_domain` agrees with what `ingest` accepts for the same text; missing, empty, integer, `https://example.com`, `example.com/path`, `user@example.com`, empty label (`a..com`), 64-character label, 254-character name, `localhost`, a leading or trailing hyphen label; `exämple.com` gives `NON_ASCII_DOMAIN` |
| RF-03 | keys stored lower case; the map is read-only (assigning raises `TypeError`); `Resend` plus `resend` is `DUPLICATE_SELECTOR` whichever comes first in the file; empty, spaced and `bad key!` selectors; names that are an integer, empty, blank, 101 characters, or a nested table; absent and empty `[senders]` accepted |
| RF-04 | `domian` suggests `domain`; `sender` suggests `senders`; an unrelated key has no suggestion; `senders` as a string is `WRONG_TYPE`; a dotted key `a.b = "x"` and a list value are refused as a nested value |
| RF-05 | a name with a line break, with U+202E, with U+0085 and with a zero-width space is `FORBIDDEN_CHARACTER`; `ConfigError.key` of a hostile unknown key contains none of them and is cut |
| RF-06 | passing signature under the domain and under a subdomain is `KNOWN` with service and selector; `fail` under the domain is `FAILING_SIGNATURE`; the right selector under `example.org` is `FOREIGN_DOMAIN`; `notexample.com` is not a subdomain; no DKIM block and no configured selector are `UNKNOWN`; empty selector and empty signer never match; two qualifying blocks give the first; foreign plus failing gives foreign; foreign plus known gives known; selector compared case-insensitively; result `PASS` counts |
| RF-07 | every `ConfigError` carries a `ConfigReason`; a file with two problems reports the same one regardless of the order of its lines |
| RF-08 | the hostile rows above are the RF-08 list |
| RNF-02 | nothing is written under `tmp_path` besides the inputs; no file is created next to the config |
| RNF-05 | the same content with the keys in two orders gives equal `Config` values |
| 002 | the unchanged 002 suite passes after the `text.py` refactor |

The quality gate (`ruff` → `black --check` → `mypy` → `pytest --cov`) closes each stage of
`tasks.md`, with its real result recorded.
