# Stability

What a script, a CI job or a person can rely on across MailVigil versions, and what can change
without notice. MailVigil follows [Semantic Versioning](https://semver.org/): from `1.0.0`, a change
that breaks something listed under "Public" waits for the next major version.

## Public

These are the contract. Each item says where it is specified.

| Part | What is promised | Specified in |
|---|---|---|
| Commands | The names `summary`, `verdict` and `fetch`, and the arguments and options each has today (`--config`, `--domain`, `--json`, `--lang`, `--html`, `--output`, `--host`, `--user`, `--to`, `--port`, `--folder`, `--since`, `--limit`, `--password-file`) keep their meaning. `--version` prints the version. | `mailvigil --help` and the [README](../README.md) |
| Exit codes | `0`, `1`, `2`, `3`, `4`, `70`, `130` and `141` keep their meaning. A new code is never reused for an old one. | [Exit codes](../README.md#exit-codes) |
| JSON | The two documents of `--json` follow `schema_version`: a field is only added inside a version, and renamed, removed or retyped only with a new one. | [json-schema.md](json-schema.md) |
| Configuration | The keys `domain` and `[senders]`, and the strict reading of the file: an unknown key is an error. | [Configuration](../README.md#configuration) |
| Safety of the input | A report is hostile input: the size cap, the refusal of `DOCTYPE` and `ENTITY`, and `fetch` reading a mailbox without changing it, over verified TLS, never take a weaker form. | [SECURITY.md](../SECURITY.md) |
| Python | The versions in `requires-python`. | `pyproject.toml` |

A new option, a new JSON field or a new configuration key is added in a minor version. A file that
uses a new key is refused by an older MailVigil.

## Not public

These can change in any version. When one changes in a way a user would notice, the
[CHANGELOG](../CHANGELOG.md) says so under "Changed".

- **The words.** Every sentence of the text output, in English and in Brazilian Portuguese, and
  the wording of the refusal lines, can be reworded. A script reads the exit code or `--json`, never
  the text.
- **The HTML page.** Its markup, its look and the order of its parts.
- **The thresholds of the verdict.** The five rules are the tool's judgment of "safe to move to
  `p=reject`", not a promise of fixed numbers. A threshold can change in a minor version; the
  numbers are in every `--json` verdict and in the text, so a script can read what applied.
- **The files `fetch` saves.** Their names are for the tool's own bookkeeping; what is promised
  is that each file is the original message, readable by `summary` and `verdict`.
- **The Python modules.** MailVigil is a command-line tool. `import mailvigil` is not an API and
  nothing in the package is public beyond `mailvigil.__version__`.

## Deprecation

When a command, an option, a configuration key or a JSON field has to go:

1. The CHANGELOG lists it under "Deprecated" in a minor version, with what to use instead, and it
   keeps working.
2. It is removed in the next major version, and the CHANGELOG lists it under "Removed".

A security fix may skip the first step when keeping the old behavior would keep the hole open. The
CHANGELOG says so under "Security".

The lowest supported Python rises only when that Python reaches end of life, in a minor version,
announced under "Removed".
