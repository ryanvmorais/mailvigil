---
feature: Several domains in one run, and internationalized domains typed as written
status: approved
date: 2026-10-30
related:
  - 003-config-and-senders/requirements.md
  - 004-summary/requirements.md
  - 005-reject-verdict/requirements.md
  - 006-output-and-exit-codes/requirements.md
  - 008-html-report/requirements.md
origin: conception
---

# 010 — Multiple domains

## Context and problem

A run of MailVigil is about **one** domain. `mailvigil.toml` has one `domain`, and
[002](../002-report-ingestion/) drops the reports of any other domain from the same folder, counting
them as "other domains". Someone who looks after several domains (an agency, a freelancer, a company
with a brand per country) keeps one configuration file and one command per domain, and reads the
same folder of reports once per domain.

The second half of the problem is smaller. A domain with letters outside ASCII (`bücher.example`)
has to be written by hand in its `xn--` form, in the file and in `--domain`; the tool refuses
anything else (`non_ascii_domain`, [003](../003-config-and-senders/) RF-02). The refusal tells the
person what to write, but a person should not need to know what punycode is to type their own
domain.

Both are issue [#79](https://github.com/ryanvmorais/mailvigil/issues/79). It needs a spec of its own
because it crosses the configuration, the command line, the summary, the verdict, `--json`, the
exit codes and `--html` at once, and three of those are public contract
([docs/stability.md](../../docs/stability.md)). The rule that guides every choice below: **a run
with one domain behaves exactly as it does today**, byte for byte, so nobody who already uses the
tool has to change anything. Everything new is reachable only by writing more than one domain.

The question the product answers does not change: for each domain, "who sends mail as it, and is it
safe to move it to `p=reject`?". Several domains give several answers, never one blended answer: a
verdict on a mix of domains would say nothing about any of them.

## Goals

- **Several domains, one command:** one configuration file, one run, one summary and one verdict per
  domain.
- **Each domain keeps its own identity map:** a selector, an SPF domain or an address range that
  names a sender for one domain never names it for another.
- **A script can still decide:** one exit code for the whole run that a `cron` job can act on, and a
  `--json` document that carries each domain's answer.
- **An internationalized domain as it is written:** in the file, in `--domain` and as an `[spf]` key,
  with the `xn--` form still accepted.
- **Nothing changes for one domain:** same file format, same flags, same text, same JSON, same exit
  codes.

## Non-goals

- **Discovering the domains from the reports:** the run is about the domains the person wrote. A
  report of a domain nobody listed is counted as "other domain", as today.
- **A combined summary or verdict across domains:** see the context. A total would hide the domain
  that is not ready behind the ones that are.
- **Settings per domain for the verdict:** the thresholds of [005](../005-reject-verdict/) stay the
  tool's judgment and apply to every domain alike.
- **An index page, or one page with a section per domain:** `--html` writes the page that exists
  today, once per domain (RF-07). A new page layout would need its own mockup and its own spec.
- **Wildcards and "every subdomain of":** a subdomain is a domain only if it is written.
- **Several domains in `fetch`:** `fetch` has no domain; it saves mail, and the reading is the job
  of `summary` and `verdict`.
- **Full IDNA 2008:** the conversion uses the standard library's `idna` codec (IDNA 2003), because
  the product has no runtime dependency. Names that the two versions treat differently are refused,
  not guessed (RF-03).
- **Unicode in the output:** the output stays ASCII (006), so an internationalized domain is shown in
  its `xn--` form.

## Personas

- As an **agency owner** with eight client domains, I want one file and one command that gives me
  the answer for each, so that I do not run a loop of eight commands and merge the text myself.
- As a **domain owner whose name is not ASCII**, I want to type my domain as I write it, so that I do
  not have to convert it first.
- As a **user with a scheduled job,** I want one exit code that is `0` only when every domain is
  ready, and a JSON document that says which one is not.
- As a **user with one domain,** I want nothing to change.
- As a **maintainer,** I want the one-domain code path to be the same code as the many-domain one, so
  that there is one behavior to test, not two.

## Functional requirements

### RF-01 — Several domains in the configuration file

- **Given** a file with an array of tables `[[domains]]`, each with its own `domain` and, optionally,
  its own `[domains.senders]`, `[domains.spf]` and `[domains.ips]`
  **When** the file is loaded
  **Then** every entry is read with the same strict rules as the top level of today's file (an
  unknown key is an error, each name is checked, an `[spf]` key must be within **its own** domain),
  and the result carries one configuration per domain, in the order of the file.
- **Given** a file with the top-level `domain` and no `[[domains]]`
  **When** the file is loaded
  **Then** it is read exactly as today, as a run of one domain.
- **Given** a file that has both a top-level `domain` (or `[senders]`, `[spf]`, `[ips]`) and
  `[[domains]]`
  **When** the file is loaded
  **Then** it is refused, naming the key that clashes: one file is one form or the other, never a
  blend whose rules the reader has to guess.
- **Given** two entries that name the same domain (after normalizing case, a trailing dot and the
  internationalized form of RF-03)
  **When** the file is loaded
  **Then** it is refused as a duplicate, naming the domain.
- **Given** an entry with no `domain`, an empty `[[domains]]`, or more entries than the cap closed in
  the design
  **When** the file is loaded
  **Then** it is refused with a typed reason, never a repair. The `[fetch]` table stays at the top
  level and is unchanged.

### RF-02 — Choosing the domains of a run with `--domain`

- **Given** a file of several domains and no `--domain`
  **When** a command runs
  **Then** it covers every domain of the file.
- **Given** one or more `--domain` values (the option may be repeated) and a file of several domains
  **When** a command runs
  **Then** it covers only those domains, in the order of the file, and a value that is not in the file
  is refused with the message of today's mismatch, naming the value and the file.
- **Given** one or more `--domain` values and no configuration file
  **When** a command runs
  **Then** it covers each of them with an empty identity map, as the single `--domain` does today
  (the first run).
- **Given** a repeated `--domain` that names the same domain twice
  **When** a command runs
  **Then** it is covered once.
- **Given** a run of one `--domain` and a file of one domain (today's form)
  **When** a command runs
  **Then** nothing differs from today.

### RF-03 — Internationalized domains typed as written

- **Given** a domain written with non-ASCII letters (`bücher.example`), in `domain`, in `--domain`
  or as an `[spf]` key
  **When** it is checked
  **Then** it is converted with the standard `idna` codec to its `xn--` form, and from there every
  rule that exists today applies to the converted name (label and length limits, within-the-domain
  for `[spf]`).
- **Given** a domain already written in `xn--` form
  **When** it is checked
  **Then** it is accepted as today and is the same domain as its Unicode spelling: the two together
  in one file are a duplicate (RF-01).
- **Given** a name that the conversion would **rewrite into a different name** than the one typed,
  beyond lower-casing (the codec maps `ß` to `ss`, and the Kelvin sign to `k`), or that is not a valid
  internationalized name
  **When** it is checked
  **Then** it is refused, naming the key and saying why. A report for `fass.example` must never be
  counted for a person who typed `faß.example`: the existing guard against look-alike letters (003,
  the Kelvin sign) is kept, not loosened.
- **Given** an internationalized domain
  **When** anything is printed (text, `--json`, `--html`, a refusal line)
  **Then** it is the `xn--` form, in ASCII, as the reports themselves carry it.

### RF-04 — One reading, one result per domain

- **Given** a folder of reports and a run of several domains
  **When** the reports are read
  **Then** each file is opened and parsed **once**, however many domains the run has, and every
  report goes to the domain it belongs to. A report is never counted for two domains.
- **Given** a report whose domain is in the run
  **When** the result of another domain of the run is made
  **Then** that report is **not** counted there as "other domain": it belongs to a domain that has
  its own result. "Other domain" counts only the reports that belong to no domain of the run.
  For a run of one domain this is today's meaning.
- **Given** two files holding the same report
  **When** the run covers several domains
  **Then** it is one duplicate, as today.
- **Given** a domain of the run for which no report was found, while another has some
  **When** the results are made
  **Then** that domain has a result that says so and its verdict is `too early`; the run is not
  refused. The run is refused (`1`, with the line of today) only when **no** domain has a report.

### RF-05 — `summary` and `verdict` print one block per domain

- **Given** `summary` on a run of several domains
  **When** it prints
  **Then** the text is the summary of each domain in the order of the run; each block is the text of
  a single-domain run (80 columns, ASCII, its title already names the domain), and the blocks are
  set apart by a rule line, so what a person knows how to read does not change.
- **Given** `verdict` on a run of several domains
  **When** it prints
  **Then** it is the same, with the verdict of each domain, and at the end one line that counts the
  answers (for example "2 ready, 1 too early, 1 not ready") so the person does not have to scan.
- **Given** `--lang pt-BR`
  **When** the new lines print
  **Then** they are in Portuguese, from the messages module like every other sentence.

### RF-06 — The exit code of `verdict` is the worst answer

- **Given** a run of several domains
  **When** `verdict` finishes
  **Then** the exit code is `4` if any domain is `not ready`, else `3` if any is `too early`, else `0`
  (every domain is ready). It is the worst answer, so `0` means "safe to move all of them".
- **Given** a run that is refused (RF-04, no report at all; a bad configuration; a bad `--domain`)
  **When** it ends
  **Then** the code is `1` or `2` as today, decided before any text, and no domain gets a partial
  answer.
- **Given** `summary` on several domains
  **When** it prints
  **Then** it exits `0`, as today.
- **Given** the codes
  **Then** no code is added or changed: the meaning of `0`, `3` and `4` for one domain is the
  special case of this rule.

### RF-07 — `--json` and `--html` with several domains

- **Given** `--json` on a run of **one** domain
  **When** it prints
  **Then** the document is the one of today, unchanged (`schema_version` 1).
- **Given** `--json` on a run of **several** domains
  **When** it prints
  **Then** it is one document with `schema_version`, `command` and a `domains` list holding, in the
  order of the run, the document of each domain exactly as a single-domain run would print it; for
  `verdict` it also carries the worst answer, so a script reads the code's meaning from the
  document. The new shape is described in `docs/json-schema.md`; a field is added, none changes.
- **Given** `--top N` with several domains
  **When** it prints
  **Then** it trims each domain's lists, and each domain's own `top` key says what was left out.
- **Given** `--html` on a run of one domain
  **When** it runs
  **Then** nothing differs from today (standard output, or `--output FILE`).
- **Given** `--html` on a run of several domains
  **When** it runs
  **Then** `--output` names a **folder** and the command writes one page per domain,
  `mailvigil-<domain>.html`, each the page of 008 for that domain, unchanged. Without `--output` it is refused
  before any work, saying why: several pages cannot go to one stream. The names are built from the
  validated ASCII domain, so no name can leave the folder, and the prefix keeps a domain such as
  `con.example` from becoming a reserved device name on Windows.
- **Given** a page that cannot be written
  **When** the command runs
  **Then** it ends in the refusal of today's `output_failed`, naming the file; the pages already
  written are complete files (each is written atomically as in ADR-11 of 008), never a half page.

### RF-08 — `fetch` and the network are untouched

- **Given** a configuration file with `[[domains]]`
  **When** `fetch --config FILE` runs
  **Then** it reads the `[fetch]` table as today and the file is accepted; no domain is used, and
  `summary` and `verdict` still never load the network code.

## Non-functional requirements

### RNF-01 — A public contract that only grows

- **Given** the one-domain runs
  **When** the existing tests run unchanged
  **Then** they pass: text, JSON, HTML, exit codes and configuration errors for one domain are
  identical. The release is a **minor** one (a new key, a new option form and a new document shape,
  all reachable only by writing several domains); `docs/stability.md`, `docs/json-schema.md`, the
  README and the CHANGELOG are updated in the same stages.

### RNF-02 — Bounded

- **Given** hostile or careless input
  **When** it has many domains
  **Then** the number of domains, the size of the file (64 KiB) and the size of each page and
  document stay bounded; a cap on domains is closed in the design with its reason. Reading the
  reports does not grow with the number of domains (RF-04).

### RNF-03 — Deterministic

- **Given** the same files and the same arguments
  **When** the run is repeated
  **Then** the order of domains (the file's, or the first `--domain` given when there is no file),
  the text and the JSON are identical.

### RNF-04 — Zero dependencies, offline, ASCII

- **Given** the wheel
  **When** it is built
  **Then** it declares no dependency, nothing in the run touches the network, and every line printed
  is ASCII in both languages.

### RNF-05 — Hostile text stays text

- **Given** a domain, a service name or a key taken from the file or the command line
  **When** it is printed or becomes a file name
  **Then** it goes through the same escaping and checking as today; a domain that is a file name only
  after RF-03 has validated it (letters, digits, hyphen and dots).

### RNF-06 — Synthetic data and the quality gate

- **Given** the tests
  **When** they need reports and domains
  **Then** every domain is invented (`example.com`, `example.net`, `.invalid`, an invented
  internationalized name) and every address is in a documentation range. The gate (`ruff`, `black`,
  `mypy` strict, `pytest --cov` at 100%) closes every stage.

## Open questions

Answered on 2026-10-30: the maintainer approved the requirements with the recommendation of all
five. Each had one; none was a guess to be left as is.

1. **A domain of the run with no reports (RF-04).** Recommended: not a refusal; its result says "no
   reports" and its verdict is `too early`. An agency that adds a new client domain should still
   get the answers for the other seven. The alternative is to refuse the whole run, which is what a
   single domain does today and makes the new domain block the rest. The design checks that the
   verdict can say it honestly (no number invented).
2. **What "other domain" counts with several domains (RF-04).** Recommended: only the reports that
   belong to no domain of the run, so a report is never reported as dropped by one block and kept by
   another. The alternative is to count, in each block, every report that is not its own, which
   makes the numbers of the blocks add up to more than the files read.
3. **The JSON shape follows the number of domains in the run (RF-07).** Recommended: one domain
   gives today's document even when the file lists several (a script that passes one `--domain`
   gets what it always got), several give the new `domains` document. The alternative is to tie the
   shape to the file, which is steadier for a script but changes what `--domain a` prints depending
   on the file.
4. **The cap on domains (RF-01).** Recommended: a small fixed number, closed in the design (an agency
   of dozens is plausible; thousands is a misuse). Raising it later is a minor change.
5. **`--output` as a folder (RF-07).** Recommended: the folder must already exist, as the parent of
   `--output FILE` must today, and an existing page of the same name is replaced atomically. The
   alternative, creating the folder, makes a mistyped path silently create a directory tree.

## Resolved decisions

Answered by the maintainer on 2026-10-30.

1. **The file form: `[[domains]]`, each with its own maps.** Not a repeated `--config` and not one
   shared map: a range of addresses or an SPF domain that names a sender for one client must not
   name it for another, because that would hide a failing source and change a verdict. The one-domain
   form stays valid.
2. **`--json`: today's document for one domain, a new document for several.** No `schema_version` 2
   and no major release.
3. **`--html`: one page per domain in a folder.** The page itself is unchanged, so this spec needs no
   interface mockup; an index page or a combined page is a non-goal.

## Tests

Following [specs/README.md](../README.md#how-a-spec-is-tested):

- **Unit tests, no CLI:** the loader on files of one and of several domains, and every refusal of
  RF-01 and RF-03; the conversion on a table of inputs (accented letters, `xn--`, `ß`, the Kelvin
  sign, mixed scripts, a trailing dot); the split of reports per domain; the worst-answer rule.
- **One reading:** a test that counts how many times each file is opened for a run of three domains.
- **Compatibility:** the existing suites for one domain run unchanged, and a golden comparison of the
  one-domain text and JSON before and after.
- **CLI:** `main(argv)` with `capsys` for several domains in text, in Portuguese, `--json`, `--top`,
  `--html --output DIR` and the exit codes; `--domain` repeated, with and without a file.
- **Contract:** `test_json_schema_doc.py` extended to the new document, and the examples of
  `docs/json-schema.md` built by the code.
- **Isolation:** `test_offline_isolation.py` keeps proving that `summary` and `verdict` never load the
  network code.
- **Synthetic only:** RNF-06.
- **Quality gate last:** `ruff` → `black --check` → `mypy` → `pytest --cov`, with its real result
  recorded in `tasks.md`.
