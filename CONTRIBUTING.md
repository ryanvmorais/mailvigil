# Contributing to MailVigil

Thanks for your interest in improving MailVigil. By taking part you agree to follow the
[Code of Conduct](CODE_OF_CONDUCT.md).

MailVigil is pre-1.0: the interface will change until the first version is out, so open an issue
before starting anything large.

## Development

MailVigil is managed with [uv](https://docs.astral.sh/uv/). `uv sync` installs the project and the
`dev` dependency group, which pins the tooling (`ruff`, `black`, `mypy`, `pytest`, `pytest-cov`).
The package itself has **zero runtime dependencies** and must stay that way: it is the product
promise, and the CI fails if the built wheel declares one. Parsing uses the standard library only.

The setup and the quality gate commands are in the README's [Development](README.md#development)
section.

## Before opening a pull request

Run the full quality gate and make sure it is green: the pre-commit hook and the CI run the same
sequence. Activate the hook once per clone with `git config core.hooksPath .githooks`.

## Conventions

- **Language:** all code, comments, docstrings, commit messages and documentation are in English.
  See [CLAUDE.md](CLAUDE.md).
- **Commits:** [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`,
  `docs:`, `refactor:`, `test:`, `chore:`). Pull requests are squash-merged.
- **Issues and PRs:** a bug or a feature starts as an issue (forms in `.github/ISSUE_TEMPLATE/`);
  the PR that resolves it says `Closes #N`, so the issue closes on merge. A trivial fix can go
  straight to a PR.
- **Design changes:** non-trivial features are designed as specs under [specs/](specs/) before
  implementation (requirements, design, tasks).

## Never use a real DMARC report

A real report carries IP addresses and domains. Tests, docs, issues and pull requests use
**synthetic** reports only. The `.gitignore` ignores `*.xml`, `*.zip` and `*.gz` outside `tests/`
as a safety net, but check what you are adding.

## Claude Code hooks

The repository ships [Claude Code](https://claude.com/claude-code) hooks in `.claude/`. If you open
the project with Claude Code, they format the file you edit, run ruff and mypy at the end of a turn
and block edits to `uv.lock`. They only call the local tooling, with no network access. They are
optional: nothing else depends on them.

## Reporting security issues

Do not open public issues for vulnerabilities in MailVigil itself: see [SECURITY.md](SECURITY.md).
