---
feature: IMAP fetch — download the DMARC report messages from a mailbox into a folder (`mailvigil fetch`)
status: done
date: 2026-10-28
related:
  - 009-imap-fetch/requirements.md
  - 009-imap-fetch/design.md
origin: conception
---

# 009 — IMAP fetch — Tasks

Each stage is one pull request (issue → branch → PR); Claude opens it and never merges. Inside a
stage, tests come first: write the test that feeds the input, watch it fail for the right reason,
then write the code. No test opens a connection: the logic runs against a `FakeMailbox`, the
adapter's bounds against a local `socket.socketpair()` (ADR-1). Hosts are `.invalid`, users and
passwords are invented (a canary password is searched for in every output), messages are built in
`tests/fetch_helpers.py`. No real message, host, address or credential enters a test, a doc or a
commit message (RNF-06).

The stages go from the bottom up: first the vocabulary and the texts, which nothing calls yet; then
the store; then the loop against a fake; then the adapter to `imaplib`; then the command that wires
them; then the close. The test files of 002 to 008 are only edited where the design says a
signature changed (the parent parser split); if any other one fails, the code is wrong.

## Stage 1 — Vocabulary, texts and the ignore rule (RF-08, RNF-01, RNF-07, ADR-1, ADR-8)

- [x] `tests/test_fetch_model.py`, written first: the twelve keys of `FetchReason` exist with the exact
  strings of the design; `FetchRefused` carries `reason`, a `detail` cleaned and cut at 200 and an
  optional partial `FetchOutcome`; `SearchResult` (the valid UIDs and the count of dropped tokens, what `Mailbox.search` returns); `FetchOutcome` is frozen and slotted; the constants have the
  values of the design table; `MAX_MESSAGE_BYTES` in `fetch` is the object of `reports.mail`;
  importing `mailvigil.fetch.errors` and `mailvigil.fetch.model` does not put `imaplib` in
  `sys.modules` (a fresh interpreter). — RF-08, ADR-1, ADR-7
- [x] `src/mailvigil/fetch/__init__.py` (docstring only), `errors.py`, `model.py`: `FetchReason`,
  `FetchRefused`, `FetchOutcome`, the constants and the `Mailbox` protocol, with docstrings
  (`Args:` / `Returns:` / `Raises:`). — RF-08, ADR-1
- [x] `tests/test_messages.py`, `tests/test_render_fetch.py`, first: every `FetchReason` has a
  sentence in both languages (the coverage test fails for all of them, which is the point); the
  texts are ASCII; `render_fetch` writes the six numbers and the directory, at most 80 columns, in
  English and in Portuguese, with a hostile directory name (control characters, a bidirectional
  override, 300 characters) cleaned and cut; the refusal line is `mailvigil: <phrase>[: <detail>]`
  plus the line with the saved count only when `saved > 0`. — RF-08
- [x] `src/mailvigil/messages/model.py`, `en.py`, `pt_br.py` (ASCII only) and
  `src/mailvigil/render_fetch.py`: `FetchMessages`, one sentence per reason and per label in each
  language, `render_fetch`, `refusal_line`. `messages/` imports `fetch.errors` and nothing else of
  `fetch/`. — RF-08
- [x] `.gitignore` and a test: `*.eml` and `*.mbox` are ignored outside `tests/`, and the negations
  keep `tests/**` tracked (`git check-ignore` over `tmp` paths in a test, or a text check of the
  file if the repository state cannot be assumed). — RNF-07
- [x] Quality gate of the stage: `uv run ruff check .` → `uv run black --check .` → `uv run mypy` →
  `uv run pytest --cov`. Record the result here, with the number of tests and the coverage.
  **Result:** ruff, black and mypy clean; 2346 tests passed, coverage 100%.

## Stage 2 — The store (RF-06, RF-07, RNF-05, ADR-6)

- [x] `tests/test_fetch_store.py`, written first: the tag is eight hex digits, stable for the same
  host, user and folder and different when any of the three changes; a hostile host, user and
  folder (separators, `..`, a reserved Windows name, control characters, a bidirectional override)
  give a tag of eight hex digits and nothing else; `name(validity, uid)` is
  `<tag>-<validity>-<uid>.eml` and stays inside the directory; `has` is false before and true after
  a `save`; `save` creates a missing directory (several levels), writes the exact bytes, leaves no
  temporary file; a failing `os.replace`, a failing write and a disk-full `OSError` raise
  `write_failed` and leave no `.eml` and no temporary file; two saves of one message leave one
  correct file; `clean_stale` removes a `.mailvigil-*.partial` older than a day and keeps a younger
  one and every other file (an `.eml` among them). — RF-06, RF-07, ADR-6
- [x] `src/mailvigil/fetch/store.py`: `Store`, `tag_of`, `name`, `has`, `save` (unique temporary
  file in the same directory, `flush`, `fsync`, `os.replace`), `clean_stale`. Docstrings with
  `Args:` / `Returns:` / `Raises:`. — RF-06, RF-07, RNF-05, ADR-6
- [x] Quality gate of the stage: the same four commands. **Result:** ruff, black and mypy clean;
  2379 tests passed, coverage 100%.

## Stage 3 — The loop against a fake (RF-04, RF-05, RF-07, RF-08, RNF-03, RNF-04, ADR-1, ADR-8)

- [x] `tests/fetch_helpers.py`: `FakeMailbox` (the five methods of the protocol, scripted: UIDs,
  sizes, bodies, a validity number, hooks to raise or to return `None`, a record of every call and
  of `close`) and `build_message(...)` (a small synthetic `.eml`). — RNF-06
- [x] `tests/test_fetch_run.py`, written first: the counts add up
  (`matched == saved + already + too_large + skipped + left`) in every scenario below; messages
  are requested newest first; `--limit` counts new messages only and puts the rest in `left`; a
  rerun against the same store saves nothing and every file is byte-identical; a changed validity
  number downloads again and keeps the old files; a size over `MAX_MESSAGE_BYTES` is `too_large`
  and `message` is never called for it; a message announced small that arrives with
  `MAX_MESSAGE_BYTES + 1` bytes is `too_large` and is not saved; a UID with no size, a body of
  `None` and the tokens dropped by the search are `skipped`; a clock past the deadline moves every
  message not yet tried to `left` and stops; a `write_failed` raises `FetchRefused` carrying the
  outcome so far; `message` is asked for exactly the cap; the loop does not close the mailbox (the
  command that opened it does, and stage 5 tests that on every path); the module reads no
  time, environment or `sys.argv`. — RF-04, RF-05, RF-07, RF-08, RNF-03, RNF-04, ADR-8
- [x] `src/mailvigil/fetch/run.py`: `fetch_reports(mailbox, folder, since, store, limit, clock,
  deadline)` as in the design. — RF-04, RF-05, RF-07, RF-08, ADR-8
- [x] Quality gate of the stage: the same four commands. **Result:** ruff, black and mypy clean;
  2413 tests passed, coverage 100%.

## Stage 4 — The adapter to `imaplib` (RF-01 to RF-05, RF-10, RNF-01, RNF-02, ADR-2 to ADR-5)

- [x] `tests/test_fetch_imap.py`, pure functions, written first: the modified UTF-7 encoder
  against the RFC's examples (`Entwürfe` → `Entw&APw-rfe`, a lone `&` → `&-`, a run of accents,
  an emoji, `/` inside a run) and a folder with a control character refused; the quoted string with
  `\` and `"` escaped; the `SINCE` date in a locale other than English (`locale.setlocale` where
  available, or a monkeypatched `strftime` that would fail); the search parser on good answers, an
  empty answer, `None`, tokens that are zero, negative, over `UID_MAX`, hex, with a sign and with
  a decimal point; the size parser on lines with reordered attributes, with only one of the two
  numbers, with garbage and with a number of 10,000 digits; the validity parser. — RF-04, RF-05,
  RF-10, ADR-4
- [x] Same file, the connection: the context that reaches `IMAP4_SSL` has `verify_mode ==
  CERT_REQUIRED`, `check_hostname` and `minimum_version >= TLSv1_2`, and no path builds another one;
  the port only changes where to connect; `ssl.SSLCertVerificationError` is
  `certificate_invalid` and nothing was sent after the handshake; other `ssl.SSLError` is
  `tls_failed`; `socket.gaierror`, `ConnectionRefusedError` and `OSError` are `host_unreachable`;
  `TimeoutError` is `timeout`; a rejected login is `login_failed` with an empty `detail`; a
  password with a line break, empty or non-ASCII is `password_unusable` before the connection
  opens. — RF-01, RF-02, ADR-2, ADR-5
- [x] Same file, the bounds, over a `socket.socketpair()` with a scripted peer and the `_Bounds`
  mixin composed over plain `IMAP4`: a literal announced over the limit is refused before one byte
  of it is read; a literal that never ends and a silent peer end in `timeout`; an endless line and
  a `SEARCH` line over the limit are `protocol_error` and `too_many_matches`; a clock past the
  deadline between chunks ends the transfer; the limit is `LITERAL_OTHER` outside `message()` and
  `limit + 1` inside it; after an `abort` no `LOGOUT` is sent. — RF-05, RF-10, ADR-3
- [x] Same file, what goes on the wire, recorded by the scripted peer: only `CAPABILITY`, `LOGIN`,
  `EXAMINE`, `UID SEARCH`, `UID FETCH` and `LOGOUT` ever appear, with `BODY.PEEK[]<0.N>` and never
  `BODY[]`; the folder arrives quoted and encoded; a `NO` on `EXAMINE` is `folder_not_found`; the
  search carries `SUBJECT "Report Domain:"` with and without `SINCE`; sizes are asked in batches of
  `SIZE_BATCH`; `close` sends `LOGOUT` and ignores its failure. — RF-03, RF-04, ADR-3
- [x] Same file, secrets: with a canary password, no `detail`, no exception text and no recorded
  line sent after the login contains it, including when the server echoes it back in an error; a
  server error line with control characters and a bidirectional override comes out cleaned and at
  most 200 characters. — RNF-02, RF-10
- [x] `src/mailvigil/fetch/imap.py`: the pure helpers, `_Bounds`, `ImapMailbox`, `connect`, the
  error mapping and the secret scrubbing, as in the design. The only module of the product that
  imports `imaplib` and `ssl`. Docstrings with `Args:` / `Returns:` / `Raises:`. — RF-01 to RF-05,
  RNF-01, RNF-02, ADR-2 to ADR-5
- [x] Quality gate of the stage: the same four commands, on Python 3.12 and on the newest release
  (the mixin depends on two method names of the library; ADR-3). **Result:** ruff, black and mypy clean on 3.12 and 3.15; 2553 tests passed on both, coverage 100%.

## Stage 5 — The command (RF-02, RF-08, RF-09, ADR-7)

- [x] `tests/test_cli_fetch.py`, written first, through `main(argv)` and `capsys` with
  `mailvigil.fetch.imap.connect` replaced by a function returning a `FakeMailbox`: success with
  new messages (exit `0`, the six numbers, the files in `--to`); nothing new (exit `0`); each
  `FetchReason` as a refusal (exit `1`, one line on standard error, the saved count line when some
  were saved); the usage errors (exit `2`): no terminal and no `--password-file`, `--since` not a
  date, `--limit 0` and above `MAX_LIMIT`, `--port 0` and `70000`, a missing `--host`, `--user` or
  `--to`; the prompt through a patched `getpass.getpass` when stdin is a terminal; a password file
  with and without a trailing newline, an empty one, a missing one, a longer-than-4-KiB first line;
  on POSIX a file readable by group or others adds a warning and still works; `--lang pt-BR` is
  ASCII; the mailbox is closed on success and on every
  refusal; a canary password absent from standard output and error in every case above. — RF-02,
  RF-08
- [x] `tests/test_cli_fetch.py` (there is no `tests/test_cli.py`; the help tests live here) and `tests/help_golden.py` (the recorded text), first: `summary --help` and `verdict --help` are
  byte-identical to the ones before the parent parser split (compare with a recorded text), and
  `fetch --help` states that it connects, that it only reads, what happens to the password and that
  the certificate is always checked. `mailvigil --help` describes `fetch` as the one command that
  uses the network. — RF-08, RF-09, ADR-7
- [x] `tests/test_offline_isolation.py`: a fresh `python -I` subprocess imports `mailvigil.cli`,
  runs `summary` and `verdict` over a synthetic report and asserts that neither `imaplib` nor
  `mailvigil.fetch.imap` is in `sys.modules`; a second case runs `fetch` up to the user-name check (the real `connect` refuses it before any socket)
  and asserts they are loaded only then. — RF-09, ADR-7
- [x] `src/mailvigil/cli.py` (and `messages/`, one new sentence, `password_file_exposed`): split the shared parent parser into `reading` and `language`
  (`summary` and `verdict` take both, in the old order); the `fetch` subparser; `_run_fetch` with the
  lazy import of `fetch.imap` only (the other `fetch` modules load no network code) and its one comment saying why; the password source; `try` / `finally` around the
  mailbox. Update the module docstring and the architecture line. — RF-02, RF-08, RF-09, ADR-7
- [x] Quality gate of the stage: the same four commands. **Result:** ruff, black and mypy clean on 3.12 and 3.15; 2629 tests passed (1 POSIX-only skip on Windows) and coverage 100% on both.

## Stage 6 — Close the spec (RF-08, RF-09, RNF-01, RNF-07)

- [x] `README.md`: a `fetch` section with the command, what it does and does not do (read-only,
  verified TLS, password by prompt or file), the exit codes, the provider limits (Gmail with an
  app password; Microsoft 365 not supported, no OAuth) and a line saying a non-ASCII password is
  not accepted in this version. `CLAUDE.md`: the architecture tree (`fetch/`, `render_fetch.py`),
  the commands block, the ⚠️ "`imaplib` and `ssl` only in `fetch/imap.py`; never an unverified
  context; `summary` and `verdict` never load them", and the line on the project overview.
  `docs/stack.md`: `imaplib`, `ssl`, `getpass`, `os.replace`. Run `/atualizar-docs`. — RF-08, RF-09
- [x] `specs/README.md`: the roadmap row of 009 to **done**; the three statuses of the spec to
  `done`; the memory of the project updated in the same session.
- [x] Zero dependencies still true: `[project].dependencies` is empty, `uv build` succeeds and the
  CI `package` job passes. — RNF-01
- [ ] **Manual check by the maintainer, with a real mailbox (not in CI, nothing from it enters the
  repository):** run `mailvigil fetch` against his own mailbox; compare the number matched with the
  DMARC report messages he can count by hand (this closes the risk of the subject criterion, open
  question 3); run it again and confirm that nothing is saved; run `mailvigil verdict` over the
  folder; confirm in the mail client that no message was marked as read. If a provider's subject
  does not match, the criterion changes in `imap.py` with a test, in a new PR. — RF-03, RF-04,
  RF-07
- [x] Quality gate of the spec: `uv run ruff check .` → `uv run black --check .` → `uv run mypy` →
  `uv run pytest --cov`, then `uv build`. Record the result here, with the number of tests and the
  coverage. **Result:** 2026-10-28: ruff, black and mypy (34 source files) clean; 2629 tests passed and 1
  skipped (file modes, a POSIX idea), 100% coverage; `uv build` succeeds and the wheel declares 0
  `Requires-Dist`.

## Stage 7 — A provider with no IMAP (RF-08)

- [x] `messages/en.py` and `messages/pt_br.py`: the phrases of `LOGIN_FAILED` and
  `HOST_UNREACHABLE` say that the provider must allow IMAP and that otherwise the reports can be
  downloaded by hand and read with `summary` (a provider that has IMAP off answers like one of the
  two); the README says the same under Fetch. Test: both refusals mention IMAP and `summary` in
  both languages. — RF-08
- [x] Quality gate. — result recorded when run: ruff, black and mypy clean; pytest passed with
  coverage 100% (Python 3.12, 2026-10-29).

## Stage 8 — A private certificate authority (RF-01, ADR-10; issue #76)

- [x] `FetchReason.CAFILE_UNUSABLE` (`cafile_unusable`) and its sentence in both languages. Test:
  the thirteen keys are pinned and both catalogs cover them. — RF-08
- [x] `imap.build_context(cafile)` adds the file with `load_verify_locations`; `connect(cafile=)`
  builds the context before it opens anything. Tests: the system's authorities are all still there
  and the file's is added once; the verify mode, the host name check and the TLS floor are as
  before; a missing file, an empty one, text, a cut PEM and a folder are `cafile_unusable`; the
  source never passes an argument to `create_default_context`. — RF-01
- [x] `fetch --cafile FILE` in `cli_fetch.py`: checked before the password is asked for; the
  connection gets it. Tests: the argument reaches `connect` (and is `None` without the flag); an
  unusable file ends in exit 1 with no prompt and no connection. — RF-01, RF-08
- [x] Docs: README in both languages, SECURITY, `docs/stability.md`, `docs/stack.md`, `CLAUDE.md`,
  CHANGELOG `[Unreleased]`.
- [x] Quality gate. — **Result:** 2026-10-30: ruff, black and mypy (36 source files) clean; pytest passed
  at 100% coverage (Python 3.12, Windows).
