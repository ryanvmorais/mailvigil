# Changelog

All notable changes to MailVigil are written here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the versions follow
[Semantic Versioning](https://semver.org/); what counts as a breaking change is in
[docs/stability.md](docs/stability.md).

## [Unreleased]

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

[Unreleased]: https://github.com/ryanvmorais/mailvigil/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/ryanvmorais/mailvigil/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/ryanvmorais/mailvigil/releases/tag/v1.0.0
