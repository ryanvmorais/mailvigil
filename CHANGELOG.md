# Changelog

All notable changes to MailVigil are written here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the versions follow
[Semantic Versioning](https://semver.org/); what counts as a breaking change is in
[docs/stability.md](docs/stability.md).

## [Unreleased]

### Added

- **`fetch --config FILE` reads the mailbox from a `[fetch]` table.** The table takes `host`, `user`,
  `port` and `folder`, so a scheduled job stops repeating them; a flag wins over the file, and `fetch`
  reads a file only when `--config` names it. The password is not a key: `password` is refused with
  its own reason (`invalid_fetch_value` and `password_not_allowed` are new). A run with no host or
  user still ends with exit code `2`.

- **`fetch --json` prints the outcome of a run as one JSON document.** A script that runs `fetch`
  from `cron` had to parse the text to read the six numbers. With `--json`, a finished run prints
  `schema_version`, `command` and the six numbers (`matched`, `saved`, `already`, `too_large`,
  `skipped`, `left`) and nothing else: no folder, host or user. A refused run still prints no
  document, one line goes to standard error and the exit code is `1`. `--lang` is accepted and
  changes nothing. The `domain` key is no longer promised in every document: `summary` and
  `verdict` keep it, `fetch` has none (`docs/json-schema.md`).

## [1.2.0] - 2026-10-30

### Added

- **`--recursive` searches the subfolders of a folder, and a report renamed on download is no longer
  silent.** `summary` and `verdict` read a folder one level deep, only for the providers' names, so
  reports kept in a folder per month were not found. `--recursive` goes down up to 8 levels, in name
  order, and never enters a linked folder. A `.zip`, `.gz` or `.xml` file that a folder search did
  not read because of its name is now counted: "passed over by name" in the left-out block of the
  summary (only when there is one), in the left-out sentence of the verdict and the HTML page, and
  as the new `passed_over` integer in the two `--json` documents (`left_out.passed_over` in the
  verdict). The "no report found" message names the option.

- **`fetch --cafile FILE` trusts a private certificate authority.** A mail server behind a company
  or home-lab authority was refused with `certificate_invalid`, and the only way out was to change
  the machine's trust store. The PEM file now adds its authorities to the system's, and the
  certificate and the host name are still checked, so the option can only add trust, never skip a
  check. A file that is missing, cannot be read or holds no certificate is refused before the
  password is asked for, with the new reason `cafile_unusable`.

## [1.1.2] - 2026-10-30

### Changed

- **A report built to be expensive for its size is refused.** An XML nested more than 32 levels deep
  or holding more than 500,000 elements is skipped with the new reason `xml_too_complex`, while it
  is read. A real report has about six levels and, at the 5 MiB cap, about 230,000 elements, so
  none is refused. The worst case drops from 213 MB of memory to 1 MB (nesting) and from 108 MB to
  42 MB (empty elements). The reason shows up in the skipped files of the text and of `--json`.

## [1.1.1] - 2026-10-30

### Changed

- **`fetch` accepts a user name or password outside ASCII.** It was refused before. Such a login now
  goes by `AUTHENTICATE PLAIN` in UTF-8, only when the server offers it (`AUTH=PLAIN`); otherwise
  the run is refused as before. A login in plain ASCII still uses `LOGIN`, and nothing else
  changes. A control character in the password is still refused.

## [1.1.0] - 2026-10-30

### Added

- **Portuguese README.** `README.pt-BR.md` is the whole README in Brazilian Portuguese, with the
  sample output of `--lang pt-BR`; the English README links to it.

- **`verdict --html --output FILE`.** Writes the page to a file itself, as ASCII bytes, replacing a
  file already there, so it no longer depends on the shell: Windows PowerShell 5.1 turns `>` into
  UTF-16. It needs `--html`; without `--output` nothing changes.

- **A logo for the tool.** An envelope with an open eye, `docs/images/mailvigil-dmarc-analyzer-logo.svg`,
  shown at the top of both READMEs.

### Changed

- **The HTML report header.** `verdict --html` now opens with the new symbol, in the accent colour
  of the page, where it had a shield outline. The page still loads nothing: the symbol is an inline
  SVG.
- **Faster reading of reports.** Cleaning a text skips the per-character walk when it is plain
  printable ASCII, and the fields of a record are read by direct lookups instead of path searches.
  On 300 files of 100 records the read went from about 11,400 to about 17,600 records per second.
  The cleaning, the refusals and the output are unchanged.
- **License metadata.** The package now declares its license as the SPDX expression `Apache-2.0`
  (PEP 639) instead of the deprecated table and classifier. The license itself is unchanged.

## [1.0.0] - 2026-10-29

### Added

The first release. It gathers the milestones `v0.1` to `v0.9` described in the README.

- **Reading reports.** `summary`, `verdict` and the other commands read DMARC aggregate reports
  from files and folders: `.xml`, `.gz` and `.zip`, and also `.eml` and `.mbox` mail, where the
  report attachment is taken out in memory. Duplicates, reports of another domain and files that
  are refused are counted, never dropped silently.
- **Hostile input.** A report is untrusted: the decompressed size is capped (zip bombs), XML with
  `DOCTYPE` or `ENTITY` is refused, mail is bounded in size, lines, parts and depth, and a count or
  a period out of range is refused as an invalid field.
- **Configuration.** A strict TOML file with the domain and a map from DKIM selector to service
  name. A signature names a service only when it passes under your own domain.
- **`mailvigil summary`.** The messages per sender and per situation (ok, fragile, failing), the
  failing sources, the period and the policy published, in 80 columns of ASCII text.
- **`mailvigil verdict`.** One of `READY`, `TOO EARLY` and `NOT READY` for `p=reject`, with the five
  rules, what each measured against what it needs, notes (a fragile sender, a partial policy,
  a reporter that went quiet, old data) and the next step. The criterion: 28 days covered, reports on
  80% of the days, 100 messages, no failure from a recognized sender, at most 0.5% of the messages
  failing from unrecognized sources.
- **Exit codes for scripts.** `0` ready or finished, `1` refused, `2` usage, `3` too early, `4` not
  ready, `70` internal error, `130` Ctrl+C and `141` closed pipe.
- **`--json`.** One document for `summary` and for `verdict`, with a `schema_version`
  ([docs/json-schema.md](docs/json-schema.md)).
- **`--lang en|pt-BR`.** Every sentence of the tool in English or Brazilian Portuguese.
- **`verdict --html`.** One self-contained page, with no script and no network: the verdict, each
  rule against its limit and the messages day by day.
- **`mailvigil fetch`.** Downloads the report messages of an IMAP mailbox into a folder, as `.eml`
  files. It is opt-in and the only command that uses the network: always over TLS with the
  certificate checked, read-only (it changes, moves and deletes nothing and does not mark mail as
  read), with the password asked on the terminal or read from a file.

[Unreleased]: https://github.com/ryanvmorais/mailvigil/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/ryanvmorais/mailvigil/compare/v1.1.2...v1.2.0
[1.1.2]: https://github.com/ryanvmorais/mailvigil/compare/v1.1.1...v1.1.2
[1.1.1]: https://github.com/ryanvmorais/mailvigil/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/ryanvmorais/mailvigil/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/ryanvmorais/mailvigil/releases/tag/v1.0.0
