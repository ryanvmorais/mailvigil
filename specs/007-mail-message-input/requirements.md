---
feature: Mail message input — read report attachments straight from `.eml` and `.mbox` files
status: done
date: 2026-10-28
related:
  - 002-report-ingestion/requirements.md
  - 006-output-and-exit-codes/requirements.md
origin: conception
---

# 007 — Mail message input

## Context and problem

A DMARC aggregate report arrives as an e-mail whose attachment is the `.zip`, `.gz` or `.xml`
that [002](../002-report-ingestion/) knows how to read. Today the person has to open every message,
save the attachment into a folder, and only then run `mailvigil`. For a domain that gets a report a
day from a dozen providers, that is hundreds of manual saves before a verdict on `p=reject` has
enough days behind it.

Mail clients can already export what they hold: "Save as" gives one `.eml` per message, and most
clients and providers (Thunderbird, Apple Mail, Gmail Takeout) export a whole folder or label as
one `.mbox`. If MailVigil reads those files, the manual step shrinks to one export, with no network,
no credential and no change to the product promise (offline, standard library only).

This spec also prepares [009](../README.md#roadmap): an IMAP fetch only has to save the raw messages
into a folder, and this layer does the reading. Reading mail and talking to a mail server stay in
separate specs.

The new input is hostile in a way the old one was not. A message is a nested container the sender
controls: parts inside parts, attachments encoded in base64, names in encoded words, and mailbox
files that can be gigabytes of unrelated mail. The same rule as in 002 holds: every defense has a
test that feeds it the attack.

## Goals

- **Accept `.eml` and `.mbox` files** wherever a path is accepted today (files given directly and
  folders), with no new flag.
- **Take the report attachment out of the message in memory,** and hand its bytes to the same
  size cap, XML defenses, parser, domain filter and deduplication as a loose attachment.
- **Bound the work a message can cause:** its size, the number of parts, the depth of nesting and
  the size of each decoded attachment, so a hostile message is refused, not obeyed.
- **Say where a report came from** (file, message, attachment) without printing text a third party
  controls unsanitized.

## Non-goals

- Fetching messages from a server (IMAP, POP3, any network access): spec `009`.
- Following a message attached to a message (`message/rfc822`), for instance a report forwarded
  "as attachment". The attachment of the outer message is read; the inner one is not entered.
- Decrypting S/MIME or PGP, verifying signatures, or reading Outlook `.msg` and other proprietary
  formats. A signed message (`multipart/signed`) is only a wrapper and is read normally.
- Reading the message body: the XML is never taken from the text of a message, only from an
  attachment.
- Judging the message: its headers, its `Authentication-Results`, its sender. The report inside is
  what counts, as in 002.
- Writing anything to disk, including extracting attachments (as in 002).
- Formats other than RUA (forensic reports, SMTP TLS reports), as in 002.

## Personas

- As the **maintainer** (and any domain owner), I want to export a mail folder from my client and
  point the tool at the file, so that I do not save hundreds of attachments by hand.
- As a **user who exports a whole mailbox,** I want the tool to find the reports among the
  thousands of unrelated messages and say nothing about the rest, so that the output is about my
  reports and not about my mail.
- As a **user who opens a strange `.eml`,** I want it refused with a clear reason, without the tool
  hanging, exhausting memory or crashing.
- As a **contributor to spec `009`,** I want one function that turns a raw message into the same
  records as a loose file, so that the fetch only has to save bytes.

## Functional requirements

### RF-01 — Read one message

- **Given** an `.eml` file with one `.zip`, `.gz` or `.xml` attachment holding a valid report
  **When** it is ingested
  **Then** the result is the same report, with the same records, as the loose attachment gives.
- **Given** the suffix in upper case (`REPORT.EML`)
  **When** it is ingested
  **Then** it is treated like its lower-case form.
- **Given** the message is plain text with no attachment, or its attachments are not report
  candidates (RF-03)
  **When** it was given directly as a path
  **Then** it is skipped with a reason saying the message holds no report attachment.
- **Given** a message whose headers or structure are damaged (missing boundary, truncated base64,
  invalid encoding names)
  **When** it is ingested
  **Then** whatever can be read is read, the damaged attachment is skipped with a reason that names
  the cause, and the program does not crash.

### RF-02 — Read a mailbox

- **Given** an `.mbox` file with many messages
  **When** it is ingested
  **Then** each message is read as in RF-01, in the order they appear in the file, and the result
  merges all of them.
- **Given** a mailbox where most messages are not reports
  **When** it is ingested
  **Then** the messages without a report-candidate attachment are ignored silently, and they do not
  appear in the skipped list (a mailbox export is the user's whole mail, not a list of reports).
- **Given** a mailbox where one message is corrupt or hostile
  **When** it is ingested
  **Then** that message is skipped with a reason and the others are still read (RF-09 of 002 holds
  per message).
- **Given** the same report in two messages of one mailbox, or in a message and in a loose file
  **When** it is ingested
  **Then** it is kept once and counted as a duplicate (RF-08 of 002; nothing new here).
- **Given** an `.mbox` that uses the usual "From " separator line, with or without quoting of the
  lines that start with "From " inside a message
  **When** it is ingested
  **Then** the messages are split correctly. The exact variants supported are closed in the design.

### RF-03 — Which attachments are report candidates

- **Given** a part of a message that is an attachment (disposition `attachment`, or any part with a
  file name) whose name ends in `.xml`, `.gz` or `.zip`, in any letter case
  **When** the message is read
  **Then** it is a candidate and is read like a loose file of that kind.
- **Given** an attachment with no file name, or one that does not end in those suffixes, but whose
  content type is one providers use for reports (`application/zip`, `application/gzip`,
  `application/x-gzip`, `application/x-zip-compressed`, `text/xml`, `application/xml`)
  **When** the message is read
  **Then** it is a candidate, and the kind is taken from the content type.
- **Given** any other part (the text body, an image, a signature file, a calendar invitation)
  **When** the message is read
  **Then** it is ignored without a word.
- **Given** a message with more than one candidate
  **When** it is read
  **Then** every candidate is read as its own source, and one refusal does not stop the others.
- **Given** a file name written as an encoded word (RFC 2047) or as an extended parameter
  (RFC 2231)
  **When** the message is read
  **Then** the name is decoded before the suffix is checked.

### RF-04 — The same defenses as a loose attachment

- **Given** a candidate attachment that decodes (base64 or quoted-printable) to more than
  `MAX_BYTES` of content, or that is a `.gz` or a `.zip` inflating past it
  **When** the message is read
  **Then** it is refused with the same reason a loose file gets (`file_too_large` or
  `decompressed_too_large`); the cap acts on bytes actually produced, never on a declared size.
- **Given** a candidate holding XML with a `DOCTYPE` or `ENTITY` declaration, a zip with no or with
  several `.xml` members, a corrupt archive or a document that is not a report
  **When** the message is read
  **Then** it is refused with the same reason as a loose file (RF-01 to RF-04 of 002 are not
  reimplemented, they are reused).
- **Given** a `.zip` or `.gz` attachment
  **When** it is read
  **Then** the archive is opened from memory and nothing is extracted to disk.

### RF-05 — Bounds on the message itself

- **Given** a message larger than `MAX_MESSAGE_BYTES` (value closed in the design)
  **When** it is read, alone or inside a mailbox
  **Then** it is refused with a reason saying the message is too large, before it is parsed, and
  no more than that limit plus one byte of it is ever held in memory.
- **Given** a message with more than `MAX_PARTS` parts, nested deeper than `MAX_DEPTH`, or with more
  than `MAX_LINES` lines (values closed in the design)
  **When** it is read
  **Then** it is refused with a reason saying its structure is too complex, in bounded time and
  memory, and the program does not raise `RecursionError`. (The lines are there because measuring
  showed that the `email` parser needs tens of seconds for a message of millions of tiny lines,
  even when it has few parts; see ADR-2 of the design.)
- **Given** a mailbox file of any size (a multi-gigabyte export)
  **When** it is ingested
  **Then** it is read message by message and the whole file is never held in memory; the cap of the
  previous scenarios applies to each message, not to the file.
- **Given** a mailbox whose "From " lines are missing or absurd (one message of the size of the
  whole file)
  **When** it is ingested
  **Then** the oversized "message" is refused as in the first scenario, and the program does not
  run out of memory.

### RF-06 — Discovery of message files

- **Given** a folder
  **When** paths are discovered
  **Then** the regular files directly inside it that end in `.eml` or `.mbox` are read too, in
  name order together with the attachments, whatever their names (mail clients name an `.eml` after
  the subject, so the provider pattern of 002 does not apply to them).
- **Given** a folder with `.eml` files that are not reports
  **When** it is ingested
  **Then** they are ignored silently, as in RF-02: a folder is searched, a file given directly is
  asked for (RF-06 of 002).
- **Given** a path that is a file with another suffix
  **When** paths are discovered
  **Then** nothing changes: a file given directly is still read by the reader of 002, and one with
  an unsupported suffix is refused as before.

### RF-07 — Say where a report came from

- **Given** a report taken from a message
  **When** the caller reads it
  **Then** its display origin names the file, and for a mailbox the position of the message, and the
  attachment name; the attachment name is third-party text and goes through the same sanitizing as
  every other text field (RF-05 of 002, 255 characters).
- **Given** an attachment of a message that was refused
  **When** the caller reads the skipped list
  **Then** the entry carries the path of the message file, the typed reason and the same display
  origin, so a later spec can show it in English or Portuguese.

### RF-08 — Reasons, text and contract

- **Given** the new refusals (message too large, structure too complex, no report attachment,
  damaged message)
  **When** they are listed
  **Then** each has a stable `Reason` key, an English sentence and a Portuguese sentence in the
  message catalog, and appears in `docs/json-schema.md`.
- **Given** a release that already has the `--json` contract
  **When** a reason key is added
  **Then** no existing key changes its name or meaning: adding a value is compatible, renaming one
  is a breaking change (spec 006).
- **Given** the commands `summary` and `verdict`
  **When** the user passes an `.eml` or `.mbox`
  **Then** they work with no new option, and `--help` says which kinds of file a path may be.

### RF-09 — Hostile input is tested, not assumed

- **Given** the test suite for this spec
  **When** it runs
  **Then** it contains, at least: a message over `MAX_MESSAGE_BYTES`; a base64 attachment that
  decodes past `MAX_BYTES`; a zip bomb and an XML with `DOCTYPE` inside a message; a message with
  more than `MAX_PARTS` parts; a message nested deeper than `MAX_DEPTH`; a message of millions of blank lines and one of
  millions of headers; a mailbox with one
  oversized message among good ones; truncated base64; an unknown transfer encoding; an attachment
  name with control characters and a bidirectional override; and each expects a refusal and a
  reason, never an exception out of `ingest`.

## Non-functional requirements

### RNF-01 — Standard library only

- **Given** the project at any commit
  **When** `[project].dependencies` is read
  **Then** it is still empty. Messages are read with `email`, `mailbox` or code over `io`; if the
  limits of RF-05 cannot be met with them, that is an ADR in the design, not a dependency.

### RNF-02 — Read-only and offline

- **Given** any input
  **When** it is ingested
  **Then** files are opened for reading only, nothing is extracted or written, no network
  connection is opened, and nothing from a message is executed or followed (no links, no
  `Content-Location`, no external references).

### RNF-03 — No side effects, typed and immutable

- **Given** the new functions
  **When** they run
  **Then** they do not print, read `sys.argv`, call `sys.exit` or read the environment; `mypy`
  strict passes; the result types stay frozen dataclasses with tuples (RNF-03 and RNF-04 of 002).

### RNF-04 — Deterministic

- **Given** the same files
  **When** they are ingested twice
  **Then** the reports, the skipped list and the counts are identical and in the same order: files
  in discovery order, messages in file order, attachments in message order.

### RNF-05 — Fits the Python floor and the platforms

- **Given** the Python floor `3.12` and the CI matrix (3.12 and the newest stable)
  **When** the layer is written
  **Then** it uses nothing newer and passes on both. The tests build `.eml` and `.mbox` content as
  bytes in the test and do not depend on the platform's line endings (the maintainer develops on
  Windows and the CI runs on Linux).

### RNF-06 — Synthetic fixtures only

- **Given** the tests
  **When** they need a message or a mailbox
  **Then** they build it in the test from invented domains and documentation IP ranges
  (`192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24`, `2001:db8::/32`), with the `.invalid` or
  `example` domains in headers. No real message ever enters the repository.

## Open questions

None left open. Questions 1 to 5 were answered on 2026-10-28 (the maintainer approved
the recommendations); question 4 was refined in the design.

1. **Content type as a fallback (RF-03).** Recommended: yes. Providers are not uniform, and an
   attachment named `report` with `application/gzip` is a real case. The cost is a rule more to
   test. The alternative is to accept only the suffix of the name, simpler and stricter.
2. **A message given directly with no report attachment (RF-01).** Recommended: skipped with a
   reason, because the user pointed at it on purpose (the rule of RF-06 in 002). In a mailbox or a
   folder it is silent (RF-02, RF-06).
3. **How many messages did a mailbox hold?** Recommended: do not count them. A count of "messages
   without a report" would add a field to `IngestionResult` and to the `--json` document for a
   number the user did not ask for. If a mailbox yields no report at all, the existing "nothing
   found" message already says it.
4. **Values of `MAX_MESSAGE_BYTES`, `MAX_PARTS`, `MAX_DEPTH` and `MAX_LINES`.** Recommended
   starting point was 16 MiB, 50 parts and depth 10. Closed in the design after measuring, with
   `MAX_MESSAGE_BYTES` lowered to 8 MiB (the 5 MiB attachment cap plus base64's one third) and
   `MAX_LINES` added at 150,000 (ADR-2). A report message is a few KB of headers plus one
   attachment of a few KB to a few hundred KB.
5. **`.mbox` variants.** Recommended: the common "mboxo/mboxrd" family with "From " separators
   (what Thunderbird, Apple Mail and Gmail Takeout write); other mailbox formats (Maildir, `.pst`)
   are not read. Maildir is a folder of `.eml`-like files and could come later if someone asks.

## Resolved decisions

1. **Reading, not fetching.** This spec never opens a connection; the fetch is spec `009`, which
   saves raw messages and reuses this layer.
2. **No new flag.** A path that is an `.eml` or `.mbox` is read as such; the CLI contract of 006 is
   unchanged except for more accepted file kinds and the new reasons.
3. **Attachments only, never the body,** and the inner message of `message/rfc822` is not entered.
4. **The checks of 002 are reused, not copied.** The size cap, `DOCTYPE`/`ENTITY` refusal, the
   parser, the filter and the dedup are the same code; this spec adds the container around them.

## Tests

Following [specs/README.md](../README.md#how-a-spec-is-tested):

- **Unit tests, no CLI:** the message reader and the extended discovery are called directly with
  built bytes and `tmp_path`.
- **Hostile input:** the cases of RF-09, each expecting a refusal with a reason.
- **CLI:** `main(argv)` with `capsys` for an `.eml` and an `.mbox` through `summary` and `verdict`,
  with the exit codes asserted, in text and in `--json`.
- **Synthetic only:** every message is built in the test from the ranges in RNF-06.
- **Quality gate last:** `ruff` → `black --check` → `mypy` → `pytest --cov`, with its real result
  recorded in `tasks.md`.
