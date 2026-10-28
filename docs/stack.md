# The stack, and why

Every load-bearing technology in MailVigil, what it does, why it was chosen over the alternative,
and the handful of concepts worth learning first if it is new to you.

This is not exhaustive: the full version graph is pinned in `uv.lock`, and per-feature decisions
live in the `### ADR-N` blocks of `specs/*/design.md`. This page is the map: the *shape* of the
project and the reasoning behind each piece. Entries marked **(planned)** are decided but not
built yet. The project is pre-0.1: the report-ingestion layer (`mailvigil.reports`) is built and
tested, but the configuration, summary, verdict and output are not, and the CLI does not call the
ingestion layer yet.

The project is one small program with no runtime dependency:

```text
report files (.zip, .gz, .xml)
        │  zipfile / gzip   (size cap against zip bombs)
        ▼
   XML bytes ──► xml.parsers.expat (refuses DOCTYPE/ENTITY) ──► ElementTree tree
        │
        ▼
 Report and Record objects (ipaddress, sanitized text)   ◄── built
 ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─
 grouped by sender ◄── mailvigil.toml (tomllib)           ◄── planned
        │
        ▼
 summary + verdict ──► terminal text, or --json, plus an exit code
```

---

## Language and packaging

### Python 3.12+

The whole tool. 3.12 is the floor so that anyone still on it can install MailVigil; it is tested
in CI together with the newest stable release (3.15 today), and reaches end of life on
2028-10-31, when the floor gets reviewed.

**Why this:** a compiled language would add a build and a binary per platform for a tool that
reads a few small XML files. The standard library already has everything the job needs (zip, gzip,
XML, TOML, argument parsing), which is what makes "zero dependencies" possible.

**Learn:** type hints (`X | None`, `list[str]`, `Sequence[str]`), `pathlib.Path`, generators for
reading many files without loading all of them, and frozen dataclasses with `slots=True` (what the
report records are) next to `enum.StrEnum` (what the refusal reasons are).

**Docs:** [docs.python.org/3.12](https://docs.python.org/3.12/)

### uv

The Python package manager and virtual-environment tool (from Astral, the Ruff people). It
replaces `pip`, `pip-tools`, `virtualenv` and `pipx`. `uv sync` installs the locked graph, `uv
run` executes inside the environment, and `uv lock` resolves.

**Why this:** against Poetry, PDM and plain pip, uv is much faster, uses the standard
`pyproject.toml` (PEP 621) with a real lockfile (`uv.lock`), and needs no plugins. It also gives
end users `uv tool install mailvigil` for free.

**Learn:** `uv sync`, `uv run <cmd>`, `uv add --dev <pkg>` and `uv lock --check`; the split
between `[project.dependencies]` (empty here, on purpose) and `[dependency-groups] dev`.

**Docs:** [docs.astral.sh/uv](https://docs.astral.sh/uv/)

### Hatchling

The build backend: the program that turns the source tree into the sdist and the wheel when you
run `uv build`. Configured in `[build-system]` and `[tool.hatch.*]` of `pyproject.toml`.

**Why this:** against setuptools and Flit, Hatchling needs almost no configuration for a `src/`
layout, has no legacy `setup.py` baggage and is the same backend WebVigil uses. The wheel
contains only `src/mailvigil`; the sdist adds the README and the license.

**Learn:** the `src/` layout and why it stops you from importing the source tree by accident,
`[tool.hatch.build.targets.wheel] packages`, and how to read a wheel (`unzip -l dist/*.whl`).

**Docs:** [hatch.pypa.io](https://hatch.pypa.io/latest/)

### PyPI trusted publishing — OIDC **(planned)**

How the package will reach PyPI without a stored token: the release workflow proves its identity
to PyPI with a short-lived OIDC token. Publishing itself is always the maintainer's act.

**Why this:** against an API token in a repository secret, there is nothing to leak or rotate.

**Learn:** what a trusted publisher is, the `id-token: write` permission, and GitHub
environments with a required reviewer.

**Docs:** [docs.pypi.org/trusted-publishers](https://docs.pypi.org/trusted-publishers/)

---

## The standard library, doing the work

### `zipfile` and `gzip`

Open the `.zip` and `.gz` files the providers send. The one XML member is read with a hard cap on
the decompressed size (5 MiB), so a small archive that expands into gigabytes (a zip bomb) is
refused instead of exhausting memory. Nothing is extracted to disk, and a member's name is never
used as a path.

**Why this:** against a third-party archive library, these two are in the standard library and
already stream; the risk is in *how much* you read, which is our code either way. The cap counts
the bytes actually produced and ignores the size an archive declares, because a header can lie
(ADR-2 of spec 002).

**Learn:** `ZipFile.infolist()` to find the members (and why `ZipInfo.file_size` is not trusted),
`ZipFile.open()` as a stream, reading it in a loop up to `MAX_BYTES + 1` (a raw stream may return
fewer bytes than asked without having ended), `gzip.open()` and the `BadZipFile` / `BadGzipFile`
errors.

**Docs:** [zipfile](https://docs.python.org/3/library/zipfile.html),
[gzip](https://docs.python.org/3/library/gzip.html)

### `xml.parsers.expat` and `xml.etree.ElementTree`

`expat` is the XML parser underneath the standard library; `mailvigil/reports/xmlsafe.py` drives it
directly, with handlers that raise as soon as the document declares a `DOCTYPE` or an `ENTITY`.
A `TreeBuilder` from `ElementTree` assembles the tree that `parser.py` walks to get each record:
source IP, count, SPF and DKIM results, alignment and DKIM selector. That module is the only place
that creates an XML parser.

**Why this:** against `lxml` (a C dependency) and `defusedxml` (a dependency just for this), the
standard parser is enough once the dangerous constructs are refused. Hooking `expat` instead of
searching the bytes for `<!DOCTYPE` matters: expat decodes the document first, so the check sees
what the parser sees, in UTF-8 or UTF-16. The byte search missed a UTF-16 document in testing
(ADR-1 of spec 002). A legitimate DMARC report has neither construct, so refusing them costs
nothing.

**Learn:** `expat.ParserCreate`, the `StartDoctypeDeclHandler` and `EntityDeclHandler` hooks,
`TreeBuilder` (`start`, `end`, `data`, `close`), `find` / `findall` / `findtext` on the result, why
entity expansion ("billion laughs") is an attack, and why refusing the construct is safer than
limiting it.

**Docs:** [xml.parsers.expat](https://docs.python.org/3/library/pyexpat.html),
[xml.etree.ElementTree](https://docs.python.org/3/library/xml.etree.elementtree.html),
[XML security notes](https://docs.python.org/3/library/xml.html#xml-vulnerabilities)

### `ipaddress`

Turns the `source_ip` text of each record into a canonical address, so `2001:DB8::1` and
`2001:db8:0::1` are the same sender. Text that is not an address is kept, sanitized, instead of
failing the whole report.

**Why this:** the alternative is comparing strings, which treats one IPv6 address written two ways
as two senders and would split a sender's volume in the summary. The module is in the standard
library and handles IPv4 and IPv6.

**Learn:** `ip_address()` and its `ValueError`, `str()` of the result as the canonical form,
`is_private` and the other classification properties (useful later, in the summary).

**Docs:** [ipaddress](https://docs.python.org/3/library/ipaddress.html)

### `tomllib` **(planned)**

Reads `mailvigil.toml`: the domain and the map from DKIM selector to service name.

**Why this:** TOML is read-only in the standard library since 3.11, and it is the format
`pyproject.toml` already taught every Python developer. No YAML parser to depend on.

**Learn:** `tomllib.load` (binary file mode), the error type for invalid TOML, validating the
shape of the loaded dict before using it.

**Docs:** [tomllib](https://docs.python.org/3/library/tomllib.html)

### `argparse`

The command line: flags, `--version`, and later the subcommands and `--json`.

**Why this:** against click, typer and rich, argparse needs nothing installed. The CLI is small
enough that its verbosity does not hurt, and terminal colors are a few ANSI codes that honor
`NO_COLOR` (**planned**).

**Learn:** `ArgumentParser`, `add_argument(action="version")`, `parse_args(argv)` with an explicit
`argv` (what makes the CLI testable), and exit codes from `main() -> int`.

**Docs:** [argparse](https://docs.python.org/3/library/argparse.html)

---

## Quality tools

### Ruff

The linter, and the import sorter (it replaces flake8 and isort). Rules `E F I UP B SIM C4 RUF`,
line length 100, `target-version = "py312"`.

**Why this:** against flake8 plus a pile of plugins, one fast tool configured in `pyproject.toml`.
Targeting `py312` makes the lint reject syntax newer than the floor, so it fails on your machine
instead of a user's.

**Learn:** `ruff check --fix`, `select` / `ignore` in `[tool.ruff.lint]`, reading a rule with
`ruff rule <code>`.

**Docs:** [docs.astral.sh/ruff](https://docs.astral.sh/ruff/)

### Black

The code formatter. No options beyond line length and target version, so formatting is never a
review topic.

**Why this:** against Ruff's own formatter, black is the house standard across the maintainer's
projects, and the hooks run `ruff check --fix` then `black`.

**Learn:** `black --check .` (what the gate runs) and `black .` (what the hook runs), and the
"magic trailing comma".

**Docs:** [black.readthedocs.io](https://black.readthedocs.io/)

### mypy (strict)

The static type checker, over `src/` with `strict = true`. Every function is annotated, `-> None`
included.

**Why this:** the verdict logic is arithmetic over untrusted XML fields, where a `None` or a
string where a number is expected becomes a wrong "safe to reject". Strict mode catches that
class of mistake before the tests do. Tests are not type-checked on purpose.

**Learn:** what `strict` turns on, `Optional` handling (`X | None`) and narrowing, and writing a
specific `# type: ignore[code]` with a reason.

**Docs:** [mypy.readthedocs.io](https://mypy.readthedocs.io/)

### pytest and pytest-cov

The test runner and the coverage measurement. Coverage is measured (`uv run pytest --cov`, branch
coverage on) but has no numeric target.

**Why this:** against `unittest`, plain `assert`, fixtures and `parametrize` keep tests short, and
`capsys` makes the CLI output easy to check. Reports used as fixtures are always synthetic.

**Learn:** fixtures and `tmp_path` (build a zip or gzip of a synthetic report in the test),
`pytest.mark.parametrize`, `pytest.raises`, `capsys`, and reading the coverage "Missing" column.

**Docs:** [docs.pytest.org](https://docs.pytest.org/)

---

## Automation and supply chain

### GitHub Actions

The CI (`ci.yml`): quality on Python 3.12 and 3.15, a `package` job (build, `twine check`, the
wheel must declare no runtime dependency, it must install and run in a clean environment) and a
`security` job (`pip-audit`). Actions are pinned by commit SHA with the version in a comment, on a
fixed `ubuntu-26.04` runner.

Two more workflows cover the supply chain: CodeQL (code scanning, run as a workflow rather than the
default setup) and dependency review on pull requests.

**Why this:** it is where the repository lives. The repository is public, so Actions minutes are
free and the CI runs on pull requests, on pushes to `main` and by hand. A `proteger-main` ruleset
requires a pull request, a linear history and the quality and package checks to pass; `pip-audit`,
CodeQL and dependency review are deliberately not required, so a new CVE cannot block the PR that
fixes it.

**Learn:** `on:` triggers, `permissions: contents: read`, `concurrency`, a matrix, and why a SHA
cannot be moved after publication but a tag can.

**Docs:** [docs.github.com/actions](https://docs.github.com/en/actions)

### Dependabot and `pip-audit`

Dependabot opens weekly PRs for `uv` and `github-actions` (7-day cooldown, minor and patch
grouped). A separate weekly workflow runs `pip-audit` over `uv.lock`, because Dependabot does not
always open a fix and the CI audit only runs on pull requests.

**Why this:** the package has no runtime dependency, so this guards the dev tooling and the CI.
`pip-audit` runs with `uvx`, so the project does not depend on it.

**Learn:** `dependabot.yml` (`cooldown`, `groups`), `uv export --frozen`, and what a CVE entry in
the output means.

**Docs:** [Dependabot options](https://docs.github.com/en/code-security/dependabot/working-with-dependabot/dependabot-options-reference),
[pip-audit](https://pypi.org/project/pip-audit/)

### Git hooks and Claude Code hooks

A versioned pre-commit hook (`.githooks/pre-commit`) runs the whole gate, and four Claude Code
hooks in `.claude/` format on edit, validate at the end of a turn, block edits to `uv.lock` and
warn about a missing environment.

**Why this:** the local hook fails a bad commit before it leaves the machine, so the CI is a second
check and not the first. The editor-side hooks make the agent fix lint and type errors before it
hands anything back.

**Learn:** `git config core.hooksPath`, and the hook events (`PreToolUse`, `PostToolUse`, `Stop`,
`SessionStart`) and the exit code `2` that blocks.

**Docs:** [Git hooks](https://git-scm.com/docs/githooks),
[Claude Code hooks](https://docs.claude.com/en/docs/claude-code/hooks)

---

## Smaller pieces

| Piece | Role |
|---|---|
| `twine` (via `uvx`) | `twine check --strict` in CI: the README renders on PyPI |
| `coverage` | the engine under pytest-cov; settings in `[tool.coverage.*]` |
| `unicodedata` | drops control, format and line-separator characters from every text of a report, by Unicode category (ADR-6 of spec 002) |
| `dataclasses`, `enum.StrEnum` | the immutable report model (`frozen=True, slots=True`) and the refusal reasons, which are plain strings a later spec can translate |
| `os.path.realpath` | tells that one file given twice, or once directly and once through its folder, is the same file, so it is read once |
| `re` | the name pattern of an attachment (`provider!domain!begin!end…`), compiled with `re.ASCII` |
| `NO_COLOR` | convention for turning terminal colors off, honored by the output (**planned**) |

---

## What is deliberately not in the stack

- **click, typer, rich** — nice CLIs, but each is a dependency; `argparse` and a few ANSI codes do the job.
- **defusedxml, lxml** — hardened or faster XML parsers; refusing `DOCTYPE`/`ENTITY` inside `expat` makes the standard parser safe enough for this input.
- **gettext / Babel** — the CLI text exists in two languages (English and Portuguese), a small dictionary is simpler than a translation toolchain.
- **Elasticsearch, Splunk, Kibana, a web dashboard** — that is parsedmarc's territory; MailVigil answers one question offline.
- **IMAP fetching, sending e-mail** — out of scope: you point MailVigil at files you already have.
- **Docker / GHCR** — a pure-Python wheel installs with `pipx` or `uv tool`; an image adds a release surface for no gain.
- **Pydantic** — would validate the report records, but it is a dependency and the shape is small enough to check by hand.
