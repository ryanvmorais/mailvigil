---
feature: Report ingestion — read DMARC aggregate reports safely into a typed record model
status: approved
date: 2026-10-27
related:
  - 002-report-ingestion/requirements.md
  - 001-foundation/design.md
origin: conception
---

# 002 — Report ingestion — design

## Overview

The layer is four small steps behind one function, and each step can be tested alone:

```text
paths ──discover──▶ files ──read_xml──▶ bytes ──parse_report──▶ Report ──filter/dedupe──▶ IngestionResult
         (RF-06)            (RF-01,02)          (RF-03,04,05)            (RF-07,08,09)
```

- **discover** turns the paths the caller gave (files and folders) into an ordered list of files.
- **read_xml** turns one file into XML bytes under a hard size cap.
- **parse_report** turns XML bytes into an immutable `Report`, refusing hostile or invalid input.
- **ingest** runs the three over every file, applies the domain filter and the duplicate rule, and
  never lets one refused file stop the rest.

Every refusal is a `ReportRefused` exception carrying a machine-readable `Reason` plus a short
detail. `ingest` catches it per file and records it; the lower functions let it propagate, so each
can be tested for "this input is refused for this reason". Nothing in the package prints, exits,
reads `sys.argv` or the environment (RNF-03), and nothing is written to disk (RNF-02).

The XML is parsed with `xml.parsers.expat` directly, not through `ElementTree.fromstring`, so that
`DOCTYPE` and `ENTITY` declarations are refused by the parser itself, in whatever encoding the
document uses (ADR-1). The tree is still an `ElementTree` one, built with `TreeBuilder`.

## Module layout

```text
src/mailvigil/reports/
  __init__.py      # public API: ingest, discover, read_xml, parse_report, the model, errors
  errors.py        # Reason (StrEnum), ReportRefused
  model.py         # frozen dataclasses: Report, PolicyPublished, Record, DkimResult, SpfResult,
                   #   OverrideReason, SkippedFile, IngestionResult
  reader.py        # read_xml(path) -> bytes            (RF-01, RF-02)
  xmlsafe.py       # parse_xml(bytes) -> Element        (RF-03, ADR-1)
  parser.py        # parse_report(xml, source) -> Report   (RF-04, RF-05)
  discovery.py     # discover(paths) -> (files, skipped)   (RF-06)
  ingest.py        # ingest(paths, domain) -> IngestionResult   (RF-07, RF-08, RF-09)
tests/
  conftest.py                  # factories that build synthetic XML, zip and gzip (RNF-07)
  test_reports_reader.py       # RF-01, RF-02
  test_reports_xmlsafe.py      # RF-03
  test_reports_parser.py       # RF-04, RF-05
  test_reports_discovery.py    # RF-06
  test_reports_ingest.py       # RF-07, RF-08, RF-09
```

`reports` is a package, not a module, because the pieces have different reasons to change (the
format reader changes with archive formats, the parser with the DMARC schema, discovery with file
naming) and because `xmlsafe.py` is the one file a security reviewer should be able to read alone.
`cli.py` is not touched (Resolved decision 5).

## Data model

All types are `@dataclass(frozen=True, slots=True)`; collections are tuples (RNF-04). Text fields
are already sanitized (RF-05); the fields below are strings unless said otherwise.

```python
class Reason(StrEnum):
    UNSUPPORTED_EXTENSION = "unsupported_extension"
    UNREADABLE = "unreadable"                    # missing, no permission, not a regular file
    FILE_TOO_LARGE = "file_too_large"            # on-disk size over the cap
    DECOMPRESSED_TOO_LARGE = "decompressed_too_large"
    NOT_AN_ARCHIVE = "not_an_archive"            # corrupt or unsupported zip / gzip
    NO_XML_MEMBER = "no_xml_member"
    MULTIPLE_XML_MEMBERS = "multiple_xml_members"
    FORBIDDEN_DECLARATION = "forbidden_declaration"   # DOCTYPE or ENTITY
    MALFORMED_XML = "malformed_xml"
    NOT_A_REPORT = "not_a_report"                # wrong root or foreign namespace
    UNSUPPORTED_VERSION = "unsupported_version"
    INVALID_FIELD = "invalid_field"              # count, period, pct

class ReportRefused(Exception):
    reason: Reason
    detail: str          # short, English, never echoes report content except the parser position

class DkimResult:  domain, selector, result
class SpfResult:   domain, result
class OverrideReason:  type, comment

class Record:
    source_ip: str                    # normalized by `ipaddress` when valid, else sanitized as-is
    count: int                        # >= 0
    disposition: str                  # "none" by default
    dkim_evaluated: str               # policy_evaluated/dkim: "pass" | "fail" | ""
    spf_evaluated: str                # policy_evaluated/spf
    override_reasons: tuple[OverrideReason, ...]
    header_from: str                  # lower case
    dkim: tuple[DkimResult, ...]      # every auth_results/dkim block, in order
    spf: tuple[SpfResult, ...]        # every auth_results/spf block (RFC 9990 allows several)

class PolicyPublished:
    domain: str                       # lower case
    p: str                            # "?" when absent, as in the source script
    sp: str; np: str; adkim: str; aspf: str; testing: str; discovery_method: str   # "" when absent
    pct: int                          # 0..100, default 100

class Report:
    reporter: str                     # report_metadata/org_name, "?" when absent
    report_id: str
    begin: datetime                   # aware, UTC
    end: datetime                     # aware, UTC, >= begin
    policy: PolicyPublished
    records: tuple[Record, ...]
    source_file: str                  # file name, display only

class SkippedFile:   path: Path; reason: Reason; detail: str
class IngestionResult:
    reports: tuple[Report, ...]       # discovery order
    skipped: tuple[SkippedFile, ...]  # discovery order
    duplicates: int
    other_domain: int
```

The evaluated results stay raw strings on purpose: turning them into `ok` / `fragile` / `failing`
is spec `004`, and naming the sender from `dkim[*].selector` is specs `003` and `004`. This layer
records what the report said, not what it means.

## Components

### Reader (RF-01, RF-02)

`read_xml(path: Path) -> bytes`, raising `ReportRefused`.

1. Suffix, lower-cased, must be `.xml`, `.gz` or `.zip`, else `UNSUPPORTED_EXTENSION`. This is
   checked before the file is touched.
2. `path.stat()`: not a regular file or any `OSError` → `UNREADABLE`; `st_size > MAX_BYTES` →
   `FILE_TOO_LARGE`. `MAX_BYTES = 5 * 1024 * 1024`, one module constant.
3. Open the content as a binary stream:
   - `.xml`: the file itself.
   - `.gz`: `gzip.open(path)`.
   - `.zip`: `zipfile.ZipFile(path)`, members that are not directories and end in `.xml`
     (case-insensitive). Zero → `NO_XML_MEMBER`; more than one → `MULTIPLE_XML_MEMBERS`; one →
     `zip.open(member)`. Nothing is extracted; the name of the member is never used as a path.
4. `_read_capped(stream)` reads until the end or until it holds `MAX_BYTES + 1` bytes (asking for
   only what is still missing, and looping because a raw stream may return less than asked without
   having ended) and raises `DECOMPRESSED_TOO_LARGE` when it got more than `MAX_BYTES`. This is the
   only size defense on the decompressed side: it acts on the bytes actually produced, so it holds
   for gzip (whose trailer size is only 32 bits and untrusted) and for zip (whose header can lie),
   and at most `MAX_BYTES + 1` bytes are held.
5. `zipfile.BadZipFile`, `gzip.BadGzipFile`, `zlib.error`, `EOFError`, `NotImplementedError`
   (unsupported compression) and `RuntimeError` (encrypted member) → `NOT_AN_ARCHIVE`. Any other
   `OSError` → `UNREADABLE`. `BadGzipFile` is an `OSError`, so it is caught first.

Checked while designing (2026-10-27, Python 3.14): when a zip header declares a size smaller than
the real one, `zipfile` stops at the declared size and raises `BadZipFile: Bad CRC-32`, which
lands in item 5. A header that declares more than the real size is harmless. In both cases the cap
in item 4 is the actual guard, and it is the one exercised by the bomb tests.

### Safe XML parser (RF-03)

`parse_xml(xml: bytes) -> ElementTree.Element`, the only place that touches a parser.

```python
parser = expat.ParserCreate(namespace_separator="}")
parser.StartDoctypeDeclHandler = _refuse      # any <!DOCTYPE ...>
parser.EntityDeclHandler = _refuse            # any <!ENTITY ...>, defense in depth
parser.buffer_text = True
# Start/End/CharacterData handlers feed an ElementTree.TreeBuilder
parser.Parse(xml, True)
return builder.close()
```

`_refuse` raises `ReportRefused(FORBIDDEN_DECLARATION, ...)`; an exception raised inside an expat
handler propagates out of `Parse` unchanged. Expat decodes the document (it honors the XML
declaration and a byte order mark) before it calls the handlers, so the check works on the
declaration as the parser understood it, not on the raw bytes. No external-entity handler is
registered, so even a bug in the refusal could not make the parser open a file or a URL.
`expat.ExpatError` becomes `MALFORMED_XML` with `line L, column C` taken from the exception.

Namespaces: expat reports a namespaced name as `uri}local`. The `Start`/`End` handlers translate it
before it reaches the builder: no namespace or `urn:ietf:params:xml:ns:dmarc-2.0` → the local name
(`feedback`); any other namespace → `{uri}local`, a name no later lookup asks for, so extension
elements are ignored and a foreign-namespace `feedback` fails the root check (RF-04).

A prototype of exactly this shape was run on 2026-10-27 over: a UTF-16 document with `DOCTYPE` and
`ENTITY`, a UTF-8 one, a UTF-8 one with a byte order mark, an external-entity declaration (all
refused); and a clean UTF-8 document, a clean UTF-16 document and one with an XML declaration and
a comment (all accepted). The same UTF-16 document went through the source script's byte search
unnoticed and had its entity expanded.

### Parser (RF-04, RF-05)

`parse_report(xml: bytes, *, source: str = "") -> Report`.

1. `root = parse_xml(xml)`; `root.tag != "feedback"` → `NOT_A_REPORT`.
2. `version` text, when present, must be `1.0` → else `UNSUPPORTED_VERSION`.
3. `report_metadata`: `org_name`, `report_id`, and `date_range/begin` and `end` parsed with
   `int` and `datetime.fromtimestamp(…, UTC)`. `ValueError`, `OverflowError` and `OSError` from
   that conversion, and `end < begin`, → `INVALID_FIELD` (detail: the field name only).
4. `policy_published`: the fields of `PolicyPublished`; `pct` parsed as `int`, must be 0 to 100.
5. Each `record`: `row/count` via `int`, must be ≥ 0; a non-integer count (including one so long
   that `int` refuses it) → `INVALID_FIELD`. `row/source_ip` through `ipaddress.ip_address`: when
   it parses, store `str(address)` (so `2001:DB8::1` and `2001:db8:0::1` group together later);
   when it does not, keep the sanitized text, because a source the report named but that cannot be
   reasoned about is still worth showing. Then `policy_evaluated`, `reason` blocks,
   `identifiers/header_from` and every `auth_results/dkim` and `auth_results/spf`.
6. A helper `_text(node, path, default)` returns the stripped, sanitized text of a sub-element.
   `_clean(value)` implements RF-05: tab, CR and LF become a space, then every character whose
   Unicode category is `Cc`, `Cf`, `Zl` or `Zp` (this covers C1 controls and the bidirectional
   overrides and isolates) is dropped, the result is stripped and cut to `MAX_TEXT = 255`
   characters. Domains are additionally lower-cased.

Missing optional elements take the defaults of the data model; a missing required container
(`report_metadata`, `policy_published`) → `NOT_A_REPORT`. Lookups use only `find`/`findall` on
local names, so the order of elements in the document does not matter and unknown elements are
ignored.

### Discovery (RF-06)

`discover(paths: Sequence[Path]) -> tuple[tuple[Path, ...], tuple[SkippedFile, ...]]`.

- A path that does not exist or cannot be listed → a `SkippedFile(UNREADABLE)`, and discovery goes
  on with the next path.
- A directory: its direct children, sorted **by file name as a string** (not by `Path`, whose
  ordering is case-insensitive on Windows and case-sensitive on Linux; RNF-05), kept when they are
  regular files and the name matches
  `^[^!]+![^!]+!\d+!\d+.*\.(zip|gz|xml)$` (case-insensitive), the attachment pattern of the source
  script. Subdirectories are skipped without a word.
- Any other path is taken as a file and kept whatever its name. If it is not a regular file, the
  reader reports `UNREADABLE` later, which is also what keeps a named pipe from blocking the run.
- Duplicates are removed by `os.path.realpath`, keeping the first spelling given.

### Ingest (RF-07, RF-08, RF-09)

`ingest(paths: Sequence[Path], domain: str) -> IngestionResult`.

```text
wanted = domain.strip().lower().rstrip(".")      # empty -> ValueError: a programming error
files, skipped = discover(paths)
for file in files:
    try:    report = parse_report(read_xml(file), source=file.name)
    except ReportRefused as refused:  skipped.append(SkippedFile(file, refused.reason, refused.detail)); continue
    if report.policy.domain != wanted:   other_domain += 1
    elif (report.reporter, report.report_id) in seen:   duplicates += 1
    else:   seen.add(key); reports.append(report)
```

The domain filter runs before the duplicate rule, as in the source script, so an other-domain
report never counts as a duplicate. `ingest` returns even when `reports` is empty; whether that is
an error is the caller's call (RF-09, spec `006`).

## Interfaces

| Contract | Shape |
|---|---|
| `mailvigil.reports.ingest(paths, domain)` | `Sequence[Path], str -> IngestionResult` |
| `mailvigil.reports.discover(paths)` | `Sequence[Path] -> (tuple[Path, ...], tuple[SkippedFile, ...])` |
| `mailvigil.reports.read_xml(path)` | `Path -> bytes`; raises `ReportRefused` |
| `mailvigil.reports.parse_report(xml, *, source="")` | `bytes -> Report`; raises `ReportRefused` |
| `ReportRefused.reason` | a `Reason`; the stable key later specs translate to text |
| `MAX_BYTES`, `MAX_TEXT` | module constants (5 MiB, 255) |

None of this is a public contract yet: there is no release. `Reason` values and the model fields
become one at the first version, as specs `004` to `006` build on them.

## ADRs

### ADR-1 — Refuse declarations inside expat, not by searching bytes

**Decision.** Parse with `xml.parsers.expat` directly. `StartDoctypeDeclHandler` and
`EntityDeclHandler` raise `ReportRefused`; a `TreeBuilder` assembles the tree.
**Alternatives.** (a) Keep the source script's `b"<!DOCTYPE" in xml`. (b) Search the bytes for the
ASCII, UTF-16 and UTF-32 forms of the strings. (c) Decode first, then search the text.
(d) `ElementTree.XMLParser` with a hook on its inner expat parser. (e) `defusedxml`.
**Why.** (a) was run against a UTF-16 document on 2026-10-27: the search missed it and the entity
was expanded. (b) and (c) re-implement encoding detection and will drift from what the parser does
(a mismatch between the check and the parser is the bug class). (d) fails on this Python: the
accelerated `XMLParser` of 3.14 has no `.parser` attribute. (e) is a runtime dependency and
breaks RNF-01. Hooking expat means the check sees exactly what the parser sees.
**Trade-off.** About thirty lines of handler glue instead of one `fromstring` call, and a tie to
the `expat` module, which is documented and stable. Covered by RF-10 tests in three encodings.
(RF-03, RNF-01)

### ADR-2 — One size cap, on the decompressed stream

**Decision.** `read(MAX_BYTES + 1)` on whatever stream the archive gives, plus a cheap `st_size`
check on the file itself. Declared sizes inside archives are not consulted.
**Alternatives.** Also refuse early when a zip header declares more than the cap.
**Why.** Two mechanisms mean two code paths to test and a temptation to trust the header. The
stream cap is needed anyway for gzip, which has no trustworthy size, and costs at most 5 MiB of
reading to refuse a zip that declares too much.
**Trade-off.** An honestly oversized zip is read up to the cap before it is refused. Negligible.
(RF-02)

### ADR-3 — Refusals are typed exceptions with a `Reason` enum

**Decision.** `ReportRefused(reason: Reason, detail: str)`; `ingest` converts it into `SkippedFile`.
**Alternatives.** (a) `ValueError` with a message, as the source script does. (b) Return a
`Result` object from every function.
**Why.** Spec `006` shows text in English and Portuguese, which needs a key to translate, not a
sentence to parse. Exceptions keep the happy path of the lower functions plain and let tests say
`pytest.raises(ReportRefused)` and check `.reason`.
**Trade-off.** `detail` stays English and is for logs and debugging; the user-facing text is
built from `reason` by spec `006`. (RF-09)

### ADR-4 — Flat, raw model; no interpretation

**Decision.** The model keeps what the report says (`dkim_evaluated="pass"`, every DKIM block, the
override reasons). Alignment booleans, `ok`/`fragile`/`failing` and sender names are not here.
**Alternatives.** Keep the source script's `Registro` with its `situacao` and `remetente`
properties.
**Why.** Those properties are specs `003` and `004`; putting them here would fix a classification
before its spec. A raw model also lets the verdict use override reasons the script dropped
(Resolved decision 6).
**Trade-off.** More fields to carry and test. (RF-04)

### ADR-5 — Accept both report generations, strict about everything else

**Decision.** Accept `feedback` with no namespace or in `urn:ietf:params:xml:ns:dmarc-2.0`;
`version` absent or `1.0`; ignore foreign-namespace elements; refuse any other root namespace or
version.
**Alternatives.** (a) Strip every namespace blindly. (b) Accept only the RFC 7489 form.
**Why.** RFC 9990 is published and obsoletes RFC 7489, so providers will migrate; (b) would turn
good reports into refusals one provider at a time. (a) would read a document the project knows
nothing about as if it were a report.
**Trade-off.** A provider that invents its own namespace is refused until a spec adds it, which is
visible in `skipped`. (RF-04, Resolved decision 10)

### ADR-6 — Sanitize at parse time, by Unicode category

**Decision.** `_clean` drops `Cc`, `Cf`, `Zl` and `Zp` characters, turns tab/CR/LF into a space,
strips and cuts at 255 characters, for every text field that reaches the model.
**Alternatives.** (a) Sanitize where text is printed. (b) Allow only `[A-Za-z0-9._-]` in domains
and selectors.
**Why.** (a) trusts every future caller to remember; doing it once at the boundary makes the
model safe by construction. (b) would mangle internationalized names and organization names for
no gain. The XML parser already rejects C0 controls (checked 2026-10-27); this closes C1,
bidirectional overrides and line breaks, which XML allows.
**Trade-off.** `Cf` also holds the zero-width joiner some scripts need; domains and report
metadata are ASCII in practice, and the loss is cosmetic. (RF-05)

### ADR-7 — Strict defaults: one zip member, no recursion, exact domain

**Decision.** More than one `.xml` in a zip is refused; folders are not entered recursively; the
domain filter is an exact match.
**Alternatives.** Read every member; recurse; match subdomains.
**Why.** Resolved decisions 7 to 9: each is the cheapest to defend and can be loosened later by a
flag or by configuration without breaking anything. The reverse (tightening later) would.
**Trade-off.** A few users will hit a refusal and have to be told what to do; the `Reason` makes
that message possible. (RF-01, RF-06, RF-07)

## Impact on existing code

- **New package** `src/mailvigil/reports/` and new test files; `cli.py`, `__init__.py` and the
  `--version` behavior are untouched.
- **`pyproject.toml`:** no change expected. `dependencies` stays empty; ruff's selected rules
  (`E F I UP B SIM C4 RUF`) include no security plugin, so `expat` and `ElementTree` imports raise
  no rule. mypy strict over `src` covers the new package; `xml.parsers.expat` is typed in the
  bundled typeshed.
- **`.gitignore`:** already ignores real reports and allows `tests/**/*.xml.gz|zip`. The new tests
  build their fixtures in memory or in `tmp_path`, so no fixture file is committed.
- **Docs:** `docs/stack.md` gains the standard-library modules this spec relies on (`expat`,
  `zipfile`, `gzip`, `ipaddress`); `/atualizar-docs` at the end of the implementation. The
  `specs/README.md` row for `002` moves to `in progress`, then `done`.
- **The site repository's script** is not changed.

## Risks

1. **RFC 9990 fields are only partly verified.** *Settled on 2026-10-27 (Stage 1), from RFC 9990
   sections 3.1.1.2, 3.1.1.5, 3.1.1.8, 3.1.1.9, 3.1.1.11 and Appendices A and B:*
   - `policy_published` holds `domain` and `p` (required) and `sp`, `np`, `adkim`, `aspf`,
     `discovery_method` (`psl` or `treewalk`), `fo` and `testing` (optional, 0..1, any order).
   - **`pct` does not exist in RFC 9990** (it is an RFC 7489 field). The model keeps `pct` with the
     default 100, which is also what an RFC 9990 report means by "unspecified tags have their
     default values"; an RFC 7489 report fills it in. Both are read into the same `Report`.
   - `fo` is not in the model: no later spec uses it. Adding it later is a field with a default.
   - `auth_results/dkim` repeats; `auth_results/spf` is at most one in RFC 9990, but RFC 7489
     allowed several, so `Record.spf` stays a tuple and reads every block.
   - `policy_evaluated` appears once per `row`; `policy_evaluated/reason` repeats (a tuple).
   - `version` is optional, `xs:decimal`, and must be `1.0` (matches ADR-5).

   The previous wording of this risk is superseded; `PolicyPublished` treats every optional child
   as optional, as designed. The fixtures follow the RFC's sample (Appendix B, documentation, not a
   real report) with invented domains.
2. **Real providers deviate from the RFC.** Mitigation: every optional element has a default and
   unknown elements are ignored; only `count`, the period and `pct` are strict. Before the first
   release the maintainer runs the layer over the real reports of his domain locally and reports
   refusals as `skipped` reasons, without committing or pasting the reports.
3. **5 MiB may be too small for a very busy domain.** The source script never hit it. A refusal is
   visible as `DECOMPRESSED_TOO_LARGE`, and `MAX_BYTES` is one constant; raising it is a decision
   for a spec, not a silent edit.
4. **Typing the expat handlers.** *Settled on 2026-10-27 (Stage 2):* the stubs type the handler
   attributes loosely, so plain lambdas satisfy mypy strict with no annotation and no `cast`.
5. **Cross-platform ordering.** Sorting by the file name string is the same on Windows and Linux;
   the discovery test asserts it with names that differ in case only.

## Test strategy

Following [specs/README.md](../README.md#how-a-spec-is-tested): the functions are called directly
with built inputs; no CLI, no subprocess, no network. Every fixture is built in the test
(`conftest.py` factories for XML, zip and gzip; `tmp_path` for files) from invented domains and
documentation address ranges (RNF-07).

| Requirement | Tests (each hostile case expects `ReportRefused` and checks `.reason`) |
|---|---|
| RF-01 | `.xml`, `.gz`, `.zip` round trip; upper-case suffix; unknown suffix; zip with no XML, with two XMLs; corrupt zip; corrupt gzip; missing file |
| RF-02 | 5 MiB + 1 of zeros as `.xml`, as `.gz` and as `.zip` member; a zip whose header declares a smaller size than the data (`Bad CRC` → `NOT_AN_ARCHIVE`); `_read_capped` fed a stream larger than the cap, to prove the cap does not read the header; a small legitimate report passes; on-disk size over the cap |
| RF-03 | `DOCTYPE`; `ENTITY` in an internal subset; external entity (`SYSTEM`); the same in UTF-16 and UTF-8 with a byte order mark; a clean document with a declaration and a comment is accepted |
| RF-04 | full report to model (every field asserted); RFC 7489 and RFC 9990 namespace give equal reports; foreign namespace root; wrong root; malformed XML with position; negative, non-integer and 5,000-digit `count`; bad timestamp; `end < begin`; `pct` 101; `version` `2.0`; missing optionals take defaults; whitespace around values; two `dkim` blocks; IPv6 source normalized |
| RF-05 | C1 control, bidirectional override, line break inside a field (removed or replaced); a 1,000-character field cut at 255; ESC and NUL refused by the parser (documents the parser's behavior) |
| RF-06 | file taken whatever its name; folder keeps only the attachment pattern; non-recursive; same file twice; names differing in case sort identically on every platform; missing path reported, others still read |
| RF-07 | exact match, case-insensitive; trailing dot in the argument; subdomain is "other domain"; zero reports for the domain still returns the `other_domain` count |
| RF-08 | same reporter and id twice (second counted, records not summed); same id from two reporters kept; an other-domain report never counts as a duplicate |
| RF-09 | a folder with one good report and one of each refusal: the good one is returned, every bad one is in `skipped` with the right `Reason`, counts correct; `ingest` on an empty folder returns an empty result |
| RF-10 | the hostile rows above are the RF-10 list; a test asserts nothing was written under `tmp_path` besides the inputs (RNF-02) |
| RNF-05 | the same folder ingested twice gives equal results |

The quality gate (`ruff` → `black --check` → `mypy` → `pytest --cov`) closes each stage of
`tasks.md`, with its real result recorded.
