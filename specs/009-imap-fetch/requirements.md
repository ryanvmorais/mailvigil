---
feature: IMAP fetch — download the DMARC report messages from a mailbox into a folder (`mailvigil fetch`)
status: done
date: 2026-10-28
related:
  - 007-mail-message-input/requirements.md
  - 002-report-ingestion/requirements.md
  - 006-output-and-exit-codes/requirements.md
origin: conception
---

# 009 — IMAP fetch

## Context and problem

[007](../007-mail-message-input/) removed the manual step of saving each attachment: the person
exports a mail folder to `.eml` or `.mbox` and points the tool at it. The export itself is still
manual, and it has to be repeated every time the verdict needs fresher reports. Deciding on
`p=reject` takes weeks of reports, so the real workflow is "look again each week", and that
workflow wants one command, not a mail-client export.

IMAP is the one protocol every provider offers for this, and Python's standard library speaks it
(`imaplib`, `ssl`), so the promise of zero runtime dependencies survives. The command this spec adds
is `mailvigil fetch`: it connects to a mailbox, finds the report messages, and saves each one,
untouched, as an `.eml` file in a folder the person chooses. Reading what was saved is the job of
[007](../007-mail-message-input/) and of the commands that already exist.

This is the first time MailVigil opens a network connection, the first time it handles a
credential, and the first time it writes a file. The product promise says `summary` and `verdict`
are offline; that promise is kept by keeping the fetch a **separate, opt-in command** that shares no
code path with them. Every property below follows from that: the network, the secret and the write
are confined to one command that does nothing else.

The mailbox server is the user's own, but what it sends back is still input: declared sizes can be
wrong, a message can be bigger than announced, a name can be hostile. The rule of 002 and 007 holds:
every defense has a test that feeds it the attack.

## Goals

- **One command that brings the reports home:** `mailvigil fetch`, from a mailbox to a folder, with
  no step in the middle.
- **Safe by construction:** TLS with certificate verification and no way to turn it off, a
  password that never appears in the process list, the shell history or the repository.
- **Read-only on the server:** the mailbox is never changed, not even a "read" flag.
- **Incremental:** running it again downloads only what is new, so it can run from `cron`.
- **Bounded:** the size of a message, the number of messages and the time spent waiting are capped,
  whatever the server says.
- **Opt-in and isolated:** `summary` and `verdict` stay offline and gain no network option.

## Non-goals

- **Reading the saved messages:** spec `007` and the commands that exist. `fetch` saves bytes and
  never opens the report inside (no parsing, no summary of what was fetched).
- **Changing the mailbox:** no delete, move, copy, flag or expunge, not even "mark as read" and not
  even as an option. A tool that reads reports must not be able to lose mail.
- **OAuth 2 / XOAUTH2:** it needs a registered application, a browser sign-in and a call to a token
  endpoint. Providers that have turned off passwords for IMAP (Microsoft 365, and Google accounts
  without an app password) are therefore out of reach in this version; the README says so.
- **Plain-text IMAP, STARTTLS and `--insecure`:** the connection is implicit TLS (port 993) with
  the platform's certificate verification, or it does not happen.
- **Other protocols:** POP3, Exchange Web Services, Microsoft Graph, Gmail API.
- **Running as a service:** no daemon, no IDLE, no scheduler. `cron` or Task Scheduler call the
  command; the exit codes are the signal.
- **Several accounts or folders in one call:** one account and one folder per run; a script calls it
  again for the next.
- **Storing the password:** no keyring, no config-file field, no cache. See RF-02.
- **Sending mail,** as already decided in [specs/README.md](../README.md#permanent-non-goals).

## Personas

- As the **maintainer** (and any domain owner), I want to run one command each week and then ask for
  the verdict, so that "is it safe to move to `reject`?" is answered from the latest reports.
- As a **cautious user,** I want to know before I run it that the tool cannot delete my mail, cannot
  leak my password and cannot be tricked into a plain-text connection.
- As a **user with a scheduled job,** I want a rerun to be cheap and to save only what is new, and I
  want the exit code to tell me whether it worked.
- As a **contributor,** I want the network code in one small module that takes a connection I can
  fake, so that the tests never open a socket.

## Functional requirements

### RF-01 — Connect only over verified TLS

- **Given** `--host mail.example.invalid` and no `--port`
  **When** `fetch` connects
  **Then** it uses implicit TLS on port 993, the default SSL context of the platform (certificate
  chain and host name checked, TLS 1.2 or newer), and the connection has a timeout (value closed in
  the design) so that a silent server cannot hang the command.
- **Given** a certificate that does not verify (expired, wrong host name, untrusted issuer)
  **When** `fetch` connects
  **Then** it stops before sending any credential, prints a message that names the cause in plain
  language, and exits with the code of a refusal (RF-08). There is no flag, option or environment
  variable that skips the check.
- **Given** `--cafile FILE` with a PEM file that holds a private certificate authority
  **When** `fetch` connects to a server whose certificate that authority signed
  **Then** the certificate is accepted, because the authority is trusted in addition to the system's;
  the chain and the host name are still checked, and a server signed by neither is still refused.
  The file can only add trust (ADR-10).
- **Given** a `--cafile` that is missing, cannot be read or holds no certificate
  **When** `fetch` starts
  **Then** it ends in `cafile_unusable` before the password is asked for and before any connection.
- **Given** a `--port` other than 993
  **When** `fetch` connects
  **Then** it is still implicit TLS; the port is only where to connect, never a switch to plain text.
- **Given** a host that cannot be reached (name does not resolve, connection refused, timeout)
  **When** `fetch` connects
  **Then** it exits with a refusal and a message that says which of these happened, with no stack
  trace.

### RF-02 — Authenticate without leaking the secret

- **Given** `--user NAME` and a terminal
  **When** `fetch` runs
  **Then** it asks for the password without echoing it (`getpass`) and uses it for this run only.
- **Given** `--password-file PATH`
  **When** `fetch` runs
  **Then** it reads the password from the first line of that file (trailing newline removed),
  which is how a scheduled job supplies it without a terminal.
- **Given** the password
  **When** it is looked for anywhere else
  **Then** it is not an option of the command line (it would show in the process list and the shell
  history), not a field of the config file, not an environment variable, and it is never printed,
  logged, or included in an error message, including the server's own messages.
- **Given** no terminal and no `--password-file`
  **When** `fetch` runs
  **Then** it exits with a usage error that says how to give the password, and does not hang waiting
  for input.
- **Given** the server rejects the login
  **When** `fetch` runs
  **Then** it exits with a refusal that says the login failed, without echoing what the server
  answered beyond a sanitized, truncated line, and without retrying.

### RF-03 — Read-only access to the mailbox

- **Given** any run
  **When** the folder is opened
  **Then** it is opened read-only (`EXAMINE`), and messages are read with `BODY.PEEK[]`, so no flag
  (`\Seen` included) changes.
- **Given** the whole command
  **When** the IMAP commands it can send are listed
  **Then** the list holds no `STORE`, `COPY`, `MOVE`, `DELETE`, `EXPUNGE`, `APPEND`, `CREATE`,
  `RENAME` or `SUBSCRIBE`, and a test asserts that against the commands a fake server records.
- **Given** the run ends, by success or by failure
  **When** the connection is closed
  **Then** it is closed with `LOGOUT` where possible and never left to the garbage collector.

### RF-04 — Select which messages to fetch

- **Given** `--folder NAME` (default `INBOX`)
  **When** `fetch` runs
  **Then** it searches that folder only. A folder name is passed to the server as given, encoded as
  IMAP requires for non-ASCII names (modified UTF-7); a folder that does not exist is a refusal that
  says so.
- **Given** `--since DATE` (an ISO date, `2026-10-01`)
  **When** `fetch` searches
  **Then** the server is asked for messages received on or after that date (`SINCE`); without it, the
  search has no date bound, and the cap of RF-05 is what stops a first run on a large mailbox.
- **Given** any search
  **When** `fetch` asks the server
  **Then** it also asks for a subject containing `Report Domain:` (what RFC 7489 §7.2.1.1 asks
  report senders to write), so the server does the filtering and the command never downloads the
  user's other mail to look at it. The exact criterion is closed in the design after checking the
  subjects the main providers use.
- **Given** `--domain` or a config file
  **When** `fetch` searches
  **Then** nothing about the domain is sent to the server beyond the subject criterion above;
  the domain filter stays where it is, in the ingestion (002).
- **Given** a message that matches the subject but is not a report
  **When** it is saved
  **Then** nothing special happens: it is saved like the others, and the ingestion ignores it, as in
  007. `fetch` does not look inside messages.

### RF-05 — Bounds on what the server can make us do

- **Given** a message the server announces as larger than `MAX_MESSAGE_BYTES` (the cap of 007)
  **When** `fetch` is about to download it
  **Then** it is not downloaded, and it is counted as too large in the outcome (RF-08).
- **Given** a message whose announced size is small but whose body, as it arrives, passes
  `MAX_MESSAGE_BYTES`
  **When** `fetch` downloads it
  **Then** the transfer is cut at the limit plus one byte, the message is discarded and counted as
  too large; the cap acts on bytes actually received, never on a declared size.
- **Given** more matching messages than `--limit N` (default closed in the design)
  **When** `fetch` runs
  **Then** it downloads at most `N` new messages, newest first, and says how many matched and were
  left; running again fetches the next ones.
- **Given** a server that sends an endless line, a literal larger than it announced, or silence
  **When** `fetch` reads the response
  **Then** the read is bounded in size and in time, the run stops with a refusal and the program does
  not run out of memory or hang.
- **Given** a server that sends a message identifier (UID) that is not a positive integer within
  the range IMAP allows
  **When** `fetch` receives it
  **Then** that message is skipped with a counted reason and nothing derived from the text is used
  in a path (RF-06).

### RF-06 — Save the raw messages safely

- **Given** `--to DIR` (required; there is no default, so nothing lands in a place the user did not
  choose)
  **When** a message is saved
  **Then** it goes into `DIR` as one `.eml` file with the bytes exactly as received, and `DIR` is
  created if missing.
- **Given** the file name
  **When** it is built
  **Then** it is made only of characters the program chose and digits from the server (the folder
  validity number and the UID), never of any text a third party controls (subject, sender, folder
  name), so it cannot contain a separator, a `..`, a reserved Windows name or a control character,
  and the file lands inside `DIR` and nowhere else.
- **Given** a file that already exists under that name
  **When** `fetch` would save a message
  **Then** it is not overwritten and not downloaded again (RF-07).
- **Given** a write that fails half way (disk full, permission denied, the run is interrupted)
  **When** the run ends
  **Then** no partial `.eml` is left under its final name: the message is written to a temporary
  name in `DIR` and renamed only when complete, and a leftover temporary file is replaced on the next
  run.
- **Given** the saved files
  **When** they are read by `summary` or `verdict`
  **Then** they are ingested exactly like any `.eml` given by the user (007), with no special case.

### RF-07 — Incremental: a rerun saves only what is new

- **Given** a folder where earlier runs saved messages
  **When** `fetch` runs again against the same mailbox and folder
  **Then** the messages already saved are recognized by their file name (folder validity number and
  UID) and are neither downloaded nor counted as new.
- **Given** the server reports a different validity number for the folder (the UIDs were reset)
  **When** `fetch` runs
  **Then** the old files are kept, the messages are downloaded under the new number, and the
  ingestion's deduplication (RF-08 of 002) removes the repeated reports.
- **Given** two runs that overlap in time on the same `DIR`
  **When** both save the same message
  **Then** the result is one correct file, never two or a damaged one (the rename of RF-06 is the
  guarantee).

### RF-08 — Say what happened, with stable exit codes

- **Given** a run that finishes
  **When** it reports
  **Then** it prints, in English or in Portuguese by `--lang` as the other commands do, how many
  messages matched, how many were saved, how many were already there, how many were too large or
  skipped, and where they were saved. It prints no subject, sender, address or any other text from a
  message.
- **Given** the exit codes
  **When** `fetch` ends
  **Then** it uses the existing contract (006) with no new code: `0` when the run completed (even
  if it found nothing new), `1` when it was refused (connection, certificate, login, folder,
  disk), `2` for usage errors. A run that saved some messages and then failed exits `1` and says how
  many it had saved, since those files are valid.
- **Given** the help of `fetch`
  **When** the user asks for it
  **Then** it states that the command connects to a server, that it only reads, and what it will
  and will not do with the password.
- **Given** the new messages and refusal reasons
  **When** they are listed
  **Then** each has an English and a Portuguese sentence in the message catalog (ASCII only), and
  the `--json` question is settled in the open questions below.

### RF-09 — The offline commands stay offline

- **Given** the commands `summary` and `verdict`
  **When** their option lists are read
  **Then** they have no host, user, password, port or fetch option, and nothing in their import
  chain imports `imaplib`, `ssl` or `socket`.
- **Given** the test suite
  **When** it runs
  **Then** a test imports `summary`, `verdict` and the ingestion in a fresh interpreter and asserts
  that `imaplib` is not in `sys.modules`.
- **Given** `mailvigil --help`
  **When** it lists the commands
  **Then** `fetch` is described as the one command that uses the network.

### RF-10 — Hostile server input is tested, not assumed

- **Given** the test suite for this spec
  **When** it runs
  **Then** it contains, at least, each expecting a refusal or a counted skip and never an
  exception out of `fetch`: a certificate that fails verification; a login rejected; a message
  announced small that arrives large; a message announced over the cap; an endless response line;
  a literal that never ends; a silent server (timeout); a UID that is zero, negative, huge or not a
  number; a validity number that changes between runs; a folder name with a quote, a space and
  non-ASCII letters; a server error line with control characters and a bidirectional override; a
  disk that fails on write; and a run interrupted between the temporary file and the rename.

## Non-functional requirements

### RNF-01 — Standard library only

- **Given** the project at any commit
  **When** `[project].dependencies` is read
  **Then** it is still empty. The connection uses `imaplib` and `ssl`, the prompt uses `getpass`.
  If `imaplib` cannot meet a bound of RF-05, that is an ADR in the design, not a dependency.

### RNF-02 — The secret never leaves the process

- **Given** any input, any failure and any `--lang`
  **When** the program prints, raises or logs
  **Then** the password is in no output, no exception text, no file and no temporary file, and the
  tests assert that against a canary password.

### RNF-03 — Confined side effects, injectable connection

- **Given** the network code
  **When** it is written
  **Then** it sits in one module that receives the connection (and the clock, and the directory) as
  arguments, so that tests run it against a fake with no socket; it does not read `sys.argv`, call
  `sys.exit` or read the environment, and `mypy` strict passes. The command layer is the only place
  that prompts and prints.

### RNF-04 — Deterministic and idempotent

- **Given** the same mailbox state and the same arguments
  **When** `fetch` runs twice
  **Then** the second run saves nothing, the files are byte-identical, and within a run the messages
  are processed in a fixed order (closed in the design).

### RNF-05 — Fits the Python floor and the platforms

- **Given** Python `3.12` and the CI matrix (3.12 and the newest stable), on Windows and Linux
  **When** the module is written
  **Then** it uses nothing newer, the file names are valid on both platforms, and the rename is
  atomic on both (`os.replace`).

### RNF-06 — No network in the tests, synthetic data only

- **Given** the tests
  **When** they need a mailbox
  **Then** they use a fake connection built in the test, with invented hosts (`.invalid`), documentation
  IP ranges and invented domains. The CI makes no connection, and no real message, host or
  credential ever enters the repository.

### RNF-07 — Saved mail is private data

- **Given** the repository
  **When** the folder of saved messages is inside it
  **Then** `.gitignore` ignores `*.eml` and `*.mbox` outside `tests/`, as it does for `*.xml.gz`, so
  a fetch cannot be committed by accident.

## Open questions

Answered on 2026-10-28: the maintainer approved the recommendations of all six. Each had a
recommendation; none was a guess to be left as is.

1. **How the password reaches a scheduled job (RF-02).** Recommended: the interactive prompt plus
   `--password-file`, and no environment variable. A file with restricted permissions is as safe as
   a variable and does not leak to child processes or crash dumps; the cost is one more file to
   protect. The alternative is `MAILVIGIL_PASSWORD`, simpler for containers and CI, which would end
   the "no environment variables" line of `CLAUDE.md`.
2. **Connection settings in the config file.** Recommended: flags only in this version. A `[fetch]`
   table (host, user, folder, never the password) would let one `mailvigil.toml` serve the whole
   workflow, but it changes the config contract of 003 and the schema of its errors for a
   convenience a shell alias also gives.
3. **The subject criterion (RF-04).** Recommended: server-side `SUBJECT "Report Domain:"`, then
   check against the subjects of Google, Microsoft, Yahoo and others in the design. The risk is a
   provider that writes the subject differently and is silently missed; the alternative is to fetch
   every message in the date range and let the ingestion pick, which downloads the user's whole
   mail and is rejected here.
4. **A `--json` outcome for `fetch` (RF-08).** Recommended: no. The outcome is five numbers for a
   person, the exit code is the signal for a script, and every field added to `--json` is a public
   contract (006). Revisit if someone needs it. *Reopened on 2026-10-30 (issue #75) and answered
   yes: the design adds it in ADR-11.*
5. **Order and default of `--limit` (RF-05).** Recommended: newest first, default 500. The newest
   reports matter most for the verdict, and 500 messages of at most a few hundred KB is bounded
   disk and time; the values are closed in the design.
6. **Gmail and Microsoft 365.** Recommended: accept the non-goal and document it. Gmail works with
   an app password (account with two-step verification); Microsoft 365 does not work without OAuth.
   The alternative is a spec for XOAUTH2, which needs a browser flow and a call to a token endpoint
   and is a much larger decision than this one.

## Resolved decisions

1. **A separate command, never an option of `summary` or `verdict`.** The network, the secret and the
   write stay in one place the user chooses to run.
2. **Read-only, always.** There is no mode that changes the mailbox.
3. **Saves bytes, does not read them.** The reading is 007; this spec adds no parser.
4. **TLS or nothing.** No plain-text path, no way to disable verification.

## Tests

Following [specs/README.md](../README.md#how-a-spec-is-tested):

- **Unit tests, no CLI:** the fetch module is called with a fake connection and `tmp_path`: the
  commands it sends, the files it writes, the counts it returns.
- **Hostile input:** the cases of RF-10, each expecting a refusal or a counted skip.
- **The secret:** a canary password is searched for in every output, exception and file.
- **CLI:** `main(argv)` with `capsys` for `fetch`, with the exit codes asserted and a fake injected
  at the one place the command layer builds the connection.
- **Isolation:** the fresh-interpreter test of RF-09.
- **Synthetic only:** every host, message and credential is invented (RNF-06).
- **Quality gate last:** `ruff` → `black --check` → `mypy` → `pytest --cov`, with its real result
  recorded in `tasks.md`.
