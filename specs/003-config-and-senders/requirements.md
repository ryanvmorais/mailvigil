---
feature: Config and senders — a TOML file with the domain and a DKIM selector to service name map
status: done
date: 2026-10-27
related:
  - 001-foundation/requirements.md
  - 002-report-ingestion/requirements.md
origin: conception
---

# 003 — Config and senders

## Context and problem

[002](../002-report-ingestion/) turns a pile of attachments into typed records, but a record only
says *where* mail came from (an IP address) and *what signed it* (a DKIM domain and selector). It
does not say *who* that is. The person running the tool knows: `resend` is the newsletter service,
`zoho` is the mailbox. Nobody else can guess it, and a wrong guess is worse than no guess, because
the summary and the `reject` verdict (specs `004` and `005`) are built on "this traffic is mine"
versus "this traffic is a stranger's".

So this spec adds the two things the later specs need to talk about senders:

- **A configuration file** (TOML) that holds what only the owner knows: which domain the reports
  are about, and which DKIM selectors belong to which service. 002 took the domain as a plain
  argument on purpose (its Resolved decision 4); this is where it comes from.
- **Sender identification**: given a record and the configuration, name the service that sent it,
  or say that it is unknown. "Unknown" is the interesting answer: it is exactly what the owner must
  see before hardening the policy.

The starting point is the pair of constants in the maintainer's site script
(`DOMINIO_PADRAO` and `REMETENTES_CONHECIDOS`, a selector to name dictionary), which become
configuration. Reading it closely shows a gap this spec closes: the script trusts the selector
alone. A selector is a label chosen by whoever signs, so a stranger can sign with the selector
`resend` under their own domain and be shown as "Resend". Identification must therefore also look
at *whose domain* signed, and whether the signature passed.

The repository is public and nothing is published yet. This spec adds a library layer, not a
command (as 002 did): the command, and with it where the file is looked for, arrives with `004`.

## Goals

- **Load a configuration file** into an immutable, typed `Config`, with the domain normalized and
  the selector map ready for lookup.
- **Fail loudly and precisely on a bad file**: a typo must not silently turn every sender into
  "unknown" and make a safe domain look unsafe, or the reverse.
- **Identify the sender of a record** from its DKIM results and the configuration, trusting a
  selector only when the signature passed and belongs to the owner's domain.
- **Keep the layer pure**: no printing, no exit codes, no searching the disk, no environment; the
  caller decides where the file is and what to show.

## Non-goals

- Grouping records by sender, counting, classifying as `ok` / `fragile` / `failing`: spec `004`.
- The verdict and its thresholds: spec `005`.
- Where the file lives by default, the `--config` and `--domain` flags, and what a missing file
  does: they belong to the command (spec `004`), and the exit codes to spec `006`.
- The text shown for an unknown sender and its language: spec `006`. This layer returns "no
  service", not a string to print.
- A built-in table of well-known services and selectors (see Resolved decision 4).
- Identifying a sender by IP address, SPF domain or reverse DNS (see Open question 2).
- Writing, generating or editing the configuration file; environment variables as a source.

## Personas

- As the **maintainer** (and any domain owner), I want to write down once which selector is which
  service, so that the next run names my senders and puts a stranger on a line of its own.
- As a **user who copied an example config** and mistyped a key, I want a clear error that names the
  key and the line, so that I do not read a wrong summary and believe it.
- As a **contributor to the next specs**, I want one `Config` and one `identify_sender` that I can
  call with built values, so that the summary and the verdict are unit-tested without TOML or
  files.

## Functional requirements

### RF-01 — Load the configuration file

- **Given** a TOML file with a `domain` and, optionally, a `[senders]` table
  **When** it is loaded
  **Then** the result is an immutable `Config` holding the normalized domain and the selector map.
- **Given** a path that does not exist, is a folder, or cannot be read
  **When** it is loaded
  **Then** it is refused with a reason that names the cause, and the program does not crash.
- **Given** a file larger than 64 KiB
  **When** it is loaded
  **Then** it is refused without being parsed: a configuration is a few lines, and the reader
  should not take an arbitrary file.
- **Given** a file that is not valid TOML
  **When** it is loaded
  **Then** it is refused with a reason carrying the parser's line and column, not a stack trace.
- **Given** a file that is not valid UTF-8
  **When** it is loaded
  **Then** it is refused with a reason saying so.

### RF-02 — The domain

- **Given** `domain = "Example.COM."`
  **When** it is loaded
  **Then** the domain is `example.com`: lower case, no trailing dot, surrounding spaces ignored,
  the same normalization `ingest` applies to its argument, so the two always agree.
- **Given** a domain that is missing, empty, not a string, or not a plausible host name (spaces, a
  scheme such as `https://`, a path, an `@`, empty labels, a label longer than 63 characters, or
  more than 253 characters in all)
  **When** it is loaded
  **Then** it is refused with a reason that names the problem.
- **Given** a domain with non-ASCII characters
  **When** it is loaded
  **Then** it is refused with a reason that says to write it in its `xn--` (punycode) form, because
  that is how it appears in reports (see Open question 4).
- **Given** a domain that is a single label with no dot (`localhost`, `com`)
  **When** it is loaded
  **Then** it is refused: a DMARC domain has at least two labels.

### RF-03 — The selector map

- **Given** a `[senders]` table of `selector = "Service name"` pairs
  **When** it is loaded
  **Then** each selector is stored in lower case and the map is read-only.
- **Given** two keys that differ only by case (`Resend` and `resend`)
  **When** it is loaded
  **Then** it is refused as a duplicate: silently keeping one would be a guess.
- **Given** a selector key that is empty or contains characters a DKIM selector cannot have
  (whitespace or characters outside letters, digits, `.`, `-`, `_`)
  **When** it is loaded
  **Then** it is refused with a reason that names the key.
- **Given** a service name that is not a string, is empty or blank, or is longer than 100
  characters
  **When** it is loaded
  **Then** it is refused with a reason that names the key.
- **Given** no `[senders]` table, or an empty one
  **When** it is loaded
  **Then** it is accepted: the map is empty and every sender will be unknown (a first run on a new
  domain is a legitimate case).

### RF-04 — Unknown keys are errors

- **Given** a top-level key or a table that the format does not define (a typo such as `domian`, or
  `sender` for `senders`)
  **When** it is loaded
  **Then** it is refused with a reason that names the key and, when one is close, suggests the
  intended one.
- **Given** a key of the `[fetch]` table that the format does not define, or one whose name
  suggests a password (*amendment of 2026-10-30, issue #75, design ADR-7*)
  **When** it is loaded
  **Then** it is refused with a reason that names the key as `fetch.<name>`: the second
  case has a reason of its own, and the value is never repeated in the error.
- **Given** a `[senders]` entry whose value is a table or a list instead of a string
  **When** it is loaded
  **Then** it is refused with a reason that names the key. (Nested forms are reserved for future
  versions and must not be half-understood today.)

### RF-05 — Text from the file is inert

- **Given** a service name or a domain containing line breaks, C0 or C1 control characters, or
  bidirectional overrides
  **When** it is loaded
  **Then** the file is refused with a reason that names the key. Unlike a third party's report,
  which is cleaned and kept (002 RF-05), a configuration is written on purpose, so a control
  character in it is a mistake the owner should fix, not text to repair silently.

### RF-06 — Identify the sender of a record

- **Given** a record with a DKIM block whose result is `pass`, whose `d=` domain is the configured
  domain or a subdomain of it, and whose selector is in the map
  **When** the sender is identified
  **Then** the result carries the service name and the selector that matched.
- **Given** a record whose only matching selector comes from a block that did not pass
  **When** the sender is identified
  **Then** there is no service name, and the result says a configured selector was seen on a
  failing signature (a legitimate service that broke, which is not the same as a stranger).
- **Given** a record whose matching selector was signed under a domain that is not the configured
  domain or one of its subdomains (a stranger reusing the selector `resend`)
  **When** the sender is identified
  **Then** there is no service name, and the result says a configured selector was seen on a
  foreign domain.
- **Given** a record with no DKIM block, or none whose selector is in the map
  **When** the sender is identified
  **Then** there is no service name and the result says the sender is unknown.
- **Given** a record with several qualifying DKIM blocks that map to different services
  **When** the sender is identified
  **Then** the first in document order wins, deterministically (see Open question 3).
- **Given** a domain that merely ends with the configured one (`notexample.com` against
  `example.com`)
  **When** the `d=` domain is compared
  **Then** it is not a subdomain: only the exact domain or a name ending in `.example.com` counts.
- **Given** an empty selector, or an empty `d=` domain, in a DKIM block
  **When** the sender is identified
  **Then** that block never matches.

### RF-07 — Refusals are typed

- **Given** any refusal in RF-01 to RF-05
  **When** the caller reads it
  **Then** it carries a machine-readable reason and the key it concerns, plus a short English
  detail for logs, so spec `006` can show it in English or Portuguese (the same shape as 002's
  `ReportRefused`).
- **Given** the loader
  **When** the file has several problems
  **Then** the first one found is reported, in a fixed order, and it is enough to fix and run again
  (one clear message beats a list in a file this short).

### RF-08 — Hostile and mistaken input is tested, not assumed

- **Given** the test suite for this spec
  **When** it runs
  **Then** it contains, at least: an oversized file; non-UTF-8 bytes; malformed TOML; each kind of
  bad domain; duplicate selectors differing by case; a control character in a name; an unknown
  key; and, for identification, the stranger with the right selector on a foreign domain, the
  `notexample.com` look-alike, and the failing signature. Each one expects a refusal with a reason
  or the "no service" result named above.

## Non-functional requirements

### RNF-01 — Standard library only

- **Given** the project at any commit
  **When** `[project].dependencies` is read
  **Then** it is still empty. The file is read with `tomllib` (standard library since Python 3.11,
  so inside the 3.12 floor).

### RNF-02 — Read-only and offline

- **Given** any input
  **When** the file is loaded
  **Then** it is opened for reading only; nothing is written, no network is touched, and nothing in
  the file is ever executed or interpolated (no includes, no environment expansion).

### RNF-03 — No side effects in the layer

- **Given** the loader and `identify_sender`
  **When** they run
  **Then** they do not print, do not read `sys.argv`, do not call `sys.exit`, do not read the
  environment and do not search for a file: the path comes through an argument, so they are
  unit-testable with `tmp_path` and no `capsys`.

### RNF-04 — Typed and immutable

- **Given** the model
  **When** `mypy` runs in strict mode
  **Then** it passes, `Config` and the identification result are frozen dataclasses, and no mutable
  mapping or list is exposed (the selector map is read-only).

### RNF-05 — Deterministic

- **Given** the same file and the same record
  **When** they are loaded and identified twice
  **Then** the results are equal, whatever the order of the keys in the file.

### RNF-06 — Fits the Python floor

- **Given** the Python floor `3.12` set in [001](../001-foundation/)
  **When** the layer is written
  **Then** it uses nothing newer, and the CI matrix (3.12 and the newest stable) passes.

### RNF-07 — Synthetic fixtures only

- **Given** the tests
  **When** they need a configuration or a record
  **Then** they build it in the test (`tmp_path`, built dataclasses) from invented domains
  (`example.com`, `example.org`, `example.net`) and invented service names. The maintainer's real
  configuration never enters the repository (`mailvigil.local.toml` is git-ignored).

## Open questions

None. Questions 1 to 5 were answered on 2026-10-27 (the maintainer approved the recommendations)
and are Resolved decisions 6 to 10.

## Resolved decisions

1. **The selector alone is not trusted** (RF-06): it counts only on a passing signature under the
   owner's domain or a subdomain. This closes a gap in the source script and is the reason
   identification belongs in this spec and not in the summary.
2. **The loader takes a path and nothing else.** Looking for the file (current folder, `--config`,
   a user config directory) is the command's job (spec `004`); this layer is testable with
   `tmp_path`.
3. **Strict file format** (RF-04): unknown keys are errors, not warnings. A silent typo changes the
   answer, and the answer is a security decision.
4. **No built-in table of well-known services.** Selectors such as `default`, `selector1` or `k1`
   are shared by unrelated services, and a wrong built-in name would be shown as fact. The owner's
   map is the only source; an unknown sender is shown as unknown. A table of curated, unambiguous
   defaults can be reconsidered after v1.0.0 if users ask.
5. **No recursion into the file format**: no includes, no variables, no environment expansion
   (RNF-02). A configuration is a short, readable list.
6. **One `domain` in 1.0.0.** `ingest` takes one domain and the verdict is per domain; a list can
   be added later without breaking the file format.
7. **Identify by DKIM selector only.** A sender that passes only SPF is shown as unknown, which is
   the safe failure; an SPF-domain table is the next step if real reports need it.
8. **Several qualifying signatures: the first in document order wins.** No "ambiguous" state.
9. **Internationalized domains are refused** with a message to write the `xn--` form.
10. **Three kinds of "no service"** (failing signature, foreign domain, unknown) are kept distinct.

## Tests

Following [specs/README.md](../README.md#how-a-spec-is-tested):

- **Unit tests, no CLI:** `load_config` and `identify_sender` are called directly, with `tmp_path`
  files and built `Record` values.
- **Hostile and mistaken input:** the cases of RF-08, each expecting a refusal with a reason (or the
  named "no service" result).
- **Synthetic only:** domains, selectors and names are invented (RNF-07).
- **Quality gate last:** `ruff` → `black --check` → `mypy` → `pytest --cov`, with its real result
  recorded in `tasks.md`.
