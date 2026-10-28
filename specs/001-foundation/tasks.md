---
feature: Foundation — package skeleton, local quality gate, CI and supply-chain hygiene
status: in progress
date: 2026-10-27
related:
  - 001-foundation/requirements.md
  - 001-foundation/design.md
origin: conception
---

# 001 — Foundation — Tasks

The foundation was built from a checklist before this spec existed, so Stage 0 records what shipped
in pull request #1 (already checked) and Stages 1 and 2 are the work left to make the spec true.

## Stage 0 — Foundation as shipped (PR #1, squash `292a7ef`)

- [x] `pyproject.toml`, `.python-version`, `uv.lock`: metadata, `dependencies = []`, dev group,
  ruff/black/mypy/coverage/pytest configuration, Hatchling build. — RF-01, RF-04, RNF-01, ADR-1, ADR-2
- [x] `src/mailvigil/{__init__,cli,py.typed}`: `__version__` with fallback, `build_parser()`,
  `main(argv)`. — RF-01, RF-02
- [x] `tests/test_smoke.py`: version exposed, `--version`, no arguments (3 tests). — RF-10
- [x] `.gitignore`, `.gitattributes`: real reports ignored, LF endings. — RF-09, RNF-04
- [x] `.githooks/pre-commit` (mode 100755) and `core.hooksPath`. — RF-03, ADR-7
- [x] `.claude/settings.json` and the four hooks. — RF-07, RF-08, RNF-04
- [x] `.github/workflows/ci.yml`: `quality` (3.12, 3.15), `package`, `security`. — RF-03, RF-04,
  RF-05, RNF-02, ADR-5, ADR-6
- [x] `.github/workflows/pip-audit.yml` and `.github/dependabot.yml`. — RF-06, ADR-3, ADR-4
- [x] Quality gate. — green locally on Python 3.12.13 when merged; the workflows had not
  run on GitHub (Actions minutes exhausted)

## Stage 1 — Close the gaps found by the design

- [x] `tests/test_smoke.py`: add `test_unknown_flag_exits_two` — `main(["--nope"])` raises
  `SystemExit` with code `2`, and `capsys` shows the usage message on stderr and nothing on stdout.
  — RF-02, RF-10
- [x] `tests/test_smoke.py`: add `test_version_falls_back_without_install` — patch
  `importlib.metadata.version` to raise `PackageNotFoundError`, `importlib.reload(mailvigil)`, assert
  `__version__ == "0.0.0.dev0"`, and reload again in teardown (`monkeypatch` plus `finally`) so the
  other tests see the real value. — RF-01, RF-10
- [x] `.gitignore`: change `reports/` to `/reports/` so a synthetic `tests/reports/` is not hidden;
  confirm with `git check-ignore` that `reports/a.xml` is ignored and `tests/reports/a.xml` is not.
  Done with the pre-public security audit, which also ignores `*.xml`, `*.zip` and `*.gz` (Google
  sends reports as `.zip`) with `tests/` negations. — RF-09
- [x] Quality gate (`uv run ruff check .`, `uv run black --check .`, `uv run mypy`,
  `uv run pytest --cov`). — green locally on Python 3.12.13 on 2026-10-27: ruff and black clean,
  mypy no issues in 2 source files, 5 tests passed, 100% coverage

## Stage 2 — Acceptance on GitHub

Unblocked on 2026-10-27, when the repository became public (Actions minutes are free there; while
it was private the account's quota was exhausted and every job failed in 3 s). Nothing in this stage
changes code unless a job fails.

- [x] Confirm `Quality (Python 3.12)`, `Quality (Python 3.15)`, `Package` and `Security
  (pip-audit)` all run and pass. Done on PR #3 (rerun, run 40602354923): the four passed, so the
  pinned SHAs and the 3.15 leg work on GitHub. The Stage 1 pull request still has to be opened.
  — RF-03, RF-04, RF-05, RF-06, RNF-02
- [ ] Prove the `package` guard bites: on a throwaway branch add a runtime dependency to
  `[project].dependencies`, confirm the job fails with "MailVigil must stay dependency-free", then
  delete the branch (no PR merged). — RF-05, RNF-01
- [x] Trigger `Weekly pip-audit` with `workflow_dispatch` and confirm it passes. Done on
  2026-10-27: run 40602805245 passed in 15 s. — RF-06, ADR-4
- [ ] Confirm Dependabot is active (Insights → Dependency graph → Dependabot, or its first Sunday
  PRs) for `uv` and `github-actions`, with the 7-day cooldown and the grouping. The version-update
  runs for `uv` and `github-actions` already succeeded on 2026-10-27; the cooldown and the grouping
  show on the first Sunday PRs (2026-11-01). — RF-06, ADR-3
- [ ] Mark the spec `done`, update the roadmap row in `specs/README.md`, and record the first green
  run in "Resolved decisions" 6 of `requirements.md`. — RF-03 to RF-06
- [ ] Quality gate. — result recorded when run: ___ (the CI run URL)
