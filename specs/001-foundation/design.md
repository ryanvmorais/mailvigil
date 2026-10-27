---
feature: Foundation — package skeleton, local quality gate, CI and supply-chain hygiene
status: approved
date: 2026-10-27
related:
  - 001-foundation/requirements.md
origin: conception
---

# 001 — Foundation — design

## Overview

The foundation is three layers that share one definition of "ready". The **package** is a
standard-library-only Python distribution built with Hatchling. The **quality sequence** (`ruff →
black --check → mypy → pytest --cov`) is configured once in `pyproject.toml` and invoked in two
places that must stay identical: the versioned git pre-commit hook and the CI `quality` job. The
**supply chain** (locked graph, weekly Dependabot, weekly `pip-audit`, SHA-pinned Actions) keeps the
dependency-free promise honest over time. A fourth, smaller layer — the Claude Code hooks — moves
the same checks earlier: format on every edit, validate when a turn ends.

Nothing here has DMARC logic. The design goal is that later specs add modules under
`src/mailvigil/` and tests under `tests/` without touching any of this, and that a change to the
foundation is visible in the diff of exactly one of the files listed below.

## Module layout

```text
pyproject.toml                       # metadata, dev group, ruff/black/mypy/coverage/pytest config
uv.lock                              # exact graph (generated; never edited by hand)
.python-version                      # 3.12, the floor
.gitignore  .gitattributes           # real reports ignored; LF everywhere
src/mailvigil/
  __init__.py                        # __version__ from package metadata, with a dev fallback
  cli.py                             # build_parser() and main(argv) -> int
  py.typed                           # PEP 561 marker
tests/test_smoke.py                  # RF-10
.githooks/pre-commit                 # local gate (bash), activated by core.hooksPath
.claude/settings.json                # registers the four hooks
.claude/hooks/                       # session_start, guard_generated, project_format, validate
.github/workflows/ci.yml             # quality (3.12, 3.15), package, security
.github/workflows/pip-audit.yml      # weekly CVE audit of uv.lock
.github/dependabot.yml               # uv + github-actions, weekly, 7-day cooldown, grouped
.github/ISSUE_TEMPLATE/  pull_request_template.md   # real-report warnings (RF-09)
```

## Data model

None. The foundation holds no data. The one value it computes is `__version__: str`, read from
the installed distribution's metadata (`importlib.metadata.version("mailvigil")`) and falling back
to `"0.0.0.dev0"` on `PackageNotFoundError` (RF-01).

## Components

### Package and entry point (RF-01, RF-02)

`pyproject.toml` declares `dependencies = []`, `requires-python = ">=3.12"` and the console script
`mailvigil = "mailvigil.cli:main"`. `cli.build_parser()` returns an `argparse.ArgumentParser` with
`--version`; `cli.main(argv: Sequence[str] | None = None) -> int` parses and returns `0`. Taking
`argv` explicitly keeps the CLI testable without a subprocess. `argparse` already exits with `2`
and writes usage to standard error on an unknown flag, so that behaviour is inherited, not coded.

The wheel packages `src/mailvigil` only. The sdist is limited to `/src`, `README.md` and `LICENSE`:
tests, specs and CI stay in the repository.

### Quality sequence (RF-03, RF-04)

One configuration, two callers.

| Step | Command | Scope | Configured in |
|---|---|---|---|
| 1 | `ruff check .` | whole repo | `[tool.ruff]`, `target-version = "py312"` |
| 2 | `black --check .` | whole repo | `[tool.black]`, `target-version = ["py312"]` |
| 3 | `mypy` | `src` (strict) | `[tool.mypy]`, `python_version = "3.12"` |
| 4 | `pytest --cov` | `tests/` | `[tool.pytest.ini_options]`, `[tool.coverage.*]` |

`.githooks/pre-commit` runs the four in this order under `set -euo pipefail`, so the first failure
aborts the commit and the echoed `[pre-commit] <step>...` line before it names the step. The CI
`quality` job runs the same four as separate steps, over a matrix of `["3.12", "3.15"]`
(`fail-fast: false`, so a failure on one version does not hide the other). Because the lint, format
and type targets are the floor, syntax newer than 3.12 fails the lint on the newest interpreter too.

### Package verification (RF-05)

The `package` job, on Python 3.12: `uv build` (sdist and wheel) → `uvx twine check --strict
dist/*` → fail if `unzip -p dist/*.whl '*.dist-info/METADATA'` contains a line starting with
`Requires-Dist:` (emitting `::error::… MailVigil must stay dependency-free`) → create a clean venv,
install only the wheel, run `mailvigil --version`. This is the build a release would ship.

### Supply chain (RF-06, RNF-01)

- **Lock:** `uv lock --check` must pass; `pyproject.toml` holds the floors (`>=`), `uv.lock` the
  exact versions, committed together.
- **Dependabot:** ecosystems `uv` and `github-actions`, Sundays 09:00 America/Sao_Paulo, one grouped
  PR for minor and patch updates per ecosystem, `cooldown.default-days: 7`, label `dependencies`,
  commit prefixes `chore(deps)`, `chore(deps-dev)` and `chore(ci)`.
- **CVE audit:** the same three commands in `ci.yml` (`security` job, on pull requests) and in
  `pip-audit.yml` (cron `0 12 * * 1` = Monday 09:00 in São Paulo): `uv export --frozen
  --no-emit-project --no-hashes --all-groups --all-extras`, then `uvx --exclude-newer "7 days"
  pip-audit --requirement … --no-deps --disable-pip`. `--no-deps` makes it audit the lock's graph,
  not a fresh resolution.
- **Workflow hygiene:** every `uses:` is a full commit SHA with `# vX.Y.Z`; `runs-on:
  ubuntu-26.04`; top-level `permissions: contents: read`; `timeout-minutes: 10` on each job;
  `concurrency` with `cancel-in-progress` on `ci.yml`.

### Claude Code hooks (RF-07, RF-08, RNF-04)

Registered in `.claude/settings.json`, run with `python`, all using only the standard library.

| Hook | Event | Behaviour |
|---|---|---|
| `session_start` | SessionStart | Warns about a missing `.venv` or an inactive `core.hooksPath`; never blocks. |
| `guard_generated` | PreToolUse (`Edit\|Write`) | Exit `2` with guidance when the path ends in `uv.lock`. |
| `project_format` | PostToolUse (`Edit\|Write`) | On an existing `.py` file: `ruff check --fix`, then `black`. Always exits `0`. |
| `validate` | Stop | If a `.py` under `src/` or `tests/` changed (`git status`): `ruff check .` and `mypy`; exit `2` on failure. With `stop_hook_active` set, it warns and lets the stop through. |

All of them find the interpreter at `.venv/Scripts/python.exe` or `.venv/bin/python` and do nothing
when it is missing, so an environment problem never traps the agent. `pytest` is deliberately not
in `validate`: it is heavy and may be legitimately red mid-feature; it belongs to the pre-commit
hook and CI.

### Real reports stay out (RF-09)

`.gitignore` ignores `*.xml.gz`, `*.xml.zip` and `reports/`, with `!tests/**/*.xml.gz` and
`!tests/**/*.xml.zip` as the exception for synthetic samples. The bug-report form and the PR
template each carry a warning not to paste a real report.

## Interfaces

| Contract | Shape |
|---|---|
| `mailvigil --version` | stdout `mailvigil <version>\n`, exit `0` |
| `mailvigil` (no args) | no output, exit `0` (placeholder until spec 002+) |
| `mailvigil --unknown` | usage and error on stderr, exit `2` |
| `mailvigil.__version__` | `str`; `"0.0.0.dev0"` outside an install |
| `mailvigil.cli.main(argv)` | `Sequence[str] \| None -> int`; `None` reads `sys.argv` |
| Hook input (Claude Code) | JSON on stdin; `tool_input.file_path` for edit hooks, `stop_hook_active` for Stop |
| Hook output | exit `2` + message on stderr blocks; exit `0` allows |

`--version` and the exit codes become public contract at the first release; the no-argument
behaviour does not, and spec 002 replaces it.

## ADRs

### ADR-1 — Python floor 3.12, tested against the newest stable

**Decision.** `requires-python = ">=3.12"`; lint, format and type targets pinned to 3.12; the CI
matrix is `["3.12", "3.15"]`.
**Alternatives.** (a) Floor at the newest stable only. (b) Test every minor in between (3.12 to
3.15).
**Why.** A tool for people running DMARC on their own infrastructure should install on the
Python they already have. Testing the two ends catches both "uses newer syntax" (lint on the floor)
and "breaks on the newest" (matrix); nothing in the standard-library-only surface makes the middle
versions likely to behave differently.
**Trade-off.** A 3.13 or 3.14 regression could slip through. Accepted; revisit if a bug report
shows one. Review the floor when 3.12 reaches end of life (2028-10-31). (RF-04)

### ADR-2 — Hatchling as the build backend

**Decision.** `[build-system] requires = ["hatchling"]`, wheel from `src/mailvigil`.
**Alternatives.** (a) `uv_build`. (b) `setuptools`. (c) Flit.
**Why.** Same backend as WebVigil, so one packaging model across the maintainer's projects, and
the explicit `include` list for the sdist is a one-block config. The build backend is not a
runtime dependency.
**Trade-off.** One more build-time package to keep current; it is covered by the lock and the
weekly audit. (RF-01, RF-05)

### ADR-3 — Dependabot ecosystem `uv`, not `pip`

**Decision.** `package-ecosystem: "uv"`.
**Alternatives.** `pip`.
**Why.** Only the `uv` ecosystem reads `uv.lock`; `pip` would look for `requirements*.txt` that
do not exist and propose nothing.
**Trade-off.** Depends on GitHub's `uv` support staying healthy. The weekly `pip-audit` is the
safety net if Dependabot silently stops opening PRs. (RF-06)

### ADR-4 — A separate weekly `pip-audit` workflow besides the CI job

**Decision.** `pip-audit` runs in `ci.yml` (on pull requests) and in `pip-audit.yml` (weekly).
**Alternatives.** (a) CI job only. (b) Rely on Dependabot security alerts.
**Why.** CI only runs on pull requests, so a CVE published after the last PR would go unnoticed;
and Dependabot has been seen to skip a fix PR without any warning. A red weekly run is the signal.
**Trade-off.** Duplicated three-line recipe in two files, kept in sync by hand. Cheap enough, and
the weekly run costs under a minute. (RF-06)

### ADR-5 — Actions pinned by SHA; `setup-uv` at v10.3.0

**Decision.** Pin `actions/checkout` and `astral-sh/setup-uv` by full SHA with the version in a
comment; use `setup-uv` v10.3.0 although v10.3.2 exists.
**Alternatives.** (a) Pin by tag (`@v10`). (b) Take the newest release.
**Why.** A tag can be moved after publication, a SHA cannot. v10.3.2 was five days old at
adoption, inside the project's own 7-day cooldown; Dependabot raises it once it clears.
**Trade-off.** The comment and SHA must move together (Dependabot does it). (RF-06)

### ADR-6 — CI on pull requests and by hand only

**Decision.** `on: pull_request` and `workflow_dispatch`; no trigger on pushes to `main`.
**Alternatives.** Also run on push to `main`.
**Why.** The repository is private on the Free plan: 2,000 minutes a month and a US$ 0 budget,
so CI stops when the minutes run out. A PR already ran the same commit before the squash.
**Trade-off.** A direct push to `main` is not checked; there is no branch protection on this plan
either, so the pre-commit hook and discipline carry that gap. Re-decide when the repository goes
public (RNF-02).

### ADR-7 — The pre-commit hook checks, it does not fix

**Decision.** The hook uses `ruff check` and `black --check`; formatting happens at edit time
through the Claude hook or the editor.
**Alternatives.** Auto-fix in the hook and re-stage.
**Why.** A hook that edits files behind a commit makes the committed tree differ from what the
author reviewed and complicates partial staging.
**Trade-off.** A contributor without the editor integration sees a failure and runs `uv run ruff
check --fix . && uv run black .` by hand; the failure message and `CLAUDE.md` give the command.
(RF-03)

### ADR-8 — mypy strict over `src` only

**Decision.** `files = ["src"]`, `strict = true`.
**Alternatives.** Also type-check `tests/`.
**Why.** The shipped package is the contract; tests are exercised by running them. This keeps
test code free of annotation noise for pytest fixtures.
**Trade-off.** A type error inside a test is not caught statically. Test functions are still
annotated by convention. (RF-03)

## Impact on existing code

The foundation already exists; this spec formalises it. Three gaps found while writing the design
(2026-10-27) are closed by the tasks, not by new design:

1. **RF-10 is not fully covered.** `tests/test_smoke.py` has three tests (version exposed,
   `--version`, no arguments). Missing: the unknown-flag exit `2`, and the `__version__` fallback
   when the distribution is not installed.
2. **RF-09's ignore rule is wider than the requirement.** `reports/` also matches `tests/reports/`
   (verified with `git check-ignore`), which would silently hide a synthetic fixture folder of that
   name. Anchoring it as `/reports/` limits it to the repository root.
3. **RF-03/RF-05/RF-06 are unverified on GitHub.** The workflows parse and their steps pass locally
   (Resolved decision 6), but the first green CI run has not happened yet because the account's
   Actions minutes ran out. That run is the acceptance test.

No public interface changes; nothing needs migration.

## Test strategy

- **Unit:** `tests/test_smoke.py`, calling `main(argv)` and asserting on `capsys` and
  `SystemExit.code`. No subprocess, no network, no files. The `__version__` fallback is tested by
  making `importlib.metadata.version` raise `PackageNotFoundError` and reloading the module
  (`monkeypatch` and `importlib.reload`).
- **Local, not unit-testable:** the workflows and hooks are verified by running their steps by hand
  (`uv build`, `twine check`, clean-venv install, `pip-audit`, YAML parse, SHA-pin check, the hooks
  fed JSON on stdin).
- **Acceptance:** the first green CI run on a pull request — `quality` on both Pythons, `package`
  and `security` — covers RF-03 to RF-06 end to end.
- **Real reports are never fixtures** (RF-09): when a later spec needs one, it is built in the test
  or committed as a small synthetic file under `tests/`.
