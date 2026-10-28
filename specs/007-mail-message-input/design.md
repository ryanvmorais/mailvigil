---
feature: Mail message input — read report attachments straight from `.eml` and `.mbox` files
status: approved
date: 2026-10-28
related:
  - 007-mail-message-input/requirements.md
  - 002-report-ingestion/design.md
  - 006-output-and-exit-codes/design.md
origin: conception
---

# 007 — Mail message input — design

## Overview

Nothing downstream of `ingest` changes. The new code sits in front of the reader of 002 and turns a
message into the same bytes a loose attachment would give:

```text
paths ─discover─▶ Source(path, explicit) ─┬─ .xml .gz .zip ──read_xml──────────────┐
                                          ├─ .eml  ──read_message_file─┐           │
                                          └─ .mbox ──iter_mailbox──────┴─read_message─▶ Attachment(name, kind, data)
                                                                                      │ read_xml_bytes
                                                                                      ▼
                                              Document(xml, source) ─parse_report─▶ domain filter ─▶ dedup ─▶ IngestionResult
```

- **`reports/mail.py`** (new) is the only module that knows what a message is. It reads one message
  from bytes (`read_message`), reads an `.eml` from disk with its size cap (`read_message_file`),
  and splits a mailbox into messages as a stream (`iter_mailbox`). It returns attachments as bytes
  and never touches the XML or the report (ADR-1, ADR-3, ADR-4).
- **`reports/reader.py`** gains `read_xml_bytes(data, kind)`: the same size cap, zip and gzip code
  as `read_xml`, over bytes already in memory. `read_xml(path)` keeps its behavior and shares the
  code (ADR-6).
- **`reports/discovery.py`** also lists `.eml` and `.mbox` files in a folder, and says for each
  file whether the user named it or the folder search found it (ADR-5).
- **`reports/ingest.py`** turns each source into a stream of documents. The loop that parses,
  filters by domain and drops duplicates is the one that exists today; it does not know where the
  XML came from (ADR-6).
- **Output:** four new refusal reasons with their two sentences, a `part` on a skipped file so a
  mailbox can tell its messages apart, and one more key in the `--json` document (ADR-7, ADR-8).

## Module layout

```text
src/mailvigil/reports/
  mail.py        # NEW      Attachment, read_message, read_message_file, iter_mailbox, the four limits
  reader.py      # CHANGED  read_xml_bytes; _read_zip takes a path or a stream
  discovery.py   # CHANGED  Source; .eml and .mbox in folders
  ingest.py      # CHANGED  Document, _documents; the loop is unchanged
  errors.py      # CHANGED  four Reason values
  model.py       # CHANGED  SkippedFile.part
  __init__.py    # CHANGED  re-exports the new public names
src/mailvigil/messages/en.py, pt_br.py   # CHANGED  one sentence per new Reason
src/mailvigil/render.py                  # CHANGED  a skipped line shows the part
src/mailvigil/render_json.py             # CHANGED  skipped entries get `part`
src/mailvigil/cli.py                     # CHANGED  the help of PATH
docs/json-schema.md                      # CHANGED  `part`, the new reasons
tests/test_reports_mail.py               # NEW      the message reader and the splitter
```

`summary.py`, `verdict.py`, `senders.py`, `config.py` and `text.py` do not change. `mail.py`
imports `errors`, `reader` (for `MAX_BYTES` and `Kind`) and `text` (to clean a name); it imports
neither the parser nor `ingest`.

## Data model

```python
Kind = Literal["xml", "gz", "zip"]            # reader.py: what an attachment is stored as

@dataclass(frozen=True, slots=True)
class Attachment:                              # mail.py: a part that may be a report
    name: str      # file name, decoded and cleaned (clean_text, 255 chars); "" when it has none
    kind: Kind     # from the name's suffix, else from the content type (ADR-9)
    data: bytes    # the transfer encoding already undone

@dataclass(frozen=True, slots=True)
class Source:                                  # discovery.py
    path: Path
    explicit: bool  # True: the user named this file; False: a folder search found it

@dataclass(frozen=True, slots=True)
class Document:                                # ingest.py, private: what the loop parses
    xml: bytes
    source: str     # the display origin, becomes Report.source_file
    part: str       # "#3 report.zip" for a message, "" for a loose file; goes on a refusal

# model.py: SkippedFile(path, reason, detail) gains a last field, so every old call still works:
#     part: str = ""   # "#3 report.zip": the message and the attachment, "" for a loose file
```

The four limits are constants in `mail.py`, next to the constants of `reader.py` (changing one is a
spec decision, not a silent edit):

| Constant | Value | Why |
|---|---|---|
| `MAX_MESSAGE_BYTES` | 8 MiB | The 5 MiB attachment cap, plus a third for base64, plus headers and a body |
| `MAX_LINES` | 150,000 | An 8 MiB message of base64 has about 110,000 lines; more is not a mail |
| `MAX_PARTS` | 50 | A report mail has 2 or 3 parts; a newsletter with images, 20 |
| `MAX_DEPTH` | 10 | Mixed, related, alternative and a signature wrapper make 4 |

Four values are added to `Reason` (their keys are the contract of `--json`, so they are final):

| Key | When |
|---|---|
| `message_too_large` | A message over `MAX_MESSAGE_BYTES` (an `.eml` on disk, or one message of a mailbox) |
| `message_too_complex` | Over `MAX_LINES`, `MAX_PARTS` or `MAX_DEPTH` |
| `no_report_attachment` | An `.eml` the user named that holds no candidate attachment |
| `malformed_message` | The `email` package failed on the message in a way the checks above do not name |

An attachment that decodes to garbage (truncated base64, an unknown transfer encoding) is not a
new reason: the reader refuses it with the reason it already has (`not_an_archive`,
`malformed_xml`), because the `email` package is lenient and hands the bytes over (checked on
2026-10-28). The cap on a candidate is the one of 002: `file_too_large` when the decoded bytes
exceed `MAX_BYTES`, `decompressed_too_large` when an archive inflates past it.

## Components

### mail.py (RF-01 to RF-05, RNF-01, RNF-02)

- **`read_message_file(path: Path) -> bytes`** — the bytes of an `.eml`. `stat` first: not a
  regular file is `unreadable`, `st_size > MAX_MESSAGE_BYTES` is `message_too_large`, both before
  the file is opened; then one `read(MAX_MESSAGE_BYTES + 1)` and the same check again, because a
  file can grow between the `stat` and the read.
- **`read_message(raw: bytes) -> tuple[Attachment, ...]`** — the candidates of one message, in the
  order they appear.
  1. `max(raw.count(b"\n"), raw.count(b"\r")) > MAX_LINES` → `message_too_complex`, before any
     parsing (ADR-2). The count is done by the interpreter in C and costs milliseconds.
  2. Parse with `BytesFeedParser`, fed in 64 KiB chunks, with `policy.default` cloned with a
     message factory that counts the parts it creates and raises past `MAX_PARTS` (ADR-1). The
     raise is caught and becomes `message_too_complex`.
  3. Walk the tree with a stack of `(part, depth)`, not `Message.walk()` (ADR-4): a part deeper
     than `MAX_DEPTH` is `message_too_complex`; a `message/*` part is not entered; a multipart
     pushes its children (in reverse, so they come out in order); anything else is a leaf.
  4. A leaf is an attachment when `get_filename()` is not `None` or `get_content_disposition()` is
     `"attachment"`. Its name is `clean_text(filename or "", MAX_TEXT)`. Its kind is the one of the
     name's suffix (`.xml`, `.gz`, `.zip`, any case) and, if that gives none, the one of its
     content type: `application/zip` and `application/x-zip-compressed` are `zip`,
     `application/gzip` and `application/x-gzip` are `gz`, `text/xml` and `application/xml` are
     `xml` (ADR-9). No kind means the part is ignored.
  5. `get_payload(decode=True)` gives the bytes; `None` (a part with no payload) is ignored.
  6. `(email.errors.MessageError, ValueError, LookupError, UnicodeError)` out of steps 2 to 5 is
     `malformed_message`. `RecursionError` cannot happen: the parts are at most `MAX_PARTS`, so the
     tree is at most that deep, far under the interpreter's limit.
- **`iter_mailbox(stream: BinaryIO) -> Iterator[tuple[int, bytes | ReportRefused]]`** — splits a
  mailbox. It reads with `readline(65537)`, so a line of any length costs a bounded read, and
  keeps a `bytearray` for the message in progress (ADR-3).
  - A line that starts a line and matches `_FROM_LINE` starts the next message and ends the
    current one; the separator line itself is not part of either.
  - Bytes before the first separator are dropped. A message that grows past `MAX_MESSAGE_BYTES`
    stops being stored (the buffer is cleared) but keeps being read until the next separator; it
    is then yielded as `ReportRefused(MESSAGE_TOO_LARGE)`.
  - Yields `(number, message)` with `number` counting from 1. The whole file is never in memory:
    at most one message plus one line.

### reader.py (RF-04)

- **`read_xml_bytes(data: bytes, kind: Kind) -> bytes`** — `len(data) > MAX_BYTES` is
  `file_too_large`; then `xml` returns the bytes through `_read_capped(io.BytesIO(data))`, `gz`
  opens `gzip.GzipFile(fileobj=io.BytesIO(data))`, `zip` calls `_read_zip(io.BytesIO(data))`. The
  `except _ARCHIVE_ERRORS` clause of `read_xml` moves into a small helper both functions use, so the
  mapping of the standard library's errors to `not_an_archive` exists once.
- **`_read_zip`** takes `Path | BinaryIO`; `zipfile.ZipFile` accepts both, so the body does not
  change. Nothing is extracted to disk, as before.
- `read_xml(path)` is unchanged for its callers and its tests.

### discovery.py (RF-06)

- **`discover(paths) -> tuple[tuple[Source, ...], tuple[SkippedFile, ...]]`**. A path that is a
  file becomes `Source(path, explicit=True)`; a path found in a folder becomes
  `Source(path, explicit=False)`.
- `_list_folder` keeps the rule of 002 for attachments (the provider pattern) and adds: a regular
  file whose suffix, lower-cased, is `.eml` or `.mbox`, whatever its name. Name order and the
  `realpath` deduplication stay; when a file is both named and found, the first spelling wins and
  so does its `explicit` flag (the order of `paths`).

### ingest.py (RF-01, RF-02, RF-07, RF-09)

`ingest` keeps its signature and its loop. The change is what the loop iterates:

```python
for source in sources:
    for item in _documents(source):                # Document | SkippedFile
        if isinstance(item, SkippedFile):
            skipped.append(item)
            continue
        try:
            report = parse_report(item.xml, source=item.source)
        except ReportRefused as refused:
            skipped.append(SkippedFile(source.path, refused.reason, refused.detail, item.part))
            continue
        ...  # the domain filter and the dedup, as today
```

`_documents(source)` is a generator (it holds one message at a time):

- a `.xml`, `.gz` or `.zip` (or any other suffix, which the reader refuses) → `read_xml(path)`, one
  `Document(xml, path.name, "")`, or one `SkippedFile` — exactly today's behavior;
- an `.eml` → `read_message_file`, then `read_message`, then one `Document` per attachment (RF-03).
  No attachment and `source.explicit` → `SkippedFile(NO_REPORT_ATTACHMENT)`; not explicit → nothing;
- an `.mbox` → `iter_mailbox` over the opened file; each message goes as an `.eml` does, except that
  a message with no attachment is always silent (RF-02).

The `part` of a refusal is built in one place: `"#{n}"` for message `n` of a mailbox, then the
attachment's name, joined by a space, either of them absent when it does not apply. A `Document` from
a message has `source = f"{path.name}: {part}"`. A refusal for the whole of an `.eml` (too large, too
complex) has an empty part, as the message is the file. The parser's refusals (`malformed_xml`,
`forbidden_declaration`…) and the reader's carry the part of the attachment they came from, because
the loop has it.

### Output (RF-07, RF-08)

- **`render.py`**: a skipped line is `name: phrase` today, with the name cut to fit. It becomes
  `name part: phrase`, with the same cut (the phrase must survive, spec 004).
- **`render_json.py`**: `_skipped` returns `{"name": ..., "part": ..., "reason": ...}`, with `part`
  `null` when empty (the rule "a value the model may not have is `null`").
- **`messages/`**: four sentences per language in `reasons` (the dictionary the renderers read, which
  a test already requires to cover every `Reason`).
- **`cli.py`**: `PATH` help becomes `report files (.xml .gz .zip), mail files (.eml .mbox) or
  folders of them`.

## Interfaces

No new command, flag or exit code. The public names added to `mailvigil.reports`: `Source`,
`Attachment`, `read_message`, `read_message_file`, `iter_mailbox`, `read_xml_bytes`,
`MAX_MESSAGE_BYTES`, `MAX_LINES`, `MAX_PARTS`, `MAX_DEPTH`. `discover` changes its return type (its
only caller is `ingest`, and the tests that call it are updated).

`--json`: one key added to the entries of `skipped` (`part`, string or `null`), inside the same
`schema_version` as the promise says; four reason values added to the list of examples.

## ADRs

### ADR-1 — Parse with `email`, fed in chunks, counting parts as they are created

- **Decision:** `BytesFeedParser` with `policy.default` and a message factory that raises past
  `MAX_PARTS`, fed 64 KiB at a time.
- **Alternatives:** (a) `message_from_bytes` and check the tree afterwards; (b) a MIME parser of
  our own; (c) a third-party library (rejected by RNF-01 before it is considered).
- **Why:** measured on 2026-10-28: a 16 MiB message of empty parts parsed whole peaked at 283 MiB and
  2.4 s before the check could run, because the parser splits every line into an object. With the
  factory and 64 KiB chunks the same message was refused in 0.01 s at 1.1 MiB. The factory is the
  one hook the standard library offers that runs *during* parsing. A parser of our own would be
  hundreds of lines of the most attacked format there is.
- **Trade-off:** it leans on `FeedParser` calling `policy.message_factory(policy=...)` for each part,
  which is documented but is an implementation seam. The CI runs 3.12 and the newest release, and a
  test that sends a parts bomb fails loudly if the seam moves.

### ADR-2 — A line cap, and 8 MiB instead of 16

- **Decision:** refuse before parsing a message with more than `MAX_LINES` lines; set
  `MAX_MESSAGE_BYTES` to 8 MiB.
- **Alternatives:** only a byte cap; a time limit around the parse.
- **Why:** measured with chunked feeding and the part cap in place: 16 MiB of blank lines took 19 s
  and 3.3 million headers took 40 s and 388 MiB, with two parts. A byte cap does not see this: the
  cost is per line. `bytes.count` costs milliseconds and the legitimate maximum (an 8 MiB base64
  message) is about 110,000 lines, so 150,000 refuses nothing real. The byte cap drops from 16 to
  8 MiB because a report attachment is capped at 5 MiB (6.7 MiB as base64), so the second 8 MiB
  could only be refused later by the attachment cap.
- **Trade-off:** a legitimate mail with more than 150,000 lines is refused. It cannot be a report
  message, so nothing is lost. A time limit would make the result depend on the machine (RNF-04).

### ADR-3 — Our own mailbox splitter, not `mailbox.mbox`

- **Decision:** `iter_mailbox` reads the stream with `readline(65537)` and splits on the separator
  line `From <sender> <weekday> <month> <day> <hh:mm:ss>`, matched by a regex at a line start.
- **Alternatives:** `mailbox.mbox` from the standard library; `str.split` over the whole file.
- **Why:** `mailbox.mbox` finds the messages by scanning the file, but `get_bytes`/`get_message`
  read a whole message before we can look at its size, and the offsets that would let us check
  first are private (`_toc`). A message the size of the file (RF-05, the missing separators case)
  would be loaded entirely. `str.split` loads the file.
- **Why this separator:** it is what Thunderbird (`From - Tue Oct 28 10:00:00 2025`), Apple Mail and
  Gmail Takeout write, and it ignores a body line such as `From me to you`. The quoting of `From `
  lines in bodies (`>From `, mboxo and mboxrd) is not undone: only bodies are quoted, and the body is
  never read (RF-03). `mboxcl` (a `Content-Length` header, bodies not quoted) is not supported.
- **Trade-off:** the cost is linear in the number of lines. Measured: 0.8 s per 100 MiB of ordinary
  mail, but 40 s per 100 MiB of nothing but line breaks, because each is a call. That needs a file
  built for it, and the same file is read by every mail client. If it ever matters, a block scan
  for the next separator in the discarding state is a local change.

### ADR-4 — Walk the tree by hand and do not enter `message/*`

- **Decision:** an iterative walk with a stack and a depth, skipping parts of type `message/*`.
- **Alternatives:** `Message.walk()`; `EmailMessage.iter_attachments()`.
- **Why:** `walk()` enters an attached message, which the requirements exclude (Non-goals), and
  hides the depth. `iter_attachments()` skips the text body but is built for display, not for
  "any leaf with a name or a disposition", which is the rule of RF-03.
- **Trade-off:** twenty lines of our own traversal, tested against a forwarded message and a nested
  one.

### ADR-5 — Discovery says whether the user named the file

- **Decision:** `discover` returns `Source(path, explicit)`.
- **Alternatives:** `ingest` guesses by comparing `path` with the arguments; a second argument
  `explicit_only` to `discover`.
- **Why:** the only place that knows is discovery. The flag is the whole difference between "an
  `.eml` I pointed at, with nothing in it" (say so) and "an `.eml` in my folder" (a folder holds all
  sorts of mail, say nothing), the rule 002 already applies to other files.
- **Trade-off:** the return type of a public function changes. It has one caller.

### ADR-6 — One loop, fed by a generator of documents

- **Decision:** `_documents` yields `Document | SkippedFile`; the loop of `ingest` is the same.
- **Alternatives:** make `ingest` first expand everything into a list, then loop; duplicate the
  loop for messages.
- **Why:** a mailbox expanded into a list holds every attachment of the file at once (up to
  thousands of 5 MiB), against the "one message at a time" of RF-05. Duplicating the loop would
  copy the domain filter and the dedup (RF-08 of 002) and let them drift.
- **Trade-off:** the order of reports is still discovery order, then message order, then attachment
  order, which is RNF-04, because a generator yields in order.

### ADR-7 — `SkippedFile.part` and one `--json` key, instead of encoding it in the name

- **Decision:** a `part: str = ""` field on `SkippedFile`; `skipped[].part` in the JSON, `null` when
  empty.
- **Alternatives:** put `#3 report.zip` in `path`; put it in `detail`.
- **Why:** `path` is a `Path` and a name from a message is third-party text; `detail` is English for
  logs and is not shown. Two messages of one mailbox would otherwise be two lines with the same
  name. The promise of `docs/json-schema.md` allows adding a key inside a `schema_version`.
- **Trade-off:** every `skipped` entry grows by a key, null for loose files; consumers must ignore
  keys they do not know, which the promise already requires.

### ADR-8 — Four new reasons, none borrowed

- **Decision:** `message_too_large`, `message_too_complex`, `no_report_attachment`,
  `malformed_message` (above).
- **Alternatives:** reuse `file_too_large` and `not_a_report`.
- **Why:** the text a person reads is by reason, and "too large once decompressed" or "not a
  DMARC report" would be wrong for a 9 MiB mail or for a plain `.eml`. A message in a mailbox is not
  a file, so `file_too_large` would misdescribe it.
- **Trade-off:** four keys to keep in the two languages and in the schema, forever.

### ADR-9 — The name decides the kind; the content type is the fallback

- **Decision:** the suffix of the attachment's name decides `xml`, `gz` or `zip`; the content type
  only when the name gives none (resolved question 1).
- **Alternatives:** trust the content type first; the name only.
- **Why:** providers name the files consistently and a name is what the reader of 002 already
  trusts for a loose file; the type is the fallback for the attachment with no name. A name that
  says `.gz` and a type that says `application/octet-stream` (common) must work.
- **Trade-off:** a part named `report.zip` that is not a zip reaches the reader and is refused as
  `not_an_archive`, which is the right answer.

## Impact on existing code

- **Changed signatures:** `discover` (its return type), `SkippedFile` (a last field with a default),
  `Reason` (four values), `_read_zip` (private). The tests of `discover` and of `Reason` coverage
  are updated; the others do not change.
- **Docs:** `README.md` (the input row says `.eml` and `.mbox`), `CLAUDE.md` (the architecture
  tree gets `mail.py`), `docs/stack.md` (`email`, `email.policy` and the factory seam, `io.BytesIO`),
  `docs/json-schema.md` (`part`, reasons), `specs/README.md` (status).
- **Dependencies:** none. `email` and `io` are standard library.

## Risks

- **A whole-mailbox export lists its large mails as skipped.** A mail over 8 MiB cannot be a report,
  but it is refused with a reason, so an export of a whole account shows many `message too large`
  lines (the text shows the first few and "and N more"; the count is by reason). That is what the
  requirement asks (RF-05) and it is honest about what was left out, but it is noisy. If it bothers
  in practice, a mailbox could hide that one reason; deliberately not done now.
- **The `email` package changes between releases.** ADR-1 leans on a seam; the matrix (3.12 and the
  newest) and the bomb test are the alarm.
- **A separator the exporter does not write.** A mailbox whose lines do not match `_FROM_LINE` is
  read as one message, over the cap, and refused as `message_too_large` (RF-05). Nothing is read
  wrongly; the user learns that the format is not the supported one from the reason.
- **Filenames in encoded words.** A name that does not decode is kept as the parser gives it; if the
  suffix does not show, the content type decides, and if that fails the part is ignored.

## Test strategy

Following [specs/README.md](../README.md#how-a-spec-is-tested). Messages are built in the test with
`email.message.EmailMessage` and as raw bytes; mailboxes are bytes joined with separator lines;
`tmp_path` for files. No real message.

- **`read_message` (RF-01, RF-03, RF-04):** one report attached as zip, gz and xml; upper-case suffix;
  encoded-word and RFC 2231 names; no name with each content type; a name with an unknown suffix and
  a known type; two candidates in one message; a text body and an image ignored; a forwarded
  `message/rfc822` not entered; a `multipart/signed` wrapper read; base64 and quoted-printable.
- **Hostile input (RF-05, RF-09):** a message over `MAX_MESSAGE_BYTES` (as a file and in a
  mailbox); more than `MAX_LINES` lines of blank lines and of headers, each asserted to return
  without parsing (the limit is checked by a spy on the feed parser, not by a stopwatch, so the
  test does not depend on the machine); a parts bomb; nesting past `MAX_DEPTH` and past
  `MAX_PARTS` (no `RecursionError`); base64 decoding past `MAX_BYTES`; a zip bomb and a `DOCTYPE`
  inside a message; truncated base64 and an unknown transfer encoding (refused with the reader's
  reasons); a name with control characters and a bidirectional override (cleaned); a parser failure
  forced with a monkeypatched factory (`malformed_message`).
- **`iter_mailbox` (RF-02, RF-05):** several messages in order; text before the first separator;
  `From me to you` inside a body; a line longer than the read size; a message of the size of the
  whole file with no separators; one oversized message among good ones; an empty file; the three
  separator shapes of ADR-3.
- **`discover` (RF-06):** `.eml` and `.mbox` found in a folder in name order with the attachments,
  any name, any case; `explicit` true for a named file, false for a listed one; a subfolder not
  entered; a file with another suffix unchanged.
- **`ingest` (RF-01, RF-02, RF-07, RF-08):** the same report as a loose zip and in an `.eml` kept
  once with one duplicate; reports from a mailbox in file order; an explicit `.eml` with nothing
  skipped as `no_report_attachment` and the same file found in a folder silent; a bad attachment next
  to a good one; the `part` and the `source_file` of each case.
- **Output (RF-07, RF-08):** the English and Portuguese sentence of each new reason (the coverage
  test); a skipped line with a part fits 80 columns; the JSON has `part`, `null` for a loose file;
  the example in `docs/json-schema.md` still equals the real output.
- **CLI (RF-08):** `main(argv)` with an `.eml` and with an `.mbox` through `summary` and `verdict`,
  text and `--json`, exit codes asserted; `--help` mentions the new kinds.
- **Quality gate last:** `ruff` → `black --check` → `mypy` → `pytest --cov`, with its real result
  recorded in `tasks.md`.
