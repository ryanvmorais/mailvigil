# CLAUDE.md

This file guides Claude Code (claude.ai/code) when working in this repository.

## Project overview

MailVigil is an open-source command-line tool that reads DMARC aggregate reports (RUA, usually
`.zip`, `.gz` or `.xml`, or still attached to the mail in an `.eml` or `.mbox`) and says, in plain
language, who is sending mail as a domain and whether it is safe to move the policy to `p=reject`. Python `>=3.12`, standard library only (zero runtime
dependencies), offline. Version 1.0.0 is on PyPI (published by the maintainer on 2026-10-29; `v0.1` to `v0.9` are the milestones of the build, see the README): the CLI answers `mailvigil --version`, `mailvigil summary`
and `mailvigil verdict` (report ingestion, configuration, sender identification, the summary, the
verdict on `p=reject` and their texts are built and wired); `--json`, `--lang en|pt-BR` and the stable
exit codes (a public contract, `docs/json-schema.md`) are built (spec 006 is done), and so is the
static HTML page of `verdict --html` (spec 008 is done). `mailvigil fetch` (spec 009, IMAP into a
folder, opt-in) is built too; it is the only command that touches the network. Everything
is specified in [specs/](specs/) first. The repository has been public since
2026-10-27 (the maintainer made it public, not Claude); releasing and announcing are the
maintainer's acts (`docs/releasing.md`).

Conversation with the maintainer (Ryan) and plan files are in Portuguese; everything in the
repository is English.

## Common commands

```bash
# Create/update the environment from pyproject.toml + uv.lock (includes the dev group)
uv sync

# Run the CLI from the source tree
uv run mailvigil --version
uv run mailvigil summary --domain example.com path/to/reports   # or --config FILE
uv run mailvigil verdict --domain example.com path/to/reports   # exit 0 ready, 3 too early, 4 not ready
uv run mailvigil verdict --config FILE path/to/reports --json   # one JSON document, same exit code
uv run mailvigil summary --config FILE path/to/reports --lang pt-BR   # the text in Portuguese
uv run mailvigil verdict --config FILE path/to/reports --html > report.html   # one static page (spec 008)
uv run mailvigil verdict --config FILE path/to/reports --html --output report.html   # the same, written as ASCII by the tool
uv run mailvigil fetch --host HOST --user NAME --to DIR   # saves the report mail as .eml (spec 009); asks for the password

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
  cli.py             # argparse entry point (`mailvigil = mailvigil.cli:main`): `--version`, `summary`
                     # (resolve_config, ingest → summarize → render, exit 0/1/2) and `verdict` (same
                     # load, then judge → render_verdict; exit 0 ready, 3 too early, 4 not ready);
                     # the exit code is decided before the format; a parent parser shares
                     # paths/--config/--domain/--json/--lang (`--lang` is parsed to a Messages);
                     # `--html` exists on `verdict` only and is refused together with `--json`;
                     # `--output FILE` (ADR-11) needs `--html` and `_write_page` writes it atomically;
                     # `fetch` (spec 009) takes only `--lang` from the parents and loads
                     # `fetch.imap` (imaplib, ssl) inside `_run_fetch`, never at import
  py.typed           # marks the package as typed (PEP 561)
  reports/           # report ingestion (spec 002); public API re-exported by __init__.py
    errors.py        #   Reason (StrEnum) and ReportRefused: every refusal is typed
    model.py         #   frozen dataclasses: Report, Record, PolicyPublished, IngestionResult…
    xmlsafe.py       #   the only XML parser: expat handlers refuse DOCTYPE and ENTITY
    reader.py        #   .xml/.gz/.zip to bytes, capped at MAX_BYTES (5 MiB) as it decompresses
    mail.py          #   .eml/.mbox (spec 007): report attachments out of messages, bounded in size,
                     #   lines, parts and depth before and while the `email` parser works
    parser.py        #   XML tree to Report: sanitized text, strict numbers, IPs normalized
    discovery.py     #   paths (files and folders) to an ordered list of `Source`s, deduplicated
    ingest.py        #   ingest(paths, domain, now=None): the entry point; refusals go to `skipped`
  text.py            # text and domain rules shared by reports and config (clean_text, normalize_domain…)
  config.py          # load_config(path) → frozen Config (domain + selector map); check_domain is shared with
                     # the CLI's --domain; ConfigError is typed (spec 003)
  senders.py         # identify_sender(record, config) → Identification; a selector counts only under the domain
  summary.py         # summarize(result, config) → frozen Summary: rows per sender, failing sources, period,
                     # policy, what was left out (spec 004), the messages per day (`DayCounts`, spec 008,
                     # internal: not in `--json`), what each reporter sent (`ReporterActivity`, internal);
                     # a day is covered when the merged report periods cover 12 h of it; never imports render
  render.py          # render_summary(summary, config_source, messages) → 80-column ASCII text;
                     # no_reports_message; also the public helpers fit, address, format_share,
                     # share_tenths
  verdict.py         # judge(summary) → frozen Verdict: Answer (READY/TOO_EARLY/NOT_READY), five Rules
                     # with the four threshold constants, Notes, LeftOut (what the summary did not
                     # count; it never changes the answer); integer arithmetic; never imports a
                     # text module (spec 005)
  render_verdict.py  # render_verdict(verdict, messages) → 80-column ASCII text: reason, rules table,
                     # notes, what was left out, next step
  render_json.py     # summary_document / verdict_document → dict, dumps → ASCII JSON, no language
                     # (spec 006); the schema is public contract, see docs/json-schema.md
  htmlkit.py         # the ONLY module that builds markup (spec 008): `text()` escapes a str into a `Safe`
                     # (a NewType), `el()` takes only `Safe` children and allowlisted tags
  html_style.py      # the palette (light and dark dicts, contrast measured by a test), the stylesheet
                     # and the CSP constant: no `url()`, no `@import`, no `<`
  html_charts.py     # meter, stacked_bar and timeline as inline SVG, integer geometry, figures in words
  render_html.py     # render_html(summary, verdict, messages) → one self-contained ASCII page: no script,
                     # no network, no path or file name
  render_fetch.py    # render_fetch(outcome, directory, messages) → the six numbers of a run;
                     # refusal_line(refusal, messages) → the one line of a refused run (spec 009)
  fetch/             # `mailvigil fetch` (spec 009): the only code that reaches the network
    errors.py        #   FetchReason (StrEnum) and FetchRefused: every refusal is typed
    model.py         #   FetchOutcome and the limits (DEFAULT_LIMIT, MAX_LIMIT, DEADLINE_SECONDS…)
    store.py         #   Store: `<tag>-<validity>-<uid>.eml` names, atomic writes (`os.replace`)
    run.py           #   fetch_reports(): the loop over a mailbox protocol; tested with FakeMailbox
    imap.py          #   the ONLY module that imports `imaplib` and `ssl`: verified TLS context,
                     #   BODY.PEEK reads, bounded reads, every library failure becomes a FetchReason
  messages/          # every sentence of the tool, one Messages per language (spec 006): model.py
                     # (Plural and the frozen dataclasses), en.py (ENGLISH), pt_br.py (PORTUGUESE,
                     # ASCII only); language_by_code; imports no renderer
tests/               # pytest, one test file per module (test_reports_*.py incl.
                     # test_reports_mail.py, test_text.py, test_config.py,
                     # test_senders.py, test_summary.py, test_render.py, test_verdict.py,
                     # test_render_verdict.py, test_render_json.py, test_render_pt.py,
                     # test_messages.py, test_json_schema_doc.py, test_cli_summary.py,
                     # test_cli_verdict.py, test_cli_json.py, test_cli_lang.py,
                     # test_cli_exit_codes.py, test_cli_mail.py, test_htmlkit.py, test_html_style.py,
                     # test_html_charts.py, test_render_html.py, test_render_html_hostile.py,
                     # test_cli_html.py, test_fetch_*.py, test_render_fetch.py,
                     # test_cli_fetch.py, test_smoke.py, test_gitignore.py, test_readme_pt_br.py and
                     # test_offline_isolation.py, which runs fresh interpreters to prove that
                     # summary and verdict never load the network code); fixtures are synthetic,
                     # built in conftest.py, cli_helpers.py, mail_helpers.py, schema_examples.py,
                     # html_helpers.py, render_verdict_golden.py, fetch_helpers.py (FakeMailbox),
                     # imap_peer.py (a scripted IMAP server on a socket pair), help_golden.py (the
                     # recorded --help texts) or tmp_path
specs/               # spec-driven development: requirements → design → tasks per feature
docs/stack.md        # each technology of the stack, why it was chosen, what to study first
docs/json-schema.md  # every field of the two --json documents and the compatibility promise
docs/stability.md    # what is public (commands, exit codes, JSON, config) and what is not; deprecation
CHANGELOG.md         # Keep a Changelog; a change a user would notice goes in [Unreleased] in the same PR
docs/demo/           # build_demo.py makes the invented reports and runs the CLI to write verdict.cast,
                     # the recording behind the README demo (see its docstring for the SVG and the
                     # page captures); tidy_svg.py pins the SVG text to a character grid;
                     # docs/images/ holds the README pictures
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

> ⚠️ **Markup is built in `htmlkit.py` only.** Text from a report reaches the HTML page only through
> `text()`, which escapes it into a `Safe`; never write a tag, an attribute or a `Safe(...)` anywhere
> else, and keep the page free of script, network and `url()` (`test_render_html_hostile.py` feeds
> the attacks).

> ⚠️ **`imaplib` and `ssl` are imported in `fetch/imap.py` only**, and that module is loaded inside
> `_run_fetch`, never at import: `summary` and `verdict` never load the network code. The TLS
> context always verifies the certificate (no `--insecure`, no plain IMAP, no STARTTLS); the
> mailbox is only read (`BODY.PEEK`, no flag, no delete); the password is never an argument, an
> environment variable or a log line. See spec 009, ADR-2 (the library's default context does not
> verify) and ADR-3 (bounds live in the connection).

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
  `/idioma`). User-facing CLI text: English (default) and Brazilian Portuguese, chosen only by
  `--lang` (no locale detection), ASCII in both, decided in the specs. The one documentation
  exception is `README.pt-BR.md`, the Portuguese README for the Brazilian audience (a user-facing
  text, so the product's audience language): keep it in step with `README.md`, whose headings
  `tests/test_readme_pt_br.py` compares.
- **File style:** follow `/estilo-arquivos` for each file type (docstrings with `Args:` /
  `Returns:`, full annotations, `# why` comments); do not copy its rules here.
- **Python floor:** 3.12, tested in CI together with 3.13, 3.14 and the newest stable release (3.15), on Linux and
  on Windows (the one runner outside the `ubuntu-26.04` rule, so "OS Independent" is tested). Ruff and black
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

**A feature with an interface** (the HTML report, spec 008, was the first) needs a mockup the
maintainer approved before any code: Claude builds it in the Artifact with `/nova-interface` (390
and 1280 px, two or three alternatives, one recommended) and writes no interface file until the
"ok". This is a global rule (`~/.claude/CLAUDE.md`); the 008 choice is recorded in
`specs/README.md`.

## Dependencies

`uv` manages everything: `pyproject.toml` holds the floors (`>=`) and `uv.lock` the exact
versions. Commit both together (`uv lock --check` must pass). Dependabot (`uv` and
`github-actions`, Sundays, 7-day cooldown) opens the routine PRs; review them with
`/revisar-dependabot`.

> Publishing (PyPI, GitHub Releases, posts) is the maintainer's act, never Claude's. Claude
> prepares the package, the README and the CI. A vulnerability in a published version is reported
> privately (private vulnerability reporting), never in a public issue, PR or commit.
