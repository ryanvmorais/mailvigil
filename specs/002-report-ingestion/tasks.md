---
feature: Report ingestion — read DMARC aggregate reports safely into a typed record model
status: in progress
date: 2026-10-27
related:
  - 002-report-ingestion/requirements.md
  - 002-report-ingestion/design.md
origin: conception
---

# 002 — Report ingestion — Tasks

Each stage is one pull request (issue → branch → PR); Claude opens it and never merges. Inside a
stage, tests come first: write the test that feeds the input, watch it fail for the right reason,
then write the code. Every hostile-input test expects `ReportRefused` and asserts `.reason`.

The stages go from the ground up, so each one stands on a tested layer: the vocabulary (errors and
model), the one place that touches a parser, the reader, the report parser, then discovery and the
public entry point.

## Stage 1 — Vocabulary, fixtures and the RFC check

- [x] Read RFC 9990 Appendix A (schema) and Appendix B (sample) and settle the open details of
  design Risk 1: which `policy_published` children exist (`np`, `testing`, `pct`,
  `discovery_method`), their multiplicity, and whether `auth_results/spf` and `reason` can repeat.
  Write what was found into the "Risks" section of `design.md`, and adjust the model there if it
  differs. Do not copy the RFC text; cite sections. — RF-04
- [x] `src/mailvigil/reports/errors.py`: `Reason` (`StrEnum`, the twelve members of the design) and
  `ReportRefused(reason, detail)`. Test: members are unique strings; `ReportRefused` keeps `reason`
  and `detail`; `str(error)` mentions both. — RF-09, ADR-3
- [x] `src/mailvigil/reports/model.py`: `DkimResult`, `SpfResult`, `OverrideReason`, `Record`,
  `PolicyPublished`, `Report`, `SkippedFile`, `IngestionResult` as
  `@dataclass(frozen=True, slots=True)` with the defaults of the design. Test: assigning a field
  raises `FrozenInstanceError`; collection fields are tuples; defaults (`pct` 100, empty strings).
  — RF-04, RNF-04
- [x] `tests/conftest.py`: factories `make_report_xml(**overrides)` (RFC 7489 and RFC 9990 flavors,
  based on the Appendix B sample and the documentation ranges of RNF-07), `make_gzip(data)` and
  `make_zip(members)`. No file is committed; everything is built in memory or in `tmp_path`.
  — RNF-07
- [x] Quality gate (`uv run ruff check .`, `uv run black --check .`, `uv run mypy`,
  `uv run pytest --cov`). — result recorded when run: all green on 2026-10-27; 21 passed, coverage
  100% (Python 3.12)

## Stage 2 — The only parser: refuse declarations (RF-03)

- [ ] `tests/test_reports_xmlsafe.py`, written first: `DOCTYPE`; `ENTITY` in an internal subset; an
  external entity (`SYSTEM "file:///…"`, never resolved); each of those in UTF-8, UTF-8 with a byte
  order mark and UTF-16, all refused with `FORBIDDEN_DECLARATION`; a document with an XML
  declaration and a comment accepted; a clean UTF-16 document accepted; malformed XML refused with
  `MALFORMED_XML` and a `line L, column C` detail. — RF-03, RF-10
- [ ] `src/mailvigil/reports/xmlsafe.py`: `parse_xml(xml: bytes) -> Element` with the expat
  handlers and the `TreeBuilder` glue of ADR-1, `buffer_text = True`, and the namespace translation
  (no namespace or `urn:ietf:params:xml:ns:dmarc-2.0` → local name; other namespace →
  `{uri}local`). Tests for the namespace translation go in the same file. Keep the module free of
  anything but parsing, so it can be read alone. — RF-03, RF-04, ADR-1, ADR-5
- [ ] Settle the typing of the expat handlers (design Risk 4) inside this module only, with the
  narrowest annotation or `cast` that satisfies `mypy` strict, and a `# why` comment. — RNF-04
- [ ] Quality gate. — result recorded when run: ___

## Stage 3 — Reading one attachment (RF-01, RF-02)

- [ ] `tests/test_reports_reader.py`, written first: round trip for `.xml`, `.gz` and `.zip`;
  upper-case suffix; unknown suffix (`UNSUPPORTED_EXTENSION`, without opening the file); missing
  file (`UNREADABLE`); a directory passed as a file (`UNREADABLE`); zip with no XML member
  (`NO_XML_MEMBER`) and with two (`MULTIPLE_XML_MEMBERS`); corrupt zip and corrupt gzip
  (`NOT_AN_ARCHIVE`). — RF-01
- [ ] Size tests, same file: `MAX_BYTES + 1` zeros as `.xml`, as a `.gz` and as a `.zip` member (each
  compresses to a few KB; `DECOMPRESSED_TOO_LARGE`); a file over the cap on disk (`FILE_TOO_LARGE`);
  a zip whose header declares a size smaller than the data (`NOT_AN_ARCHIVE`); `_read_capped`
  called directly on a stream larger than the cap, proving the cap does not consult any header;
  exactly `MAX_BYTES` accepted; a small report unaffected. — RF-02, RF-10, ADR-2
- [ ] `src/mailvigil/reports/reader.py`: `MAX_BYTES`, `_read_capped`, `read_xml` as in the design
  (suffix → `stat` → open → capped read → error mapping). Never extract, never use a member name
  as a path. — RF-01, RF-02, RNF-02
- [ ] Quality gate. — result recorded when run: ___

## Stage 4 — Parsing a report (RF-04, RF-05)

- [ ] `tests/test_reports_parser.py`, text cleaning first: a C1 control, a bidirectional override, a
  line break and a tab inside a field are removed or replaced; a 1,000-character field is cut at
  255; domains are lower-cased; an ESC and a NUL in the document are refused by the parser (the
  test documents that behavior). — RF-05, ADR-6
- [ ] `src/mailvigil/reports/parser.py`, part 1: `MAX_TEXT`, `_clean`, `_text`. — RF-05
- [ ] Tests for the report skeleton: full RFC 7489-style report to the model (every field
  asserted); the same report in the RFC 9990 namespace gives an equal `Report`; wrong root and
  foreign-namespace root (`NOT_A_REPORT`); `version` `1.0` and absent accepted, `2.0`
  (`UNSUPPORTED_VERSION`); missing `report_metadata` or `policy_published` (`NOT_A_REPORT`); bad
  timestamp, `end < begin` and `pct` 101 (`INVALID_FIELD`, detail names the field, not the value).
  — RF-04
- [ ] `parser.py`, part 2: `parse_report` up to metadata and `PolicyPublished`. — RF-04
- [ ] Tests for records: negative, non-integer and 5,000-digit `count` (`INVALID_FIELD`); whitespace
  around values; two `dkim` blocks and two `spf` blocks; override reasons; absent optionals take the
  defaults; IPv6 `source_ip` normalized (`2001:DB8::1` and `2001:db8:0::1` equal); an invalid
  address kept sanitized; `header_from` lower-cased; elements in a foreign namespace ignored.
  — RF-04
- [ ] `parser.py`, part 3: `Record` parsing with `ipaddress`. — RF-04
- [ ] Quality gate. — result recorded when run: ___

## Stage 5 — Discovery and ingestion (RF-06 to RF-09)

- [ ] `tests/test_reports_discovery.py`, written first: a file is kept whatever its name; a folder
  keeps only names matching the attachment pattern, including `report (1).zip` style names;
  subfolders ignored silently; the same file given twice, and once directly and once through its
  folder, is read once; names differing only in case sort the same on every platform; a missing
  path is `UNREADABLE` and the other paths are still discovered. — RF-06, RNF-05
- [ ] `src/mailvigil/reports/discovery.py`: `discover` as in the design (sort by name string,
  `os.path.realpath` dedupe). — RF-06
- [ ] `tests/test_reports_ingest.py`, written first: one good report plus one of each refusal in a
  folder (good one returned, each bad one in `skipped` with the right `Reason`); domain filter exact
  and case-insensitive, trailing dot in the argument, a subdomain counted as `other_domain`, empty
  `domain` raises `ValueError`; zero reports for the domain still returns the `other_domain` count;
  same reporter and id twice counts one duplicate and does not sum records; same id from two
  reporters kept; an other-domain report never counts as a duplicate; an empty folder gives an
  empty result; ingesting twice gives equal results; nothing is written under `tmp_path` besides
  the inputs. — RF-07, RF-08, RF-09, RF-10, RNF-02, RNF-05
- [ ] `src/mailvigil/reports/ingest.py`: `ingest` as in the design. — RF-07, RF-08, RF-09
- [ ] `src/mailvigil/reports/__init__.py`: re-export the public API of the design's Interfaces
  table and nothing else; a test imports each name from `mailvigil.reports`. — RF-09
- [ ] Zero-dependency guard: `uv build`, then check the wheel metadata has no `Requires-Dist`, as
  the CI `package` job does. — RNF-01
- [ ] Quality gate. — result recorded when run: ___

## Stage 6 — Close the spec

- [ ] Run `/atualizar-docs`: `CLAUDE.md` architecture tree gets `reports/`, `docs/stack.md` gets the
  standard-library modules this spec relies on (`expat`, `zipfile`, `gzip`, `ipaddress`). — docs
- [ ] The maintainer runs the layer over the real reports of his domain, locally and outside the
  repository (a throwaway script), and tells Claude only the counts per `Reason` and whether
  anything refused looked legitimate. No report content is pasted into a conversation, an issue or
  a PR. Findings become follow-up tasks or an ADR, not silent edits. — Risk 2 of the design
- [ ] Mark the three files `done`, move the roadmap row of `002` in `specs/README.md` to `done`, and
  fill the gold-standard note there if `001` is also `done`. — all
- [ ] Quality gate and CI. — result recorded when run: ___ (the CI run URL)
