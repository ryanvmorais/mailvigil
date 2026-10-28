---
feature: Mail message input — read report attachments straight from `.eml` and `.mbox` files
status: in progress
date: 2026-10-28
related:
  - 007-mail-message-input/requirements.md
  - 007-mail-message-input/design.md
origin: conception
---

# 007 — Mail message input — Tasks

Each stage is one pull request (issue → branch → PR); Claude opens it and never merges. Inside a
stage, tests come first: write the test that feeds the input, watch it fail for the right reason,
then write the code. Messages are built in the test with `email.message.EmailMessage` or as raw
bytes, mailboxes as bytes joined with separator lines, files in `tmp_path`. Domains and addresses
are invented (`example.com`, `example.org`; `192.0.2.0/24`, `198.51.100.0/24`, `2001:db8::/32`;
`.invalid` in headers). No real message, report, address or domain enters a test, a doc or a commit
message (RNF-06).

The stages go from the bottom up: first the vocabulary and the reader of bytes, which change nothing
a user sees; then the message reader, which nothing calls yet; then the wiring that makes
`.eml` and `.mbox` work through the CLI; then the close. The test files of 002 to 006 are only
edited where the design says a signature changed (`discover`, `Reason` coverage); if any other one
fails, the code is wrong.

## Stage 1 — Vocabulary and the reader of bytes (RF-04, RF-07, RF-08, RNF-01, ADR-6, ADR-7, ADR-8)

- [x] `tests/test_reports_reader.py`, written first: `read_xml_bytes` for each kind (`xml`, `gz`,
  `zip`) returns the same bytes `read_xml` gives for the same content on disk; `len(data) >
  MAX_BYTES` is `file_too_large` before any archive is opened; a `.gz` and a `.zip` member that
  inflate past `MAX_BYTES` are `decompressed_too_large`, with a zip whose declared sizes lie; a
  corrupt `.gz`, a corrupt `.zip`, a zip with no and with two `.xml` members map to the same reasons
  as the file versions; an empty `bytes` is refused, not a crash. The existing `read_xml` tests
  still pass untouched. — RF-04, ADR-6
- [x] `src/mailvigil/reports/reader.py`: the `Kind` literal; `read_xml_bytes(data, kind)`; the
  `except _ARCHIVE_ERRORS` mapping moved into one helper both functions use; `_read_zip` takes
  `Path | BinaryIO`. `read_xml(path)` keeps its behavior. Docstrings with `Args:` / `Returns:` /
  `Raises:`. — RF-04, RNF-02, ADR-6
- [x] `tests/test_reports_errors.py` and `tests/test_reports_model.py`, first: the four new `Reason`
  keys exist with the exact strings of the design; `SkippedFile` built the old way (three
  arguments) has `part == ""`, and with the fourth argument keeps it. — RF-07, RF-08, ADR-7, ADR-8
- [x] `src/mailvigil/reports/errors.py` and `model.py`: `MESSAGE_TOO_LARGE`, `MESSAGE_TOO_COMPLEX`,
  `NO_REPORT_ATTACHMENT`, `MALFORMED_MESSAGE` with their docstring lines; `SkippedFile.part`.
  — RF-08, ADR-7, ADR-8
- [x] `tests/test_messages.py`, `tests/test_render.py`, `tests/test_render_pt.py`,
  `tests/test_render_json.py`, `tests/test_json_schema_doc.py`, first: the coverage tests already
  require every `Reason` in both languages (they fail for the four new ones, which is the point);
  a skipped line with a part reads `name part: phrase`, fits 80 columns and cuts the name, not the
  phrase; the JSON `skipped` entry has `name`, `part` and `reason`, with `part` `null` for a loose
  file; the example in `docs/json-schema.md` equals the real output. — RF-07, RF-08, ADR-7
- [x] `src/mailvigil/messages/en.py`, `pt_br.py` (ASCII only), `render.py`, `render_json.py`,
  `docs/json-schema.md`: one sentence per new reason in each language; the part in the skipped
  line; `part` in `_skipped` and in the schema table and example, with the four reasons added to
  the examples. — RF-07, RF-08
- [x] Quality gate of the stage: `uv run ruff check .` → `uv run black --check .` → `uv run mypy` →
  `uv run pytest --cov`. Record the result here, with the number of tests and the coverage.
  **Result (2026-10-28):** `ruff` clean, `black` unchanged, `mypy` strict clean on 22 source files,
  `pytest --cov` 1,101 tests passed, coverage 100% (1,476 statements, 314 branches).

## Stage 2 — The message reader (RF-01 to RF-05, RF-09, RNF-01 to RNF-04, ADR-1 to ADR-4, ADR-9)

- [x] `tests/test_reports_mail.py`, `read_message`, written first: one report attached as `.zip`,
  `.gz` and `.xml` (each built with `EmailMessage.add_attachment`) gives one `Attachment` with the
  right `name`, `kind` and the bytes put in; upper-case suffix; a name written as an encoded word
  (RFC 2047) and as an extended parameter (RFC 2231) is decoded before the suffix is checked; no
  name with each of the six content types gives the right `kind`; a name with an unknown suffix and
  a known type is a candidate, a name with a known suffix and `application/octet-stream` too; a
  text body, an image and a calendar part give nothing; two candidates come in message order; a
  forwarded `message/rfc822` is not entered; a `multipart/signed` wrapper is read; base64 and
  quoted-printable. — RF-01, RF-03, ADR-4, ADR-9
- [x] Same file, hostile input: more than `MAX_LINES` lines made of blank lines and, separately, of
  headers is `message_too_complex`, and a spy on `BytesFeedParser.feed` shows the parser was never
  fed (no stopwatch in the test); a parts bomb (`MAX_PARTS + 1` empty parts); nesting past
  `MAX_DEPTH`, and nesting of 2,000 levels, which must be `message_too_complex` and never
  `RecursionError`; a parser failure forced with a monkeypatched factory that raises `ValueError`
  is `malformed_message`; truncated base64 and an unknown transfer encoding give an `Attachment`
  whose bytes the reader later refuses; an attachment name with control characters and a
  bidirectional override comes out cleaned and at most 255 characters. — RF-04, RF-05, RF-09, ADR-1,
  ADR-2
- [x] Same file, `read_message_file`: a file over `MAX_MESSAGE_BYTES` is `message_too_large` before
  it is opened (a spy on `Path.open`); a file that grows between the `stat` and the read is still
  refused; a directory and a missing file are `unreadable`; an exact-size file passes. — RF-05
- [x] Same file, `iter_mailbox`: several messages in order with their numbers from 1; text before
  the first separator is dropped; the three separator shapes of ADR-3 (`From - Tue Oct 28 10:00:00
  2025`, with a sender and with a `+0000` zone) split, and `From me to you` inside a body does not;
  a line longer than the read size does not split a message nor start one when its tail begins with
  `From `; an oversized message among good ones is yielded as `message_too_large` and the next one
  is still read; a file with no separator and the size of the whole mailbox is one refused message,
  and the peak memory stays near the limit (a `tracemalloc` bound, generous); an empty stream
  yields nothing; `\r\n` line endings. — RF-02, RF-05, ADR-3
- [x] `src/mailvigil/reports/mail.py`: the four constants, `Attachment`, `read_message_file`,
  `read_message` (line pre-check, chunked `BytesFeedParser` with the counting factory, iterative
  walk, suffix then content type, `get_payload(decode=True)`, the caught exceptions of the design)
  and `iter_mailbox` with `_FROM_LINE`. Imports `errors`, `reader`, `text` only. Docstrings with
  `Args:` / `Returns:` / `Raises:`; `# why` comments on the factory seam, the pre-check and the
  separator regex. — RF-01 to RF-05, RNF-01 to RNF-03, ADR-1 to ADR-4, ADR-9
- [x] `src/mailvigil/reports/__init__.py`: re-export the new names of the design. `README.md` of
  the package docs is not touched here. — RF-08, ADR-8
- [x] Quality gate of the stage: `uv run ruff check .` → `uv run black --check .` → `uv run mypy` →
  `uv run pytest --cov`. Record the result here. Run the suite on 3.12 and on the newest Python
  available locally, because ADR-1 leans on a seam of the `email` package.
  **Result (2026-10-28):** `ruff` clean, `black` unchanged, `mypy` strict clean on 23 source files,
  `pytest --cov` 1,157 tests passed on 3.12 with coverage 100% (1,601 statements, 362 branches), and
  the same suite passed on 3.15.1. Two small moves outside the list: `MAX_TEXT` now lives in
  `text.py` (so `mail.py` does not import the parser, as the design says; `parser.py` still exposes
  it) and `reader._KINDS` became the public `KIND_BY_SUFFIX`. `read_message` also refuses a `raw`
  over `MAX_MESSAGE_BYTES`, for a caller that has bytes and not a file (spec 009). A mailbox with no
  separator at all is read as one message (small: read; over the cap: refused), which reconciles
  "text before the first separator is dropped" with RF-05.

## Stage 3 — Wiring: discovery, ingestion, CLI (RF-01, RF-02, RF-06, RF-07, RF-08, RNF-04, ADR-5, ADR-6)

- [ ] `tests/test_reports_discovery.py`, written first (the file is edited because `discover`
  changes its return type): the existing cases pass with `Source` in place of `Path`; `.eml` and
  `.mbox` in a folder are found in name order with the attachments, whatever their names and
  letter case; `explicit` is `True` for a named file and `False` for a listed one; a file named
  twice keeps the first spelling and its flag; a subfolder is not entered; a `.txt` in the folder is
  not listed. — RF-06, ADR-5
- [ ] `tests/test_reports_ingest.py`, first: the same report as a loose `.zip` and inside an `.eml`
  is kept once with `duplicates == 1`; an `.mbox` with three messages gives the reports in file
  order; the non-report messages of a mailbox are not in `skipped`; an explicit `.eml` with no
  attachment is `no_report_attachment` and the same file found in a folder is silent; an `.eml` with
  a good and a bad attachment keeps the good one and skips the bad one with its `part`; the `part`
  of a mailbox refusal starts with `#<n>`; `Report.source_file` of a message report is
  `<file>: <part>`; an oversized message among good ones costs one `skipped` entry; nothing the
  attachment's name holds survives uncleaned; the result is identical on two runs. — RF-01, RF-02,
  RF-07, RF-08, RNF-04, ADR-6
- [ ] `src/mailvigil/reports/discovery.py` and `ingest.py`: `Source`, the folder listing of
  `.eml`/`.mbox`, `Document`, `_documents` (loose file, `.eml`, `.mbox`), the part and source
  strings built in one place; the loop of `ingest` unchanged apart from what it iterates.
  — RF-01, RF-02, RF-06, RF-07, ADR-5, ADR-6
- [ ] `tests/test_cli_summary.py`, `tests/test_cli_verdict.py`, `tests/test_cli_json.py` (a new
  `tests/test_cli_mail.py` if a file grows too much), first, through `main(argv)` and `capsys`: an
  `.eml` and an `.mbox` through `summary` and `verdict` give the same text and the same exit code as
  the same reports as loose files; `--json` has `skipped[].part`; `--lang pt-BR` shows the new
  reasons in Portuguese; `--help` mentions `.eml` and `.mbox`. — RF-08
- [ ] `src/mailvigil/cli.py`: the help of `PATH`. — RF-08
- [ ] Quality gate of the stage: `uv run ruff check .` → `uv run black --check .` → `uv run mypy` →
  `uv run pytest --cov`. Record the result here.

## Stage 4 — Close (RF-01 to RF-09, all RNF)

- [ ] Validate end to end with synthetic data built by a throwaway script outside the repository
  (in the scratchpad): an `.eml` per provider shape (zip, gz, xml, an attachment with no name), a
  mailbox of 200 messages of which 5 are reports, a mailbox with one 20 MiB message, one with no
  separators; run `mailvigil summary` and `mailvigil verdict` over them in both languages and with
  `--json`. Record what was seen, including the time and the peak memory of the large cases.
  — RF-02, RF-05
- [ ] Docs: `README.md` (the input row names `.eml` and `.mbox`; the "Planned" sentence drops the
  first item), `CLAUDE.md` (the architecture tree gets `mail.py` and the new tests),
  `docs/stack.md` (`email`, `email.policy`, the message factory seam, `io.BytesIO`, `bytearray`),
  `specs/README.md` (the roadmap row to `done`), this file and the other two (`status: done`).
  Run `/atualizar-docs`. — RF-08, RNF-01
- [ ] Quality gate of the spec, the whole sequence on the final branch: `uv run ruff check .` →
  `uv run black --check .` → `uv run mypy` → `uv run pytest --cov`, and `uv lock --check`; confirm
  `dependencies = []` and that the CI `package` job would still pass (`uv build`, then no
  `Requires-Dist` in the wheel). Record the result here. — RNF-01
