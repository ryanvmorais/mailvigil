# CLAUDE.md

This file guides Claude Code (claude.ai/code) when working in this repository.

## Project overview

MailVigil is an open-source command-line tool that reads DMARC aggregate reports (RUA, usually
`.zip`, `.gz` or `.xml`, or still attached to the mail in an `.eml` or `.mbox`) and says, in plain
language, who is sending mail as a domain and whether it is safe to move the policy to `p=reject`. Python `>=3.12`, standard library only (zero runtime
dependencies), offline. Version 1.7.0 is on PyPI (1.0.0 on 2026-10-29, 1.1.0 to 1.5.0 on 2026-10-30, 1.6.0 and 1.7.0 on 2026-10-31; `v0.1` to `v0.9` are the milestones of the build, see the README): the CLI answers `mailvigil --version`, `mailvigil summary`
and `mailvigil verdict` (report ingestion, configuration, sender identification, the summary, the
verdict on `p=reject` and their texts are built and wired); `--json`, `--lang en|pt-BR` and the stable
exit codes (a public contract, `docs/json-schema.md`) are built (spec 006 is done), and so is the
static HTML page of `verdict --html` (spec 008 is done). `mailvigil fetch` (spec 009, IMAP into a
folder, opt-in) is built too; it is the only command that touches the network. Several domains in
one run (spec 010) are built. Everything
is specified in [specs/](specs/) first. The repository has been public since
2026-10-27; releasing and announcing are the maintainer's acts.

Everything in the repository is English, except `README.pt-BR.md` (see Conventions).

## Common commands

```bash
# Create/update the environment from pyproject.toml + uv.lock (includes the dev group)
uv sync

# Run the CLI from the source tree
uv run mailvigil --version
uv run mailvigil summary --domain example.com path/to/reports   # or --config FILE
uv run mailvigil verdict --domain example.com path/to/reports   # exit 0 ready, 3 too early, 4 not ready
uv run mailvigil verdict --config FILE path/to/reports --json   # one JSON document, same exit code
uv run mailvigil summary --config FILE path/to/reports --json --top 20   # the 20 worst of each list, and `top` says what was left out
uv run mailvigil summary --config FILE path/to/reports --lang pt-BR   # the text in Portuguese
uv run mailvigil verdict --config FILE path/to/reports --html > report.html   # one static page (spec 008)
uv run mailvigil verdict --config FILE path/to/reports --html --output report.html   # the same, written as ASCII by the tool
uv run mailvigil fetch --host HOST --user NAME --to DIR   # saves the report mail as .eml (spec 009); asks for the password
uv run mailvigil fetch --config FILE --to DIR   # host, user, port and folder from the [fetch] table of the file

# Run the tests (one file, then one test)
uv run pytest
uv run pytest tests/test_smoke.py
uv run pytest tests/test_smoke.py::test_version_is_exposed

# The quality gate, in the same order as the pre-commit hook and the CI
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest --cov

# Format what you changed (the Claude hook does this on every edit)
uv run ruff check --fix . && uv run ruff format .

# Activate the versioned pre-commit hook (once per clone)
git config core.hooksPath .githooks

# Build the sdist and wheel locally (the CI `package` job does the same)
uv build
```

## Environment variables

There are none. Configuration is a TOML file passed to the CLI with `--config` (see the README);
never commit a local one (`mailvigil.local.toml` is ignored).

## Architecture

The package is layered, and the data flows in this order: `reports/` (ingestion of hostile input),
`text.py` and `config.py` (shared text rules, the TOML file), `senders.py` (who sent the mail),
`summary.py` (the figures), `verdict.py` (the judgment on `p=reject`), the renderers (`render.py`,
`render_verdict.py`, `render_json.py`, `render_html.py` over `htmlkit.py`, `render_fetch.py`) with
every sentence in `messages/`, and `cli.py` / `cli_fetch.py` wiring the commands. `fetch/` is the
only code that reaches the network. The module tree, with a comment per file, is in
[docs/referencia/architecture.md](docs/referencia/architecture.md).

```text
src/mailvigil/   # the package
tests/           # pytest, one file per module; fixtures are synthetic (conftest.py and helpers)
specs/           # spec-driven development: requirements → design → tasks per feature
docs/            # stack.md, json-schema.md, stability.md, referencia/, demo/, images/
scripts/         # benchmark_ingest.py: times the reading of synthetic reports (not a test)
.githooks/       # versioned pre-commit hook (core.hooksPath)
.claude/         # Claude Code hooks: format on edit, validate at turn end, guard uv.lock
.github/         # CI, CodeQL, dependency review, weekly pip-audit, release, Dependabot, templates
CHANGELOG.md     # Keep a Changelog; a change a user would notice goes in [Unreleased] in the same PR
uv.lock          # never edit by hand (generated; a hook blocks it)
```

### Before you touch…

| You are changing | Read first |
|---|---|
| `reports/` (readers, XML, mail) | specs `002` and `007`, and the hostile-input line below |
| `config.py`, `senders.py` | spec `003` (ADR-8: what may name a sender) |
| `summary.py`, `verdict.py` | specs `004` and `005`; the thresholds live in `verdict.py` only |
| `render_json.py`, exit codes | [docs/json-schema.md](docs/json-schema.md), [docs/stability.md](docs/stability.md), spec `006` |
| `messages/` | spec `006` (ADR-9: accents and ASCII folding) |
| `htmlkit.py`, `render_html.py`, `html_*` | spec `008` and the markup line below |
| `fetch/`, `cli_fetch.py` | spec `009` (ADR-2, ADR-3, ADR-10) and the network line below |
| several domains in one run | spec `010` |

### Do not regress

Each line is the short form of a section of [docs/referencia/invariants.md](docs/referencia/invariants.md).

- ⚠️ **Zero runtime dependencies** is the product promise: `dependencies = []`, and the CI `package` job fails if the wheel declares one ([why](docs/referencia/invariants.md#zero-runtime-dependencies)).
- ⚠️ **The one-domain path is the loop of one**: its text, `--json` and `--html` stay byte for byte as they were ([more](docs/referencia/invariants.md#the-one-domain-path-is-the-loop-of-one)).
- ⚠️ **Markup is built in `htmlkit.py` only**; the page has no script, no network and no `url()` ([more](docs/referencia/invariants.md#markup-is-built-in-htmlkitpy-only)).
- ⚠️ **`imaplib` and `ssl` are imported in `fetch/imap.py` only**, loaded inside `run_fetch`; the TLS context always verifies, the mailbox is only read, the password is never an argument or a log line ([more](docs/referencia/invariants.md#imaplib-and-ssl-are-imported-in-fetchimappy-only)).
- ⚠️ **Reports are hostile input**: no `DOCTYPE`/`ENTITY`, a 5 MiB cap counted as bytes are read, bounded depth and elements; `xmlsafe.py` is the only module that creates an XML parser ([more](docs/referencia/invariants.md#reports-are-hostile-input)).
- ⚠️ **Never use a real DMARC report** in tests, docs, issues or PRs; fixtures are synthetic ([more](docs/referencia/invariants.md#never-use-a-real-dmarc-report)).


## Conventions

- **Language:** code, commits, branches, docstrings and docs in English (open source). User-facing CLI text:
  English (default) and Brazilian Portuguese, chosen only by `--lang` (no locale detection). English is ASCII; Portuguese has accents on a stream that carries
  them and the same text folded to ASCII otherwise (spec 006 ADR-9). The one documentation
  exception is `README.pt-BR.md`, the Portuguese README for the Brazilian audience (a user-facing
  text, so the product's audience language): keep it in step with `README.md`, whose headings
  `tests/test_readme_pt_br.py` compares.
- **File style:** follow the file you are editing: docstrings with `Args:` / `Returns:`, full
  annotations and `# why` comments.
- **Python floor:** 3.12, tested in CI together with 3.13, 3.14 and the newest stable release (3.15), on Linux and
  on Windows (the one runner outside the `ubuntu-26.04` rule, so "OS Independent" is tested). Ruff (lint and
  format) targets `py312` and mypy runs with `python_version = "3.12"`, so syntax newer than the floor
  fails the lint. Review when 3.12 reaches end of life (2028-10-31).
- **Commits:** Conventional Commits (`feat`, `fix`, `docs`, `chore`, `ci`, `deps`…), squash-merged.

## Quality and automation

- **Gate:** `ruff check` → `ruff format --check` → `mypy` (strict, over `src`) → `pytest --cov`. The same
  sequence runs in `.githooks/pre-commit` and in `.github/workflows/ci.yml`. The repository allows
  squash merges only, and the `proteger-main` ruleset requires a pull request, linear history and
  the `Quality (Python 3.12)`, `Quality (Python 3.15)` and `Package` checks; `pip-audit`, CodeQL and
  dependency review are not required, so a new CVE cannot block the PR that fixes it.
- **Claude Code hooks** (`.claude/`, run with `python`): `project_format` (PostToolUse: ruff `--fix`
  + `ruff format` on the edited `.py`), `validate` (Stop: ruff + mypy when a `.py` under `src/` or `tests/`
  changed; pytest is left to the pre-commit hook because it is heavy), `guard_generated`
  (PreToolUse: blocks editing `uv.lock`), `session_start` (warns about a missing `.venv` or an
  inactive `core.hooksPath`).
- **CI minutes:** free, because the repository is public. CI runs on pull requests, on pushes to
  `main` and by hand; CodeQL (as a workflow, not the default setup) on `main`, PRs and weekly;
  dependency review on PRs. Review the triggers if the repository ever goes private again.
- **Weekly `pip-audit.yml`** audits `uv.lock` every Monday 09:00 (São Paulo). A red run means a
  known CVE in the lock: update the locked version of the affected dependency.

## Spec-driven workflow

Features are written down in `specs/NNN-name/` (`requirements.md` → `design.md` → `tasks.md`)
with a human approval gate between phases (see `specs/README.md`). Flow per task: issue → branch →
PR. A change to the architecture, the commands or the CLI updates the README, this file and
`docs/stack.md` in the same PR.

**A feature with an interface** (the HTML report, spec 008, was the first) needs a mockup approved
before any code (two or three alternatives checked at 390 and 1280 px, one recommended), and no
interface file is written until the maintainer approves one. The 008 choice is recorded in
`specs/README.md`.

## Dependencies

`uv` manages everything: `pyproject.toml` holds the floors (`>=`) and `uv.lock` the exact
versions. Commit both together (`uv lock --check` must pass). Dependabot (`uv` and
`github-actions`, Sundays, 7-day cooldown) opens the routine PRs.

> Publishing (PyPI, GitHub Releases) is the maintainer's act. A vulnerability in a published
> version is reported privately (private vulnerability reporting), never in a public issue, PR or
> commit.
