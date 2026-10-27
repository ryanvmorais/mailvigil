---
feature: Foundation — package skeleton, local quality gate, CI and supply-chain hygiene
status: approved
date: 2026-10-27
related: []
origin: conception
---

# 001 — Foundation

## Context and problem

MailVigil will be an open-source, offline command-line tool that reads DMARC aggregate reports
and says whether it is safe to move a domain's policy to `p=reject`. Before any of that exists,
every later spec needs the same ground to stand on: a package that installs, a single quality
sequence that means the same thing on a laptop and in CI, and a pipeline that keeps the
dependency-free promise honest.

Today (2026-10-27) the repository holds that ground in its first form: a `src/mailvigil` package
with a `--version` entry point and a smoke test, the `ruff → black → mypy → pytest` configuration
in `pyproject.toml`, a versioned pre-commit hook, Claude Code hooks, a CI workflow, a weekly
`pip-audit` workflow and Dependabot. It was built from a checklist and has never been written down
as a contract, and the CI has not run on GitHub yet (the Free plan's Actions minutes ran out
before the first pull request). This spec states what the foundation guarantees, so that later
specs can rely on it and a change to it is a deliberate one.

The repository is private on the Free plan: no branch protection, 2,000 Actions minutes a month
and a US$ 0 budget (CI stops when the minutes run out). That shapes several requirements.

## Goals

- A **zero-dependency, typed package** that installs from a wheel and runs `mailvigil --version`.
- **One quality sequence** (ruff, black, mypy strict, pytest with coverage) that runs identically
  as a git pre-commit hook and in CI.
- A **tested Python floor**: the lowest supported version and the newest stable release both run
  the full sequence.
- A **package check** in CI that proves the wheel is what a release would ship, including that it
  declares no runtime dependency.
- **Dependency and supply-chain hygiene**: a locked graph, weekly update PRs, a weekly CVE audit,
  and CI actions pinned by commit SHA.
- **Guard rails for the maintainer and for Claude Code**: the lock file cannot be hand-edited,
  edited Python is formatted, and lint or type errors are caught before a turn ends.

## Non-goals

- Any DMARC logic (reading reports, classifying senders, the verdict, output formats):
  specs `002` to `006`.
- Publishing: PyPI, GitHub Releases, the release workflow, trusted publishing. Publishing is the
  maintainer's act and belongs to the release preparation, not to this spec.
- Community files and the public-facing security baseline (`SECURITY.md`, `CONTRIBUTING.md`,
  `CODE_OF_CONDUCT.md`, private vulnerability reporting, a branch ruleset, CodeQL): they are
  created when the repository becomes public.
- Docker images, a web interface, or any hosted service.
- A `CHANGELOG.md` (only worth having once someone outside pins a version).

## Personas

- As the **maintainer**, I want a local gate and a CI that agree, so that a green check means the
  same as a clean checkout and a broken change never reaches `main`.
- As a **contributor**, I want one documented command sequence and a hook that runs it, so that I
  can tell whether my change is ready without reading the CI configuration.
- As a **user**, I want to install a single small wheel with nothing else pulled in, so that I can
  run the tool on a machine with no network and no build tools.

## Functional requirements

### RF-01 — Installable, typed, dependency-free package

- **Given** a clean environment
  **When** the built wheel is installed
  **Then** the `mailvigil` command exists, `mailvigil --version` prints `mailvigil <version>` on
  standard output and exits with `0`.
- **Given** the built wheel
  **When** its metadata is inspected
  **Then** it contains no `Requires-Dist` line, and the package ships `py.typed`.
- **Given** a source tree without an installed package
  **When** `mailvigil.__version__` is read
  **Then** it falls back to a development version instead of raising.

### RF-02 — Testable command-line entry point

- **Given** the entry point `mailvigil.cli.main`
  **When** it is called with an explicit `argv` list and no arguments
  **Then** it returns `0` without reading `sys.argv`.
- **Given** an unknown flag
  **When** `main` runs
  **Then** the process exits with code `2` and the usage message goes to standard error.

### RF-03 — One quality sequence

- **Given** the project configuration in `pyproject.toml`
  **When** the sequence runs
  **Then** it executes, in this order: `ruff check .`, `black --check .`, `mypy` (strict, over
  `src`), `pytest --cov`, and the first failing step stops it with a non-zero exit code.
- **Given** a staged change that fails any step
  **When** `git commit` runs with `core.hooksPath` set to `.githooks`
  **Then** the pre-commit hook aborts the commit and prints which step failed.
- **Given** the same commit
  **When** the CI `quality` job runs it
  **Then** it runs the same four steps in the same order.

### RF-04 — Tested Python floor

- **Given** `requires-python = ">=3.12"`
  **When** the CI `quality` job runs
  **Then** its matrix covers Python 3.12 and the newest stable release, and both must pass.
- **Given** syntax newer than Python 3.12
  **When** ruff, black or mypy runs
  **Then** it fails, because their targets are set to the floor (`py312`, `python_version =
  "3.12"`).
- **Given** a developer clone
  **When** `.python-version` is read
  **Then** it names the floor (`3.12`).

### RF-05 — Package verification in CI

- **Given** a pull request
  **When** the CI `package` job runs
  **Then** it builds the sdist and the wheel, `twine check --strict` passes on both, the wheel
  declares no runtime dependency, and the wheel installs in a clean environment where
  `mailvigil --version` runs.
- **Given** a change that adds a runtime dependency by accident
  **When** the `package` job runs
  **Then** it fails with a message saying MailVigil must stay dependency-free.

### RF-06 — Dependency and supply-chain hygiene

- **Given** `uv.lock`
  **When** `uv lock --check` runs
  **Then** it passes: manifest and lock are committed together and aligned.
- **Given** the repository on GitHub
  **When** a week passes
  **Then** Dependabot has looked at `uv` and `github-actions`, grouping minor and patch updates,
  waiting 7 days after a release before proposing it.
- **Given** the lock
  **When** the weekly `pip-audit` workflow (Mondays, 09:00 in São Paulo) or the CI `security` job
  runs
  **Then** it audits the whole locked graph, and a known vulnerability makes the run fail.
- **Given** any workflow file
  **When** it is read
  **Then** every `uses:` is pinned to a full commit SHA with the version in a comment, the runner
  is `ubuntu-26.04` (never `ubuntu-latest`), and permissions are `contents: read`.

### RF-07 — Generated files are protected

- **Given** a Claude Code session in this repository
  **When** an edit or write targets `uv.lock`
  **Then** the `guard_generated` hook exits with code `2` and says to use `uv lock`, `uv add` or
  `uv remove`.

### RF-08 — Edited Python is formatted and validated

- **Given** an edited or written `.py` file and an existing `.venv`
  **When** the edit finishes
  **Then** `ruff check --fix` and `black` have been applied to that file.
- **Given** a turn that changed a `.py` file under `src/` or `tests/`
  **When** the turn ends
  **Then** ruff and mypy run over the project, and a failure exits with `2` so the agent fixes it
  (a second failure in the same turn lets the stop through, to avoid an infinite loop).
- **Given** no `.venv`, or no changed Python file
  **When** any of these hooks runs
  **Then** it does nothing and does not block.

### RF-09 — Real reports never enter the repository

- **Given** a real DMARC report file (`*.xml.gz`, `*.xml.zip`, or anything under `reports/`)
  **When** `git status` runs
  **Then** it is ignored, except for synthetic samples under `tests/`.
- **Given** a bug-report form or a pull-request template
  **When** it is opened
  **Then** it warns against pasting a real report.

### RF-10 — Smoke tests

- **Given** the test suite
  **When** it runs
  **Then** it covers the version string, `--version` output and exit code, a call with no
  arguments, and an unknown flag, using `main(argv)` and `capsys` and no subprocess.

## Non-functional requirements

### RNF-01 — Zero runtime dependencies

- **Given** the project at any commit
  **When** `[project].dependencies` is read
  **Then** it is empty. Development tooling lives in `[dependency-groups] dev` only.

### RNF-02 — CI fits the Free plan

- **Given** the repository is private on the Free plan
  **When** CI triggers are read
  **Then** they are `pull_request` and `workflow_dispatch` only (never a push to `main`), every job
  has `timeout-minutes`, and a new push to the same pull request cancels the obsolete run.
- **Given** the repository becomes public
  **When** the triggers are reviewed
  **Then** the decision to also run on pushes to `main` is made then, not before.

### RNF-03 — Least privilege and no secrets

- **Given** the repository
  **When** it is searched for credentials
  **Then** there are none: no token, no `.env`, no key. The workflows need none.

### RNF-04 — Works on Windows and Linux

- **Given** a Windows clone with `autocrlf` and a Linux CI runner
  **When** the hooks and workflows run
  **Then** line endings are LF in the repository (`.gitattributes`) and the Claude hooks find the
  `.venv` interpreter in `Scripts/` or `bin/`.

## Open questions

1. When the repository becomes public, should the pre-commit hook stay the second gate next to a
   `proteger-main` ruleset that requires the `quality` jobs? (Decided at the public flip.)

## Resolved decisions

1. **Python floor `3.12`**, so anyone still on it can install the tool; reviewed when 3.12 reaches
   end of life (2028-10-31). The CI matrix is the floor plus the newest stable (3.15 today), not
   every version in between.
2. **Build backend: Hatchling**, the same as WebVigil.
3. **Dependabot ecosystem `uv`**, not `pip`, because only `uv` reads `uv.lock`.
4. **`astral-sh/setup-uv` pinned to v10.3.0** at the start: v10.3.2 was inside the 7-day cooldown.
5. **CI on pull requests and by hand only**, because of the Free plan's minute budget.
6. **The first CI run is the acceptance test of RF-03 to RF-06.** Until the workflows pass on
   GitHub, those requirements are verified only by running the same steps locally.

## Tests

The suite for this spec is the smoke suite of RF-10. The workflows themselves cannot be unit
tested; they are verified by running their steps locally (build, `twine check`, clean install,
`pip-audit`, YAML parse, SHA pinning check) and by the first green CI run.
