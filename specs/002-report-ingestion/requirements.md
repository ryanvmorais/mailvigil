---
feature: Report ingestion — read DMARC aggregate reports safely into a typed record model
status: approved
date: 2026-10-27
related:
  - 001-foundation/requirements.md
origin: conception
---

# 002 — Report ingestion

## Context and problem

Mail providers (Google, Microsoft, Yahoo, Zoho…) send a DMARC aggregate report (RUA) per domain per
day. It is an XML document, almost always inside a `.zip` or `.gz` attachment, saying how many
messages were sent as the domain, from which IPs, and whether they passed DKIM and SPF aligned with
the `From` domain. Everything MailVigil will say later (the per-sender summary, the `reject`
verdict) is computed from those files, so this spec is the layer every other spec stands on: turn a
pile of downloaded attachments into trustworthy, typed records.

Two things make that layer worth its own spec instead of a helper function:

- **The input is hostile.** Reports arrive from third parties over the internet, and the person
  running the tool drops them in a folder without looking. A zip bomb or an XML entity-expansion
  document must be refused, not parsed. Both defenses are part of the product promise and need
  tests that feed them the attack (see [specs/README.md](../README.md)).
- **The input is messy.** Folders mix reports with unrelated files, the same report is downloaded
  twice (`report (1).zip`), reports for other domains land in the same folder, and one corrupt file
  must not hide the other two hundred good ones.

The starting point is a working script in the maintainer's site repository
(`site-ryan-morais/scripts/relatorios_dmarc.py`) that already reads `.zip`, `.gz` and `.xml`, caps
the decompressed size at 5 MiB, refuses `DOCTYPE` and `ENTITY`, and deduplicates by provider and
report id. This spec carries that behavior over, states it as a contract, and closes the gaps found
while reading it (listed in the requirements below). The script stays in the site repository until
MailVigil is released.

Today `src/mailvigil` holds only the `--version` skeleton from [001](../001-foundation/). This spec
adds the reading layer; it does not add a command (Resolved decision 5).

## Goals

- **Read one attachment** (`.xml`, `.gz` or `.zip`) into XML bytes, without ever writing to disk
  and without exceeding a decompressed size cap.
- **Refuse hostile XML** (entity declarations, document type declarations, malformed or
  non-DMARC documents) before it reaches a parser that would expand it.
- **Parse a report into an immutable, typed record model** that carries every field the later
  specs need (sender identification by IP and DKIM selector, aligned results, disposition, policy,
  period), so they never re-open the XML.
- **Ingest a mixed set of paths** (files and folders): discover candidates, filter by domain,
  drop duplicates, and report what was skipped and why, without one bad file stopping the rest.
- **Keep the layer pure**: no printing, no exit codes, no configuration; the caller decides what to
  show.

## Non-goals

- Classifying records (`ok`, `fragile`, `failing`), grouping by sender or naming services:
  specs `003` and `004`.
- The verdict, the output format, the exit codes and the text language: specs `005` and `006`.
- The TOML configuration (including where the domain comes from): spec `003`. This spec takes the
  domain as a plain argument.
- Fetching reports (IMAP, download, any network access), extracting archives to disk, and watching
  a folder.
- Report formats other than DMARC aggregate (RUA) XML: forensic/failure reports (RUF), SMTP TLS
  reports.
- Persisting parsed reports (database, cache file).

## Personas

- As the **maintainer** (and any domain owner), I want to point the tool at the folder where my
  mail client saved the report attachments, so that I do not have to unzip, sort or deduplicate
  anything by hand.
- As a **user who got a strange attachment** (or a hostile one), I want the tool to refuse it with
  a clear reason and keep going, so that one bad file cannot crash the run or hurt my machine.
- As a **contributor to the next specs**, I want a stable record model and one entry point, so that
  the summary and the verdict can be written and unit-tested without touching XML or the
  filesystem.

## Functional requirements

### RF-01 — Read one attachment

- **Given** a `.xml` file
  **When** it is read
  **Then** its bytes are returned unchanged.
- **Given** a `.gz` file holding one XML document
  **When** it is read
  **Then** the decompressed bytes are returned.
- **Given** a `.zip` file with one `.xml` member
  **When** it is read
  **Then** that member's decompressed bytes are returned, and nothing is extracted to disk.
- **Given** a file whose extension is upper case (`REPORT.ZIP`)
  **When** it is read
  **Then** it is treated like its lower-case form.
- **Given** a file with any other extension
  **When** it is read
  **Then** it is refused with a reason saying the extension is unsupported.
- **Given** a `.zip` with no `.xml` member, a corrupt `.zip`, or a corrupt `.gz`
  **When** it is read
  **Then** it is refused with a reason that names the cause, and the program does not crash.
- **Given** a `.zip` with more than one `.xml` member
  **When** it is read
  **Then** it is refused with a reason saying it holds more than one document (the source script
  silently reads only the first).

### RF-02 — Decompressed size cap

- **Given** a `.gz`, a `.zip` member or a `.xml` whose content is larger than 5 MiB once
  decompressed
  **When** it is read
  **Then** it is refused with a reason saying the limit was exceeded, and no more than the limit
  plus one byte is ever held in memory for that content.
- **Given** a file whose size on disk already exceeds 5 MiB
  **When** it is read
  **Then** it is refused without opening it as an archive.
- **Given** a compressed file that expands far beyond its size on disk (a zip bomb built in the
  test with `zipfile`/`gzip`)
  **When** it is read
  **Then** it is refused, and the cap acts on the bytes actually decompressed, never on the sizes
  declared in the archive headers.
- **Given** a legitimate report a few kilobytes long
  **When** it is read
  **Then** the cap does not interfere.

### RF-03 — Refuse entity declarations and document type declarations

- **Given** an XML document containing a `DOCTYPE` or an `ENTITY` declaration (the entry point of
  entity-expansion attacks such as the "billion laughs")
  **When** it is parsed
  **Then** it is refused with a reason naming the declaration, before any XML parser sees it.
- **Given** such a document encoded in UTF-16 or UTF-8 with a byte order mark
  **When** it is parsed
  **Then** it is refused just the same: the check cannot depend on the document being plain ASCII
  bytes (the source script searches for the ASCII byte string only, and a parser that
  autodetects UTF-16 still reads such a document and expands its entities, checked on
  2026-10-27).
- **Given** a legitimate report with an XML declaration (`<?xml version="1.0"?>`) and comments
  **When** it is parsed
  **Then** it is accepted: only the dangerous declarations are refused.

### RF-04 — Parse a report into the record model

- **Given** the XML of a valid aggregate report
  **When** it is parsed
  **Then** the result is an immutable report with:
  - **metadata:** reporting organization, report id, period start and end (timezone-aware, UTC);
  - **published policy:** domain (lower case), `p`, `pct`, and, when present, `sp`, `np`, `adkim`,
    `aspf`, `testing` and `discovery_method` (the last two are new in RFC 9990);
  - **records:** each with source IP, message count, disposition, DKIM and SPF results as
    evaluated for alignment, the DKIM authentication results (domain, selector, result), the SPF
    authentication result (domain, result), the `From` domain of the message, and the policy
    override reasons the receiver gave (for example, forwarded or mailing list);
  - **origin:** the name of the file it came from, for display only.
- **Given** a document that is well-formed XML but whose root is not `feedback`
  **When** it is parsed
  **Then** it is refused with a reason saying it is not a DMARC aggregate report.
- **Given** malformed XML
  **When** it is parsed
  **Then** it is refused with a reason carrying the parser's position, not a stack trace.
- **Given** a `feedback` root with no namespace (RFC 7489 style) or in the namespace
  `urn:ietf:params:xml:ns:dmarc-2.0` (RFC 9990)
  **When** it is parsed
  **Then** both give the same model. A `feedback` root in any other namespace is refused as not a
  DMARC aggregate report, and elements in foreign namespaces inside the report (extensions) are
  ignored.
- **Given** a `version` element
  **When** it is parsed
  **Then** `1.0` and its absence are accepted; any other value is refused with a reason saying the
  version is unsupported.
- **Given** a record whose `count` is not an integer or is negative, or a period that is not a
  valid timestamp, or a `pct` outside 0 to 100
  **When** it is parsed
  **Then** the whole report is refused: a number the verdict cannot trust is worse than a missing
  report.
- **Given** optional elements that are absent (no `pct`, no override reasons, no SPF block)
  **When** it is parsed
  **Then** documented defaults apply (`pct` 100, empty tuple, empty string) and the report is
  accepted.
- **Given** a report with the quirks real providers produce (whitespace around values, several
  `dkim` blocks in one record, an IPv6 source address)
  **When** it is parsed
  **Then** it is read correctly. The exact list of quirks is closed in the design, from synthetic
  fixtures that imitate them.

### RF-05 — Text fields are inert

- **Given** a report whose organization, report id, selector or domain contains characters that
  can change what a terminal shows or hide text (line breaks, C1 control characters, bidirectional
  overrides)
  **When** it is parsed
  **Then** those characters never survive into the model: they are removed or replaced, so no
  later spec can print them from a third party's file. (The XML parser itself already rejects the
  C0 controls, such as ESC and NUL, in raw text and in character references; checked on
  2026-10-27.)
- **Given** an overlong text field
  **When** it is parsed
  **Then** it is truncated to 255 characters.

### RF-06 — Discover the files to read

- **Given** a path that is a file
  **When** paths are discovered
  **Then** it is always read, whatever its name (the user pointed at it on purpose).
- **Given** a path that is a folder
  **When** paths are discovered
  **Then** only regular files whose name follows the providers' attachment pattern
  (`provider!domain!begin!end….zip|gz|xml`, with a possible `(1)` suffix) are read; everything else
  in the folder is ignored silently.
- **Given** the same file reachable through two of the given paths
  **When** paths are discovered
  **Then** it is read once.
- **Given** a folder
  **When** paths are discovered
  **Then** the files come in name order, so two runs over the same folder give the same result.
- **Given** a path that does not exist or cannot be listed
  **When** paths are discovered
  **Then** it is reported as skipped with the cause, and the other paths are still read.
- **Given** a folder containing subfolders
  **When** paths are discovered
  **Then** the subfolders are not entered and nothing is reported about them.

### RF-07 — Domain filter

- **Given** a domain name and reports for several domains
  **When** the reports are ingested
  **Then** only the reports whose published-policy domain equals the given domain
  (case-insensitive, exact match) are kept, and the others are counted as `other domain`.
- **Given** no reports for the given domain
  **When** the reports are ingested
  **Then** the result is empty and says how many files were skipped for being of another domain,
  so the caller can tell the user "wrong domain?" instead of "nothing found".

### RF-08 — Drop duplicate reports

- **Given** two files holding the same report (same reporting organization and same report id),
  for instance the same attachment downloaded twice
  **When** the reports are ingested
  **Then** the first (in discovery order) is kept, the second is counted as `duplicate`, and its
  records are not summed twice.
- **Given** two reports with the same id from different organizations
  **When** the reports are ingested
  **Then** both are kept: the id is only unique per organization.

### RF-09 — One bad file never stops the others

- **Given** a set of paths where some files are corrupt, oversized, hostile or not reports
  **When** the reports are ingested
  **Then** every readable report is returned, and each refused file appears in the result with its
  path and a reason that identifies the cause (not just a free-text message), so a later spec can
  show it in English or Portuguese.
- **Given** a result
  **When** the caller reads it
  **Then** it carries: the reports kept, the files skipped with their reasons, the number of
  duplicates dropped and the number of reports of other domains dropped. Whether "nothing could be
  read" is an error (and which exit code it maps to) is the caller's decision, in spec `006`.

### RF-10 — Hostile input is tested, not assumed

- **Given** the test suite for this spec
  **When** it runs
  **Then** it contains, at least: a decompressed-size test for each of `.xml`, `.gz` and `.zip`;
  a zip bomb whose declared sizes lie; a `DOCTYPE` test; an `ENTITY` test; a UTF-16 variant of the
  declaration test; a control-character test; and each of them expects a refusal and a reason.

## Non-functional requirements

### RNF-01 — Standard library only

- **Given** the project at any commit
  **When** `[project].dependencies` is read
  **Then** it is still empty. Parsing uses `xml.etree.ElementTree`, `zipfile`, `gzip`, `pathlib`
  and `dataclasses`. If the cap or the declaration check cannot be met with them, that is an ADR
  in the design, not a dependency.

### RNF-02 — Read-only and offline

- **Given** any input
  **When** it is ingested
  **Then** the layer opens files for reading only, never extracts or writes anything, never opens a
  network connection and never executes content from a report.

### RNF-03 — No side effects in the layer

- **Given** the ingestion functions
  **When** they run
  **Then** they do not print, do not read `sys.argv`, do not call `sys.exit` and do not read the
  environment: input comes through arguments and output through return values, so they are
  unit-testable with `tmp_path` and no `capsys`.

### RNF-04 — Typed and immutable

- **Given** the model
  **When** `mypy` runs in strict mode
  **Then** it passes, the model types are frozen dataclasses, and collections in them are tuples.

### RNF-05 — Deterministic

- **Given** the same set of files
  **When** they are ingested twice
  **Then** the reports, the skipped list and the counts are identical and in the same order.

### RNF-06 — Fits the Python floor

- **Given** the Python floor `3.12` set in [001](../001-foundation/)
  **When** the layer is written
  **Then** it uses nothing newer, and the CI matrix (3.12 and the newest stable) passes.

### RNF-07 — Synthetic fixtures only

- **Given** the tests
  **When** they need a report, a zip or a gzip
  **Then** they build it in the test (`tmp_path`, `zipfile`, `gzip`) from invented domains and
  documentation IP ranges (`192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24`, `2001:db8::/32`).
  No real report ever enters the repository.

## Open questions

None. Questions 1 to 6 were answered on 2026-10-27 (the maintainer approved the recommendations)
and are Resolved decisions 5 to 10.

## Resolved decisions

1. **The source script is the starting point, not a dependency.** Its behavior (5 MiB cap,
   `DOCTYPE`/`ENTITY` refusal, dedup by organization and report id, file name pattern for folders)
   is carried over and rewritten under MailVigil's English naming and typing.
2. **Hostile-input defenses ship with this spec,** not later: `DOCTYPE`/`ENTITY` refusal and the
   size cap are in the first version of the layer, each with an attack test.
3. **Refusal is per file, never global:** a file is refused, the run continues.
4. **The domain is an argument here,** not a setting; where it comes from is spec `003`.
5. **Library only, no command.** The first command arrives with spec `004`. Trying the layer on
   real reports before then is done by a throwaway script outside the repository.
6. **The wider record model** (RF-04), not the source script's seven fields: override reasons are
   what separates harmless forwarding failures from a stranger sending as the domain (spec `005`),
   and adding a field after the model is in use ripples through every caller.
7. **A zip with more than one `.xml` member is refused.** A report zip has one; more is suspicious.
8. **No recursion into subfolders.** A `--recursive` flag can come with the command (spec `004`)
   if someone asks.
9. **The domain filter is an exact, case-insensitive match.** `mail.example.com` is not
   `example.com`. Revisit with the configuration (spec `003`) if a real case appears.
10. **Both report generations are read.** RFC 9990 (published, obsoletes RFC 7489) puts `feedback`
    in the namespace `urn:ietf:params:xml:ns:dmarc-2.0` and adds an optional `version` (`1.0`).
    The parser accepts the old no-namespace form and the new one (RF-04). Source:
    [RFC 9990](https://www.rfc-editor.org/rfc/rfc9990.txt), sections 5 and 6.1, read on 2026-10-27.

## Tests

Following [specs/README.md](../README.md#how-a-spec-is-tested):

- **Unit tests, no CLI:** read, parse, discover and ingest are called directly with built inputs and
  `tmp_path`.
- **Hostile input:** the cases of RF-10, each expecting a refusal with a reason.
- **Synthetic only:** every report is built in the test from the ranges in RNF-07.
- **Quality gate last:** `ruff` → `black --check` → `mypy` → `pytest --cov`, with its real result
  recorded in `tasks.md`.
