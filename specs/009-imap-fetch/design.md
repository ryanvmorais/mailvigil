---
feature: IMAP fetch — download the DMARC report messages from a mailbox into a folder (`mailvigil fetch`)
status: done
date: 2026-10-28
related:
  - 009-imap-fetch/requirements.md
  - 007-mail-message-input/design.md
  - 006-output-and-exit-codes/design.md
origin: conception
---

# 009 — IMAP fetch — design

## Overview

Nothing that reads reports changes. `fetch` is a new package next to `reports/`, reached only from
a new subcommand, and it ends where `007` begins: with `.eml` files in a folder.

```text
mailvigil fetch ─▶ cli._run_fetch (lazy import) ─▶ password (getpass | --password-file)
                                                       │
                       fetch/imap.py  ImapMailbox ◀────┘      the ONLY module that imports imaplib/ssl
                              │  (Mailbox protocol)
                              ▼
                       fetch/run.py  fetch_reports(mailbox, folder, since, store, limit, clock)
                              │  select → search → drop what is on disk → sizes → message, newest first
                              ▼
                       fetch/store.py  Store.has / Store.save   (<tag>-<validity>-<uid>.eml, atomic)
                              ▼
                       FetchOutcome ─▶ render_fetch (en | pt-BR)        later: mailvigil summary DIR
```

- **`fetch/imap.py`** is the only module that touches the network. It wraps `imaplib` behind a
  five-method `Mailbox` protocol, builds the verified TLS context, bounds every read, and turns
  every library failure into a typed `FetchRefused` (ADR-1, ADR-2, ADR-3).
- **`fetch/run.py`** is the whole fetch logic and knows nothing about IMAP: it drives a `Mailbox`
  and a `Store`, so the tests run it with a fake and no socket (ADR-1, RNF-03, RNF-06).
- **`fetch/store.py`** names, checks and writes files; it knows nothing about the network (ADR-6).
- **`cli.py`** gains the `fetch` subcommand. `imaplib` is imported inside `_run_fetch`, never at the
  top of the module, so `summary` and `verdict` cannot load it (ADR-7, RF-09).
- **Output:** a `FetchMessages` block in the catalog, one text renderer, no JSON (open question 4).

## Module layout

```text
src/mailvigil/fetch/
  __init__.py   # NEW  docstring only: it imports nothing, so messages/ can import fetch.errors
  errors.py     # NEW  FetchReason (StrEnum), FetchRefused
  model.py      # NEW  FetchOutcome, the constants, the Mailbox protocol
  store.py      # NEW  Store: file names, has, save (atomic), stale temp files
  run.py        # NEW  fetch_reports: the loop
  imap.py       # NEW  ImapMailbox, connect, the bounded IMAP4_SSL, mUTF-7, SINCE date, parsers
src/mailvigil/render_fetch.py            # NEW      render_fetch(outcome, directory, messages) → text
src/mailvigil/messages/model.py          # CHANGED  FetchMessages (+ FetchReason keyed mapping)
src/mailvigil/messages/en.py, pt_br.py   # CHANGED  the sentences
src/mailvigil/cli.py                     # CHANGED  `fetch` subcommand, parent parser split (ADR-7)
.gitignore                               # CHANGED  *.eml and *.mbox outside tests/ (RNF-07)
tests/test_fetch_imap.py, test_fetch_store.py, test_fetch_run.py, test_render_fetch.py,
tests/test_cli_fetch.py, test_offline_isolation.py, fetch_helpers.py          # NEW
README.md, CLAUDE.md, docs/stack.md      # CHANGED  at the end (the `/atualizar-docs` step)
```

`reports/`, `summary.py`, `verdict.py`, `senders.py`, `config.py`, `render*.py` (but the new one),
`htmlkit.py` and `docs/json-schema.md` do not change. `fetch/` imports `text` (to clean server text)
and nothing else of the product; `reports/` never imports `fetch/`.

## Data model

```python
class FetchReason(StrEnum):                    # errors.py: the key is the contract of the catalog
    HOST_UNREACHABLE = "host_unreachable"      # no DNS answer, connection refused, no route
    TIMEOUT = "timeout"                        # a read or the connect passed SOCKET_TIMEOUT
    DEADLINE_EXCEEDED = "deadline_exceeded"    # the run passed DEADLINE_SECONDS
    CERTIFICATE_INVALID = "certificate_invalid"  # verification failed: nothing was sent
    TLS_FAILED = "tls_failed"                  # handshake failed for another reason (old TLS…)
    LOGIN_FAILED = "login_failed"              # the server said NO/BAD to the login
    PASSWORD_UNUSABLE = "password_unusable"    # non-ASCII, empty or with a line break (ADR-5)
    PASSWORD_FILE = "password_file"            # missing, unreadable or empty
    FOLDER_NOT_FOUND = "folder_not_found"
    PROTOCOL_ERROR = "protocol_error"          # a response the bounds or the parser refuse
    TOO_MANY_MATCHES = "too_many_matches"      # the SEARCH line passed the library's line limit
    WRITE_FAILED = "write_failed"              # the disk refused (full, permission, interrupted)

class FetchRefused(Exception):                 # reason, detail (sanitized, ≤ 200), outcome | None

@dataclass(frozen=True, slots=True)
class FetchOutcome:                            # model.py
    matched: int      # messages the server listed for the search
    saved: int        # written in this run
    already: int      # found on disk by name, not downloaded
    too_large: int    # announced over the cap, or cut at the cap while arriving
    skipped: int      # an unusable UID, or a message the server would not give
    left: int         # new messages beyond --limit (or beyond the deadline), for a later run
```

`matched == saved + already + too_large + skipped + left` always holds; a test asserts it for every
scenario. A `FetchRefused` raised after some work carries the partial `FetchOutcome`, so the command
can say how many files are valid (RF-08).

Constants, in `model.py` (changing one is a spec decision):

| Constant | Value | Why |
|---|---|---|
| `SOCKET_TIMEOUT` | 30 s | One silent read ends the run; a slow link still moves 8 MiB in chunks |
| `DEADLINE_SECONDS` | 1800 | 500 messages of a few hundred KB fit on any usable link; more is a stuck run |
| `DEFAULT_LIMIT` / `MAX_LIMIT` | 500 / 10,000 | The newest 500 decide a verdict; 10,000 is a bounded disk |
| `SIZE_BATCH` | 100 UIDs | One short command line per batch; 500 messages cost 5 size queries |
| `LINE_LIMIT` | 1,000,000 bytes | The library's own `_MAXLINE`; a SEARCH answer over it is `too_many_matches` |
| `LITERAL_OTHER` | 64 KiB | The biggest literal any command but the message fetch may announce |
| `UID_MAX` | 2³² − 1 | The range IMAP allows for a UID and for a validity number (RFC 3501 §2.3.1.1) |

`MAX_MESSAGE_BYTES` is the one of `reports/mail.py` (8 MiB), imported, not copied: a message `fetch`
saves is always one `007` would accept.

## Components

### imap.py (RF-01 to RF-05, RNF-01, RNF-02)

- **`Mailbox`** (a `Protocol`, in `model.py`):
  `select(folder) -> int` (read-only; returns the validity number) ·
  `search(since: date | None) -> SearchResult` (the valid UIDs, ascending, and the count of dropped tokens) ·
  `sizes(uids) -> dict[int, int]` (announced sizes) ·
  `message(uid, limit) -> bytes | None` (at most `limit + 1` bytes; `None` when the server gives
  no body) · `close() -> None`.
- **`connect(host, port, user, password, clock, deadline) -> ImapMailbox`**: builds
  `ssl.create_default_context()` (certificate chain and host name verified, TLS 1.2 or newer) and
  passes it to the connection; the library's own default does **not** verify (ADR-2). Opens with
  `timeout=SOCKET_TIMEOUT`, logs in (ADR-5) and returns the wrapper. `ssl.SSLCertVerificationError`
  is `certificate_invalid`, other `ssl.SSLError` is `tls_failed`, `socket.gaierror`,
  `ConnectionError` and `OSError` are `host_unreachable`, `TimeoutError` is `timeout`. The
  credential is sent only after the handshake, which is after verification: a failed certificate
  has seen nothing.
- **The bounded connection** — a mixin `_Bounds` over `imaplib.IMAP4_SSL` (a test composes it over
  plain `IMAP4` and a local socket pair) overrides two methods the library documents as replaceable
  (`read`, `readline`):
  - `read(size)`: `size > self.max_literal` raises `imaplib.IMAP4.abort` before one byte is read
    (a server that announces a huge literal is refused, not obeyed), then reads in 64 KiB slices
    through the library's own `read`, checking the deadline between slices and setting the socket
    timeout to the time left. (Not `read1` on `self.file`: Python 3.15 reads from the socket
    itself and has no `self.file`.) `max_literal` is `LITERAL_OTHER` by default and `limit + 1` only while `message()` runs.
  - `readline()`: sets the socket timeout to `min(SOCKET_TIMEOUT, time left)`, then the library's
    own bounded line read (1,000,000 bytes). An `abort` or an oversized line is `protocol_error`
    (`too_many_matches` when it happens during the SEARCH). `imaplib` re-wraps every `abort`, so the
    connection keeps an `overlong` flag the mailbox reads.
  After an `abort` the connection is shut down at the socket and no `LOGOUT` is attempted; in every
  other end `close()` sends `LOGOUT` and ignores its failure (RF-03).
- **`select(folder)`**: rejects a folder with a control character (< 0x20, 0x7f) before it is sent
  (a line break would inject a command); encodes it as modified UTF-7 and quotes it (ADR-4); sends
  `EXAMINE` through `select(..., readonly=True)`; a `NO` is `folder_not_found`. The validity number
  is read from the `UIDVALIDITY` response and must be an integer in 1..`UID_MAX`, else
  `protocol_error`.
- **`search(since)`**: `UID SEARCH [SINCE dd-Mon-yyyy] SUBJECT "Report Domain:"`. The date is built
  from a fixed table of English month names, never `strftime`, because IMAP wants English whatever
  the locale. The answer is split on whitespace; a token that is not an integer in 1..`UID_MAX` is
  dropped and counted as `skipped` by the caller (the method returns the clean list and the count of
  dropped tokens in a small result type).
- **`sizes(uids)`**: `UID FETCH u1,u2,… (RFC822.SIZE)` in batches of `SIZE_BATCH`. Each response
  line must match `\d+ \((?:(?:UID|RFC822\.SIZE) \d+ ?)+\)` (the attributes come in any order, as
  servers differ); a line that does not match, or lacks one of the two numbers, is ignored, and a
  requested UID with no size is `skipped` by the caller.
- **`message(uid, limit)`**: `UID FETCH uid (BODY.PEEK[]<0.{limit + 1}>)`. `PEEK` leaves `\Seen`
  alone (RF-03) and the partial form asks the server for at most `limit + 1` bytes; the bounded
  `read` is the second line of defense against a server that ignores it (RF-05). The body is the
  second item of the first response tuple; anything else is `None`.
- **Commands the class can send:** a closed set — `CAPABILITY` (the library's own), `LOGIN`,
  `EXAMINE`, `UID SEARCH`, `UID FETCH`, `LOGOUT`. A test records what a fake server receives and
  asserts membership in that set (RF-03).
- **Secrets:** `detail` of a refusal is `clean_text` of the library's message, cut at 200 and with
  every occurrence of the password replaced by `***`. A `login_failed` carries no server text at
  all. The library's debug level stays 0 (`imaplib.Debug`), which would print the login line.

### store.py (RF-06, RF-07)

- **`Store(directory: Path, tag: str)`**; `tag` is the first 8 hex digits of
  `sha256(f"{host}\0{user}\0{folder}")` — characters the program chose, so two mailboxes saving into
  one folder cannot take each other's files (ADR-6).
- **`name(validity, uid) -> str`** is `f"{tag}-{validity}-{uid}.eml"`, built from the tag and two
  integers already range-checked; nothing a third party writes reaches a path (RF-06).
- **`has(validity, uid) -> bool`**: `is_file()` of that name.
- **`save(validity, uid, data) -> None`**: creates the directory (`parents=True`), writes to a
  unique temporary file in the same directory (`tempfile.mkstemp(prefix=".mailvigil-",
  suffix=".partial")`), `flush` and `fsync`, then `os.replace` onto the final name. Any `OSError` is
  `write_failed`, and the temporary file is removed on every path out. `os.replace` is atomic on
  Windows and Linux (RNF-05).
- **`clean_stale()`** removes `.mailvigil-*.partial` files older than a day, once per run, so a
  crash leaves nothing for long (RF-06). A younger one may belong to a run in progress.

### run.py (RF-04, RF-05, RF-07, RF-08, RNF-04)

`fetch_reports(mailbox, folder, since, store, limit, clock, deadline) -> FetchOutcome`:

1. `store.clean_stale()`; `validity = mailbox.select(folder)`.
2. `found = mailbox.search(since)`, newest first (UID descending: UIDs grow with arrival).
   `matched = len(found) + dropped tokens`; the dropped tokens start `skipped`.
3. Split `found` into `already` (`store.has`) and `new`. `new[limit:]` is `left`; the rest is `todo`.
4. `sizes = mailbox.sizes(todo)`; a UID with no size is `skipped`; a size over `MAX_MESSAGE_BYTES` is
   `too_large` and is never requested.
5. For each remaining UID, in order: past `deadline` → everything not yet tried joins `left`; stop.
   `data = mailbox.message(uid, MAX_MESSAGE_BYTES)`; `None` → `skipped`; `len(data) >
   MAX_MESSAGE_BYTES` → `too_large`; else `store.save`. A `write_failed` ends the run: it raises
   `FetchRefused` carrying the outcome so far; any refusal raised after the search (sizes,
   message) carries it too, with the messages not tried counted in `left`.
6. Return the `FetchOutcome`. The caller closes the mailbox in a `finally`.

The function takes `clock` and `deadline` as arguments and never reads the time itself, so a test
moves time by hand.

### render_fetch.py and the command (RF-02, RF-08, RF-09)

`render_fetch(outcome, directory, messages) -> str` writes the six numbers and the folder, ASCII,
at most 80 columns, with the words from `FetchMessages` (`directory` goes through `clean_text`
like every echoed path). A refusal line is
`mailvigil: <phrase of the reason>[: <detail>]` on standard error, as `summary` does, followed on a
second line by `N message(s) were saved before it stopped` when the partial outcome has `saved > 0`.

`cli._run_fetch(args)`:

1. Lazy `from mailvigil.fetch import …` (ADR-7).
2. The password: `--password-file` → read at most 4 KiB, first line, trailing `\r\n` removed
   (`password_file` if missing, unreadable or empty); on POSIX a mode with group or other bits set
   adds a warning line on standard error, not a refusal. Else, if `sys.stdin.isatty()`,
   `getpass.getpass()`; else `parser.error("no terminal: give the password in a file with
   --password-file")`, which is exit `2` (RF-02). A password that is empty, non-ASCII or has a line
   break is `password_unusable` (ADR-5).
3. `store = Store(args.to, tag)`; `mailbox = connect(...)`; `try: outcome = fetch_reports(...)
   finally: mailbox.close()`.
4. `FetchRefused` → one line on standard error, `EXIT_REFUSED`. Else print and `EXIT_OK`.

The tests replace `connect` at the one place the command module looks it up
(`monkeypatch.setattr` on `mailvigil.fetch.imap.connect`, called through the module attribute), so
the CLI test opens no socket.

## Interfaces

```text
mailvigil fetch --host HOST --user NAME --to DIR
                [--port N] [--folder NAME] [--since YYYY-MM-DD] [--limit N]
                [--password-file FILE] [--lang {en,pt-BR}]
```

| Option | Rule |
|---|---|
| `--host`, `--user`, `--to` | required |
| `--port` | integer 1..65535, default 993; always implicit TLS (RF-01) |
| `--folder` | default `INBOX`; no control characters |
| `--since` | `date.fromisoformat`; an invalid value is argparse's usage error (exit 2) |
| `--limit` | integer 1..`MAX_LIMIT`, default `DEFAULT_LIMIT` |
| `--password-file` | see the command, step 2 |
| `--lang` | the same parent parser as `summary` and `verdict` (ADR-7) |

Exit codes are the existing contract, no new code: `0` completed (even with nothing new), `1`
refused (any `FetchRefused`), `2` usage. There is no `--json` and no `--insecure`.

The help of `fetch` says: it connects to a server; it only reads (it never changes, moves or
deletes mail and does not mark it read); the password is asked for or read from a file and is never
an argument, a variable or a stored value; the certificate is always checked.

## Architecture decisions

### ADR-1 — The fetch logic runs against a protocol, not against `imaplib`

- **Decision:** `run.py` talks to a five-method `Mailbox` protocol; `imap.py` is the one adapter to
  `imaplib`. Tests use a `FakeMailbox` for the logic and a socket pair for the adapter's bounds.
- **Alternatives:** patch `imaplib.IMAP4_SSL` with `unittest.mock`; run a fake IMAP server on
  `127.0.0.1`.
- **Why:** a mock of the library tests the mock, and a localhost server opens a socket, which
  RNF-06 forbids and a CI sandbox may refuse. The protocol keeps the counting, ordering and
  idempotence logic (most of the bugs) testable with plain Python objects.
- **Trade-off:** the adapter is covered by narrower tests (parsers, the bounded reads over a
  local `socket.socketpair()`, the context's properties), not by a full IMAP conversation. The first
  real run by the maintainer is the end-to-end check, recorded in `tasks.md`.

### ADR-2 — The TLS context is built by us; the library's default is not used

- **Decision:** the connection receives `ssl.create_default_context()`; no code path builds an
  unverified one, and a test asserts `verify_mode == CERT_REQUIRED`, `check_hostname` and
  `minimum_version >= TLSv1_2` on the context that reaches the connection.
- **Alternatives:** leave `IMAP4_SSL` to its default.
- **Why:** checked on 2026-10-28 in the source of Python 3.12.13 and 3.15.1: when no context is
  given, `IMAP4_SSL` calls `ssl._create_stdlib_context()`, which is `_create_unverified_context`
  and does **not** verify the server. A tool
  that sends a password and says "TLS" would be open to anyone on the path. This is the main
  security finding of the spec, which is why RF-01 forbids any switch.
- **Trade-off:** a server with a self-signed or private-CA certificate is refused. The platform
  trust store is the only trust there is; adding a `--cafile` is a later spec if someone needs it.

### ADR-3 — Bounds live in the connection, not only in the caller

- **Decision:** a mixin overrides `read` and `readline` to refuse an announced literal over the
  current limit, to read literals in chunks under a deadline, and to set the socket timeout to the
  time left.
- **Alternatives:** trust `imaplib` (it reads a literal of any announced size, in chunks, and its
  memory grows with what the server sends); wrap `socket` ourselves.
- **Why:** the caller never sees bytes until the library has finished reading them, so a check
  after `uid("FETCH", …)` is a check after the damage. `read` and `readline` are the documented
  seam, and refusing by the announced size stops the transfer before it starts. The partial fetch
  (`<0.N>`) and the size query are polite requests; this is the enforcement.
- **Trade-off:** a subclass of a standard library class depends on two method names staying; the
  tests run on 3.12 and the newest release, and a change there breaks a test, not a user. A server
  that drips one byte per timeout inside a single *line* can keep a run past the deadline, by at
  most one line (1,000,000 bytes), because the deadline is checked between commands and between
  chunks of a literal; it cannot exhaust memory or disk. Accepted: the server is the user's own.

### ADR-4 — Folder names: encoded, quoted and checked by us

- **Decision:** a folder name is modified UTF-7 (RFC 3501 §5.1.3: `&` becomes `&-`, a run of other
  characters becomes `&` + base64 of UTF-16BE with `,` for `/` + `-`), then a quoted string with `\`
  and `"` escaped. A name with a control character is refused before it is sent.
- **Alternatives:** pass the name through unchanged (breaks `Sent Items`, `INBOX.Relatórios`);
  send it as a literal (needs `LITERAL+` or a continuation round trip).
- **Why:** `imaplib` sends arguments as they are, so quoting and encoding are ours; skipping them
  makes the command fail on a space and obey a line break. The encoder is about fifteen lines and a
  test pins it to the RFC's own example (`Entw&APw-rfe` for `Entwürfe`).
- **Trade-off:** the decoder is not written (the tool never lists folders), so a folder the user
  mistypes shows the server's refusal instead of a suggestion.

### ADR-5 — `LOGIN`, ASCII credentials (the ASCII limit is lifted by ADR-9)

- **Decision:** the login uses the `LOGIN` command through the library. A user name or password
  that is empty, has a control character or is not ASCII is `password_unusable` before the
  connection opens (for the user name, a usage error).
- **Alternatives:** `AUTHENTICATE PLAIN` with UTF-8 (supports any password, needs `AUTH=PLAIN`
  advertised, and one more path to test); both, falling back by character set.
- **Why:** `LOGIN` is what every IMAP server accepts over TLS, and the library quotes the password
  correctly. The ASCII limit is the library's (`imaplib` encodes with `ascii`), and a visible,
  early refusal is better than a `UnicodeEncodeError` halfway.
- **Trade-off:** a password with an accented letter does not work in this version. It is the one
  decision here the maintainer should confirm; the fallback to `PLAIN` is a small, separate change.

### ADR-6 — File names: a tag, the validity number and the UID

- **Decision:** `<tag>-<validity>-<uid>.eml` (see `store.py`). The tag is a hash of host, user and
  folder, so it is stable between runs and different between mailboxes.
- **Alternatives:** `<validity>-<uid>.eml` alone, as the requirements sketched; a hash of the message
  content; the subject or `Message-ID`.
- **Why:** the validity number is chosen per mailbox, often as a timestamp, and UIDs start at 1: two
  accounts fetched into one folder can produce the same pair, and the second would be taken as "already
  there" and never saved, a silent loss of a report. A content hash needs the download, which defeats
  the idempotence check. Subject and `Message-ID` are third-party text (RF-06).
- **Trade-off:** the name says nothing to a human. That is fine: the folder is read by the tool,
  and `007` shows the origin by the attachment. This refines RF-06 and RF-07, which named only the
  validity number and the UID.

### ADR-7 — `fetch` is imported lazily, and the parent parser is split

- **Decision:** `cli.py` imports `mailvigil.fetch` inside `_run_fetch`. The shared parent parser
  becomes two, `reading` (paths, `--config`, `--domain`, `--json`) and `language` (`--lang`);
  `summary` and `verdict` take both in the same order, so their help does not change, and `fetch`
  takes only `language`.
- **Alternatives:** import at the top (then `import mailvigil.cli` loads `imaplib` and RF-09 fails);
  copy the `--lang` definition into the `fetch` parser.
- **Why:** RF-09 is about what runs for `summary` and `verdict`, and both live in `cli.py` with
  `fetch`. A lazy import is the smallest thing that keeps the module graph honest, and the
  fresh-interpreter test checks it. `messages/` imports `fetch.errors`, which is why
  `fetch/__init__.py` imports nothing.
- **Trade-off:** an import inside a function against the usual style; one comment says why.

### ADR-8 — Newest first, and a limit on new messages

- **Decision:** UIDs are processed in descending order, and `--limit` counts only messages not yet
  on disk.
- **Alternatives:** oldest first; counting the ones already saved.
- **Why:** the newest reports are the ones a verdict about *today's* mail needs, and a first run on
  a large mailbox gets those first; the next run continues backwards. Counting saved ones would make
  a rerun with the same limit do nothing once the folder holds that many.
- **Trade-off:** after an interrupted first run the folder has a recent window and a gap behind it,
  and the verdict's "too early" rule says so honestly until a later run fills it.

### ADR-9 — A login outside ASCII goes by `AUTHENTICATE PLAIN` (amendment of 2026-10-30, issue #74)

- **Decision:** the login is chosen from the credentials. A user name and a password that are both
  printable ASCII keep using `LOGIN`, exactly as in ADR-5. When either has a character outside
  ASCII, the adapter looks at the `CAPABILITY` the library already read at the greeting: with
  `AUTH=PLAIN` it sends `AUTHENTICATE PLAIN`, whose one response is the base64 of
  `NUL user NUL password` encoded as UTF-8 (RFC 4616); without it the run ends in
  `password_unusable`. This happens after the handshake, so the certificate was verified and no
  secret has been sent. The rule on what is usable at all changes from "printable ASCII" to "not
  empty, no control character of C0, DEL or C1 (NUL is the `PLAIN` separator), and encodable as
  UTF-8"; a user name that fails it is still a usage error (exit 2). No new flag, no new reason,
  no new state; only the text of `password_unusable` changes, in both languages.
- **Alternatives:** `ENABLE UTF8=ACCEPT` and then `LOGIN` (RFC 6855), chosen by capability, which
  adds a command to the closed set and another path to test for the same reach, since a server that
  takes UTF-8 over TLS advertises `AUTH=PLAIN`; `PLAIN` for every login, which changes what works
  today for ASCII passwords; keeping the refusal (ADR-5).
- **Why:** `LOGIN` has no defined encoding outside ASCII, while `PLAIN` is UTF-8 by definition. The
  verified TLS of ADR-2 is what makes sending a password in `PLAIN` acceptable, and `AUTHENTICATE`
  is the one command added to the closed set of ADR-1. The `imaplib` call takes a function for the
  response, so the secret is built in the adapter and never reaches a command line or a log. The
  scrubbing of server text also covers the password as its UTF-8 bytes read as ASCII (one
  replacement character per byte) and in base64, next to the forms of ADR-5; a refused login still
  shows no server text at all.
- **Trade-off:** the text is sent as typed, with no SASLprep (RFC 4013) normalisation, so a
  password typed as a composed letter on one keyboard and a decomposed one on another does not
  match on a server that normalises. A server without `AUTH=PLAIN` (or with `LOGINDISABLED`) still
  refuses a non-ASCII login.

## Impact

- **New:** the `fetch/` package, `render_fetch.py`, the `fetch` subcommand, twelve reason sentences
  and the outcome texts in two languages. `[project].dependencies` stays empty.
- **Changed:** `cli.py` (subcommand, split parent parser, lazy import), `messages/`, `.gitignore`.
  The `--json` documents, `docs/json-schema.md` and the exit codes do not change.
- **Docs:** README gets a `fetch` section with the provider limits (Gmail with an app password,
  Microsoft 365 not supported, no OAuth); CLAUDE.md gets the architecture lines and the
  ⚠️ "`imaplib` only in `fetch/imap.py`; never an unverified context"; `docs/stack.md` gets
  `imaplib`, `ssl`, `getpass`, `os.replace`.
- **CI:** nothing; the tests open no socket. CodeQL may flag a password read; it is read from a
  prompt or a file by design.

## Risks

- **A provider writes the report subject differently** and `SUBJECT "Report Domain:"` misses it.
  Mitigation: the criterion is RFC 7489's; the maintainer's first real run compares the number
  matched with the reports he already has, and any mismatch becomes a change of the criterion. No
  real report may enter the repository to check this, so it is a manual step in `tasks.md`.
- **A server with a different `UIDVALIDITY` policy** (changes it on every session) makes every run
  download everything again. The ingestion deduplicates, so the verdict is right, only slower.
- **Windows file locks:** `os.replace` over a file another process has open raises
  `PermissionError`, reported as `write_failed`; a rerun succeeds. Rare, since the target does not
  exist on the first save.
- **The mixin and the library's internals** (ADR-3): covered by running the tests on both Python
  versions of the CI matrix.

## Tests

Following [specs/README.md](../README.md#how-a-spec-is-tested). No test opens a connection.

- **`test_fetch_imap.py`:** the modified UTF-7 encoder against the RFC's examples; the `SINCE` date
  in any locale; the three response parsers with good lines, reordered attributes, garbage and
  oversized numbers; the context properties (ADR-2); the commands sent, recorded from a scripted
  server on a `socket.socketpair()`, all inside the closed set (RF-03); the bounded `read`: a
  literal announced over the limit, a literal that never ends, a silent peer (timeout), an endless
  line, a clock past the deadline between chunks (RF-05, RF-10); the error mapping, with a canary
  password that must appear nowhere in any `detail` (RNF-02).
- **`test_fetch_store.py`:** the name from a tag and two integers; a hostile folder and user give a
  tag of eight hex digits and nothing else; atomic save (a failing `os.replace`, a failing write,
  a disk-full `OSError` — no `.eml` and no temp file left); a stale temp file removed and a young
  one kept; two saves of one message leave one correct file (RF-06, RF-07).
- **`test_fetch_run.py`:** with a `FakeMailbox`: the counts add up in every scenario; newest first;
  `--limit` counts new messages only; a rerun saves nothing; a changed validity number downloads
  again; a size over the cap is never requested; a message announced small that arrives large is
  `too_large`; a UID with no size, a token out of range and a body of `None` are `skipped`; a
  deadline moves the rest to `left`; a write failure raises with the partial outcome; the mailbox is
  closed on every path.
- **`test_render_fetch.py`:** the text in both languages, ASCII, within 80 columns, with a hostile
  directory name cleaned; the refusal lines.
- **`test_cli_fetch.py`:** `main(argv)` with `capsys` and `connect` replaced: success, nothing new,
  each refusal reason with exit `1`, the usage errors with `2` (no terminal and no password file, a
  bad `--since`, `--limit 0`), the password prompt through a patched `getpass`, a password file with
  and without a trailing newline, a canary password absent from standard output and error.
- **`test_offline_isolation.py`:** a fresh `python -I` subprocess imports `mailvigil.cli`, runs
  `summary` and `verdict` over a synthetic report and asserts that neither `imaplib` nor
  `mailvigil.fetch.imap` is in `sys.modules`. (`ssl` and `socket` are not asserted: other standard
  library modules may load them.) A second case runs `fetch` and asserts they are then present
  (RF-09).
- **Synthetic only:** hosts under `.invalid`, invented users, canary passwords, messages built in
  `fetch_helpers.py` from the ranges of 007 (RNF-06).
- **Quality gate last:** `ruff` → `black --check` → `mypy` → `pytest --cov`, with its real result
  recorded in `tasks.md`.

## Refinements of the requirements

The design closes these points the requirements left to it; none changes a requirement's intent.

1. **File name** gains a tag (ADR-6): RF-06 and RF-07 still hold, with the tag in front.
2. **Leftover temporary files** are not "replaced" (each run uses a unique name): they are never
   read, and the ones older than a day are removed (RF-06).
3. **The deadline** is checked between commands and between chunks of a literal, not inside one
   line (ADR-3, RF-05).
4. **Non-ASCII passwords** were refused in 1.0 (ADR-5, RF-02); since the amendment they go by
   `AUTHENTICATE PLAIN` when the server offers it (ADR-9).
5. **The subject criterion** is closed as `SUBJECT "Report Domain:"` and verified by the
   maintainer's first real run (open question 3, Risks).
