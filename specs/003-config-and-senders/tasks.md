---
feature: Config and senders — a TOML file with the domain and a DKIM selector to service name map
status: in progress
date: 2026-10-27
related:
  - 003-config-and-senders/requirements.md
  - 003-config-and-senders/design.md
origin: conception
---

# 003 — Config and senders — Tasks

Each stage is one pull request (issue → branch → PR); Claude opens it and never merges. Inside a
stage, tests come first: write the test that feeds the input, watch it fail for the right reason,
then write the code. Every refusal test expects `ConfigError` and asserts `.reason` and `.key`.
Every file a test needs is written in `tmp_path` as explicit bytes, from invented domains
(`example.com`, `example.org`, `example.net`) and invented service names (RNF-07).

The stages go from the ground up: the shared text rules (which touch finished code, so they come
first and alone), the loader, then identification, then the close.

## Stage 1 — Shared text rules (ADR-4)

- [x] `tests/test_text.py`, written first: `clean_text` gives the results the existing `_clean` tests
  expect (tab, CR and LF become a space; C1 controls, bidirectional overrides and zero-width
  characters dropped; stripped; cut at the given limit; ordinary international text kept);
  `has_dropped_characters` is true for a line break, U+0085, U+202E and U+200B and false for
  `Müller 日本語`; `normalize_domain("  Example.COM. ")` is `example.com`; `is_within_domain` is true
  for the domain itself, for `mail.example.com` and for `MAIL.Example.com.`, and false for
  `notexample.com`, `example.com.evil.net`, `com` and the empty string. — RF-02, RF-05, RF-06
- [x] `src/mailvigil/text.py`: `DROPPED_CATEGORIES`, `clean_text(value, limit)`,
  `has_dropped_characters`, `normalize_domain`, `is_within_domain`, as in the design. — ADR-4
- [x] Refactor 002 without changing its behavior: `parser._clean` becomes
  `clean_text(value, MAX_TEXT)` (`MAX_TEXT` stays in `parser.py`; `_SPACING`, `_DROPPED_CATEGORIES`
  and the `unicodedata` import leave it), and `ingest` calls `normalize_domain`. The existing 002
  tests must pass **unchanged**; if one needs an edit, stop and ask. — ADR-4
- [x] Quality gate (`uv run ruff check .`, `uv run black --check .`, `uv run mypy`,
  `uv run pytest --cov`). — result recorded when run: all green on 2026-10-27; 207 passed (178 of
  002 unchanged, 29 new), coverage 100% (Python 3.12)

## Stage 2 — The loader (RF-01 to RF-05, RF-07)

- [x] `src/mailvigil/config.py`, vocabulary only: `ConfigReason` (the thirteen members of the
  design), `ConfigError(reason, key, detail)` with `key` passed through `clean_text` and cut, and the
  frozen `Config`. Test first in `tests/test_config.py`: members are unique strings; `ConfigError`
  keeps `reason`, `key` and `detail`; `str(error)` mentions the reason and the key; a key with a
  line break and U+202E comes out of `ConfigError.key` clean and cut at 100; assigning a `Config`
  field raises `FrozenInstanceError`; assigning into `Config.senders` raises `TypeError`. — RF-07,
  RNF-04, ADR-5
- [x] Tests for reading the file, written first: a minimal valid file; a missing path and a folder
  (`UNREADABLE`); exactly 64 KiB accepted and 64 KiB + 1 refused as `FILE_TOO_LARGE` without being
  parsed; non-UTF-8 bytes (`NOT_UTF8`); UTF-8 with a byte order mark accepted; malformed TOML
  (`MALFORMED_TOML`, and the detail mentions `line`); a 30,000-deep nested array (40,000 would
  pass the 64 KiB cap) refused as `MALFORMED_TOML` instead of crashing; nothing created or written next to the config. — RF-01,
  RNF-02
- [x] `config.py`, part 1: `load_config` up to the parsed table (steps 1 to 4 of the design), with
  `MAX_CONFIG_BYTES`. — RF-01
- [x] Tests for the domain, written first: `Example.COM.` and padded input give `example.com`; the
  loaded domain is the one `ingest` would use for the same text; missing (`MISSING_DOMAIN`); empty,
  an integer, `https://example.com`, `example.com/path`, `user@example.com`, `a..com`, a 64-character
  label, a 254-character name, `localhost`, `-a.example.com` and `a-.example.com`, a domain with a
  space and one with a control character (`INVALID_DOMAIN`); `exämple.com` and the Kelvin sign U+212A,
  which lower-cases to an ASCII `k` (`NON_ASCII_DOMAIN`, checked before lower-casing);
  unknown top-level keys: `domian` suggests `domain`, `sender` suggests `senders`, an unrelated key
  has no suggestion, and a hostile key is cleaned in `ConfigError.key`. — RF-02, RF-04, RF-05
- [x] `config.py`, part 2: unknown keys (step 5) and the domain (step 6). — RF-02, RF-04
- [x] Tests for the selector map, written first: keys stored lower case and the map is read-only;
  `Resend` plus `resend` is `DUPLICATE_SELECTOR` whichever comes first; empty, spaced and `bad key!`
  selectors (`INVALID_SELECTOR`); `senders` as a string (`WRONG_TYPE`); a value that is an integer,
  empty, blank, 101 characters, a list, a nested table, and a dotted key `a.b = "x"`
  (`INVALID_SERVICE_NAME`); a quoted `"a.b" = "x"` accepted; a name with a line break, U+202E, U+0085
  and a zero-width space (`FORBIDDEN_CHARACTER`); names stripped when stored; absent and empty
  `[senders]` accepted. — RF-03, RF-04, RF-05
- [x] `config.py`, part 3: the senders table (step 7) and the final `Config` built in sorted order
  (step 8). — RF-03, RNF-05
- [x] Order and determinism tests: a file with two problems reports the same one whichever order its
  lines are in; the same content with keys in two orders gives equal `Config` values. — RF-07,
  RNF-05
- [x] Quality gate. — result recorded when run: all green on 2026-10-27; 289 passed (207 before,
  82 new), coverage 100% (Python 3.12)

## Stage 3 — Identifying the sender (RF-06)

- [x] `tests/test_senders.py`, written first, with `Record` and `DkimResult` built in the test and a
  `Config` built by a small helper: a passing signature under the domain and under a subdomain is
  `KNOWN` with service and selector; `fail` under the domain is `FAILING_SIGNATURE`; the right
  selector under `example.org` is `FOREIGN_DOMAIN`, with the selector filled in and the service
  empty; `notexample.com` is not a subdomain; no DKIM block and a selector that is not configured
  are `UNKNOWN`; an empty selector and an empty signer never match; two qualifying blocks give the
  first; foreign plus failing gives foreign; foreign plus known gives known; failing plus known gives
  known; selector compared case-insensitively; result `PASS` counts; a foreign signature that also
  failed is foreign; `Identification` is frozen. — RF-06, RF-08, RNF-04
- [x] `src/mailvigil/senders.py`: `Outcome`, `Identification`, `identify_sender` as in the design (one
  pass, first of each kind remembered, precedence known > foreign > failing > unknown). Does not
  read `dkim_evaluated`, `header_from` or the IP. — RF-06, ADR-2, ADR-3, ADR-6
- [x] A test that `identify_sender` ignores the record's `dkim_evaluated`, `header_from` and
  `source_ip`: the same DKIM blocks with those fields changed give equal results. — ADR-3
- [x] Quality gate. — result recorded when run: all green on 2026-10-27; 329 passed (289 before,
  40 new), coverage 100% (Python 3.12)

## Stage 4 — Close the spec

- [ ] Hostile-input audit (RF-08): list the cases of the requirement and point each to its test; add
  whichever is missing. — RF-08
- [ ] Zero-dependency guard: `uv build`, then check the wheel metadata has no `Requires-Dist` and
  holds `text.py`, `config.py` and `senders.py`, importable from the built wheel. — RNF-01
- [ ] Run `/atualizar-docs`: the README gains the file format (with the quoted-dotted-selector note
  and the advice to start with an empty `[senders]`), its "Configuration" row and `CLAUDE.md`'s
  architecture block gain the new modules, and `docs/stack.md` gains `tomllib`, `difflib` and
  `types.MappingProxyType`. The README status stays "library built, not wired to the CLI" until the
  command exists. — docs
- [ ] Mark the three files `done` and move the roadmap row of `003` in `specs/README.md` to `done`.
  — all
- [ ] Quality gate and CI. — result recorded when run
