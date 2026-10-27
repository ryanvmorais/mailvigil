# CLAUDE.md

This file guides Claude Code (claude.ai/code) when working in this repository.

## Project overview

MailVigil is an open-source command-line tool that reads DMARC aggregate reports (RUA, usually
`.zip`, `.gz` or `.xml`) and says, in plain language, who is sending mail as a domain and whether
it is safe to move the policy to `p=reject`. Python `>=3.12`, standard library only (zero runtime
dependencies), offline. It is pre-0.1: only the package skeleton and `mailvigil --version` exist;
everything else is specified in [specs/](specs/) first. The repository is private until the
first version is ready (the maintainer makes it public, not Claude).

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
tests/               # pytest; reports used as fixtures are synthetic
specs/               # spec-driven development: requirements → design → tasks per feature
docs/stack.md        # each technology of the stack, why it was chosen, what to study first
.githooks/           # versioned pre-commit hook (core.hooksPath)
.claude/             # Claude Code hooks: format on edit, validate at turn end, guard uv.lock
.github/             # CI, weekly pip-audit, Dependabot, issue and PR templates
uv.lock              # never edit by hand (generated; a hook blocks it)
```

> ⚠️ **Zero runtime dependencies is the product promise** (offline, nothing to install but the
> tool). `dependencies = []` in `pyproject.toml`, and the CI `package` job fails if the wheel
> declares any `Requires-Dist`. Dev tools go in `[dependency-groups] dev`. Parsing uses the
> standard library only (`argparse`, `tomllib`, `xml.etree`, `zipfile`, `gzip`).

> ⚠️ **Reports are hostile input.** The parser must refuse any XML containing `DOCTYPE` or
> `ENTITY` (entity expansion) and cap decompressed size (5 MiB per member, against zip bombs),
> and both defenses need tests. The starting point is the script in the maintainer's site
> repository (`site-ryan-morais/scripts/relatorios_dmarc.py`).

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
  sequence runs in `.githooks/pre-commit` and in `.github/workflows/ci.yml`. The repository is
  private on the Free plan (no branch protection), so the hook and a green CI are the real gate.
- **Claude Code hooks** (`.claude/`, run with `python`): `project_format` (PostToolUse: ruff `--fix`
  + black on the edited `.py`), `validate` (Stop: ruff + mypy when a `.py` under `src/` or `tests/`
  changed; pytest is left to the pre-commit hook because it is heavy), `guard_generated`
  (PreToolUse: blocks editing `uv.lock`), `session_start` (warns about a missing `.venv` or an
  inactive `core.hooksPath`).
- **CI minutes:** private + Free plan = 2,000 min/month and a US$ 0 budget, so CI stops when it
  runs out. CI runs on pull requests and by hand only. Review the triggers when the repository
  becomes public.
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
