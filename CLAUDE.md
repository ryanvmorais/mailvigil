# CLAUDE.md

This file guides Claude Code (claude.ai/code) when working in this repository.

## Project overview

MailVigil is an open-source command-line tool that reads DMARC aggregate reports (RUA, usually
`.zip`, `.gz` or `.xml`) and says, in plain language, who is sending mail as a domain and whether
it is safe to move the policy to `p=reject`. Python `>=3.12`, standard library only (zero runtime
dependencies), offline. It is pre-0.1: the CLI only answers `mailvigil --version`, and the report
ingestion layer (`mailvigil.reports`), the configuration loader (`mailvigil.config`) and the sender
identification (`mailvigil.senders`) are built and tested but not wired to the CLI yet; everything
else is specified in [specs/](specs/) first. The repository has been public since
2026-10-27 (the maintainer made it public, not Claude); nothing is announced or published to PyPI
until the first version is ready.

Conversation with the maintainer (Ryan) and plan files are in Portuguese; everything in the
repository is English.

## Common commands

```bash
# Create/update the environment from pyproject.toml + uv.lock (includes the dev group)
uv sync

# Run the CLI from the source tree
uv run mailvigil --version

# Run the tests (one file, then one test)
uv run pytest
uv run pytest tests/test_smoke.py
uv run pytest tests/test_smoke.py::test_version_is_exposed

# The quality gate, in the same order as the pre-commit hook and the CI
uv run ruff check .
uv run black --check .
uv run mypy
uv run pytest --cov

# Format what you changed (the Claude hook does this on every edit)
uv run ruff check --fix . && uv run black .

# Activate the versioned pre-commit hook (once per clone)
git config core.hooksPath .githooks

# Build the sdist and wheel locally (the CI `package` job does the same)
uv build
```

## Environment variables

There are none. Configuration will be a TOML file passed to the CLI (see the specs); never commit a
local one (`mailvigil.local.toml` is ignored).

## Architecture

```text
src/mailvigil/
  __init__.py        # __version__ read from package metadata
  cli.py             # argparse entry point (`mailvigil = mailvigil.cli:main`)
  py.typed           # marks the package as typed (PEP 561)
  reports/           # report ingestion (spec 002); public API re-exported by __init__.py
    errors.py        #   Reason (StrEnum) and ReportRefused: every refusal is typed
    model.py         #   frozen dataclasses: Report, Record, PolicyPublished, IngestionResult…
    xmlsafe.py       #   the only XML parser: expat handlers refuse DOCTYPE and ENTITY
    reader.py        #   .xml/.gz/.zip to bytes, capped at MAX_BYTES (5 MiB) as it decompresses
    parser.py        #   XML tree to Report: sanitized text, strict numbers, IPs normalized
    discovery.py     #   paths (files and folders) to an ordered, deduplicated list of files
    ingest.py        #   ingest(paths, domain): the entry point; refusals go to `skipped`
  text.py            # text and domain rules shared by reports and config (clean_text, normalize_domain…)
  config.py          # load_config(path) → frozen Config (domain + selector map); ConfigError is typed (spec 003)
  senders.py         # identify_sender(record, config) → Identification; a selector counts only under the domain
tests/               # pytest, one test file per module (test_reports_*.py, test_text.py, test_config.py,
                     # test_senders.py); fixtures are synthetic, built in conftest.py or tmp_path
specs/               # spec-driven development: requirements → design → tasks per feature
docs/stack.md        # each technology of the stack, why it was chosen, what to study first
.githooks/           # versioned pre-commit hook (core.hooksPath)
.claude/             # Claude Code hooks: format on edit, validate at turn end, guard uv.lock
.github/             # CI, CodeQL, dependency review, weekly pip-audit, Dependabot, issue/PR templates
uv.lock              # never edit by hand (generated; a hook blocks it)
```

> ⚠️ **Zero runtime dependencies is the product promise** (offline, nothing to install but the
> tool). `dependencies = []` in `pyproject.toml`, and the CI `package` job fails if the wheel
> declares any `Requires-Dist`. Dev tools go in `[dependency-groups] dev`. Parsing uses the
> standard library only (`argparse`, `tomllib`, `xml.etree`, `xml.parsers.expat`, `zipfile`,
> `gzip`, `ipaddress`).

> ⚠️ **Reports are hostile input.** The parser refuses any XML containing `DOCTYPE` or `ENTITY`
> (entity expansion) inside `reports/xmlsafe.py`, and `reports/reader.py` caps the decompressed
> size at `MAX_BYTES` (5 MiB, against zip bombs) by counting the bytes actually read, never a
> declared size. Both defenses have tests that feed the attack; keep it so when touching them, and
> keep `xmlsafe.py` the only module that creates an XML parser. The starting point was the script in
> the maintainer's site repository (`site-ryan-morais/scripts/relatorios_dmarc.py`).

> ⚠️ **Never use a real DMARC report** in tests, docs, issues or PRs: it carries IP addresses and
> domains. Fixtures are synthetic. `*.xml.gz`, `*.xml.zip` and `reports/` are git-ignored except
> under `tests/`.

## Conventions

- **Language:** code, commits, branches, docstrings and docs in English (open source; rule from
  `/idioma`). User-facing CLI text: English and Portuguese (locale or `--lang`), decided in the
  specs.
- **File style:** follow `/estilo-arquivos` for each file type (docstrings with `Args:` /
  `Returns:`, full annotations, `# why` comments); do not copy its rules here.
- **Python floor:** 3.12, tested in CI together with the newest stable release. Ruff and black
  target `py312` and mypy runs with `python_version = "3.12"`, so syntax newer than the floor
  fails the lint. Review when 3.12 reaches end of life (2028-10-31).
- **Commits:** Conventional Commits (`feat`, `fix`, `docs`, `chore`, `ci`, `deps`…), squash-merged.

## Quality and automation

- **Gate:** `ruff` → `black --check` → `mypy` (strict, over `src`) → `pytest --cov`. The same
  sequence runs in `.githooks/pre-commit` and in `.github/workflows/ci.yml`. The repository allows
  squash merges only, and the `proteger-main` ruleset requires a pull request, linear history and
  the `Quality (Python 3.12)`, `Quality (Python 3.15)` and `Package` checks; `pip-audit`, CodeQL and
  dependency review are not required, so a new CVE cannot block the PR that fixes it.
- **Claude Code hooks** (`.claude/`, run with `python`): `project_format` (PostToolUse: ruff `--fix`
  + black on the edited `.py`), `validate` (Stop: ruff + mypy when a `.py` under `src/` or `tests/`
  changed; pytest is left to the pre-commit hook because it is heavy), `guard_generated`
  (PreToolUse: blocks editing `uv.lock`), `session_start` (warns about a missing `.venv` or an
  inactive `core.hooksPath`).
- **CI minutes:** free, because the repository is public. CI runs on pull requests, on pushes to
  `main` and by hand; CodeQL (as a workflow, not the default setup) on `main`, PRs and weekly;
  dependency review on PRs. Review the triggers if the repository ever goes private again.
- **Weekly `pip-audit.yml`** audits `uv.lock` every Monday 09:00 (São Paulo). A red run means a
  known CVE in the lock: answer with `/atualizar-dependencias`.

## Spec-driven workflow

Features are written down in `specs/NNN-name/` (`requirements.md` → `design.md` → `tasks.md`)
with a human approval gate between phases; use `/spec`. Flow per task: issue → branch → PR →
`/fechar-sessao`. Claude opens PRs and never merges. At the end of a session that changed
architecture, commands or the CLI, run `/atualizar-docs` and then `/fechar-sessao`.

## Dependencies

`uv` manages everything: `pyproject.toml` holds the floors (`>=`) and `uv.lock` the exact
versions. Commit both together (`uv lock --check` must pass). Dependabot (`uv` and
`github-actions`, Sundays, 7-day cooldown) opens the routine PRs; review them with
`/revisar-dependabot`.

> Publishing (PyPI, GitHub Releases, posts) is the maintainer's act, never Claude's. Claude
> prepares the package, the README and the CI. A vulnerability in a published version is reported
> privately (private vulnerability reporting), never in a public issue, PR or commit.
