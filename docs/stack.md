# The stack, and why

Every load-bearing technology in MailVigil, what it does, why it was chosen over the alternative,
and the handful of concepts worth learning first if it is new to you.

This is not exhaustive: the full version graph is pinned in `uv.lock`, and per-feature decisions
live in the `### ADR-N` blocks of `specs/*/design.md`. This page is the map: the *shape* of the
project and the reasoning behind each piece. Entries marked **(planned)** are decided but not
built yet. The project is pre-0.1: the report-ingestion layer (`mailvigil.reports`), the
configuration loader, the sender identification, the summary, the verdict and their texts are built
and tested (it reads `.eml` and `.mbox` too, spec 007), and `mailvigil summary` and `mailvigil
verdict` run them end to end, in English or Portuguese (`--lang`), as text or as one JSON document (`--json`), with exit codes that are a public
contract (spec 006).

The project is one small program with no runtime dependency:

```text
report files (.zip, .gz, .xml)        mail files (.eml, .mbox)
        │                                   │  email   (bounded: size, lines, parts, depth)
        │                                   ▼
        │                          report attachments (bytes in memory)
        ▼                                   ▼
   zipfile / gzip   (size cap against zip bombs)
        ▼
   XML bytes ──► xml.parsers.expat (refuses DOCTYPE/ENTITY) ──► ElementTree tree
        │
        ▼
 Report and Record objects (ipaddress, sanitized text)   ◄── built
        │
        ▼
 sender named from the DKIM selector ◄── a TOML file (tomllib)   ◄── built
        │
        ▼
 summary per sender and per situation ──► 80-column terminal text   ◄── built
        │
        ▼
 verdict (five rules) ──► 80-column text (--lang en|pt-BR) or JSON (--json)
                         + exit code 0, 3 or 4                          ◄── built
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

### `email` and `email.policy`

Reads the mail messages of an `.eml` file or of each message in an `.mbox`, and hands back the
attachments that look like a report as plain bytes. `mailvigil/reports/mail.py` feeds a
`BytesFeedParser` 64 KiB at a time and walks the parts with its own stack, so it never enters a
message attached to a message and never recurses.

**Why this:** the `email` package is in the standard library and parses what real mail clients
write (RFC 2047 and RFC 2231 file names, base64, quoted-printable). A message is a container the
sender controls, so the work is in the bounds: the parser splits every line into an object, and on
a large message of empty parts it spends hundreds of MiB before a check *after* parsing could run.
The module checks the size and the number of lines first, then counts parts as the parser creates
them, through a message factory that raises past the limit
(`policy.default.clone(message_factory=…)` is the seam; ADR-1 and ADR-2 of spec 007). A report that
is not an attachment, or a message too big, costs one skipped entry and never the run.

**Learn:** `BytesFeedParser` (`feed`, `close`), `email.policy.default` and `clone()`, `EmailMessage.get_filename()` and `get_payload(decode=True)`, how a `multipart/*` tree is shaped and why walking
it with a stack is safer than recursion, why a body can be larger than its own size on disk
(base64 adds a third).

**Docs:** [email](https://docs.python.org/3/library/email.html),
[email.policy](https://docs.python.org/3/library/email.policy.html),
[email.parser](https://docs.python.org/3/library/email.parser.html)

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

### `tomllib`

Reads the configuration file: the domain and the map from DKIM selector to service name.
`mailvigil/config.py` reads the file as bytes (capped at 64 KiB), decodes it as strict UTF-8,
parses it with `tomllib.loads` and then checks the shape of the result by hand. Every refusal is a
`ConfigError` with a typed reason, never a stack trace.

**Why this:** TOML is read-only in the standard library since 3.11, and it is the format
`pyproject.toml` already taught every Python developer. No YAML parser to depend on, and no
include or variable syntax to defend against (ADR-1 and RNF-02 of spec 003).

**Learn:** `tomllib.loads` (text) against `tomllib.load` (binary file), `TOMLDecodeError` and the
line it carries, why a dotted key `a.b = "x"` is a nested table (so a selector with a dot is
quoted), and validating the shape of the loaded dict before using it.

**Docs:** [tomllib](https://docs.python.org/3/library/tomllib.html)

### `argparse`

The command line: `--version`, the `summary` and `verdict` subcommands, which share `PATH...`,
`--config`, `--domain`, `--json` and `--lang`. `--lang` is parsed by a `type=` function that returns
the language's message catalog, so a code that does not exist is argparse's own usage error (exit
`2`) and the command never sees a string.

**Why this:** against click, typer and rich, argparse needs nothing installed. The CLI is small
enough that its verbosity does not hurt, and terminal colors are a few ANSI codes that honor
`NO_COLOR` (**planned**).

**Learn:** `ArgumentParser` with `add_argument` (`action="version"`, `nargs="+"` for "one or more
paths"), `add_subparsers(dest="command")` for a command with its own flags, a parent parser
(`add_help=False`, passed as `parents=[shared]`) for the arguments two commands have in common, and
`parse_args(argv)` with an explicit `argv` (what makes the CLI testable) returning an exit code from
`main(argv) -> int`, and `type=` (a function that converts, and validates, an option's text).

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
| `json` | `render_json.py` turns the frozen summary and verdict into a `dict` and `json.dumps` writes it with `ensure_ascii=True` (so no console encoding can corrupt it) and `allow_nan=False`. The key order is the order the dict is built in, and it is part of the contract documented in `docs/json-schema.md` (spec 006) |
| message catalog | `messages/` holds every sentence as frozen dataclasses, one `Messages` per language (`ENGLISH`, `PORTUGUESE`); the renderers take it as a last parameter and read every sentence from it. `Plural` stores the whole phrase for 1 and for any other count, so Portuguese agreement needs no rule. Tests check that both languages have the same fields and placeholders (ADR-3 and ADR-4 of spec 006) |
| `unicodedata` | drops control, format and line-separator characters from every text of a report, by Unicode category (ADR-6 of spec 002) |
| `dataclasses`, `enum.StrEnum` | the immutable report model (`frozen=True, slots=True`), the refusal reasons and the verdict's answers, which are plain strings a later spec can translate |
| `enum.IntEnum` | `RuleId`, the number of each verdict rule (1 to 5): it sorts and prints as the number the table shows |
| integer thresholds | the verdict compares whole numbers only: rule 5 is `MAX_UNRECOGNIZED_PER_MILLE = 5` (0.5%), per mille so no float decides a verdict (ADR-4 of spec 005) |
| `io.BytesIO`, `bytearray` | an attachment taken out of a message is opened as `BytesIO` by the same zip and gzip code that opens a file; an mbox message is gathered in a `bytearray` that stops growing past the cap, so a mailbox with no separator never fills memory (ADR-3 and ADR-6 of spec 007) |
| `os.path.realpath` | tells that one file given twice, or once directly and once through its folder, is the same file, so it is read once |
| `difflib` | `get_close_matches` suggests the right key for a typo in the configuration (`domian` → `domain`) |
| `types.MappingProxyType` | the selector map of a `Config` is a read-only view, so a frozen dataclass does not hide a mutable dict (ADR-5 of spec 003) |
| `re` | the name pattern of an attachment (`provider!domain!begin!end…`), compiled with `re.ASCII` |
| `datetime` | the period of the summary: each report is a range of days with an exclusive end (one ending at midnight does not touch the next day), and overlapping ranges are merged so a day is counted once (ADR-3 of spec 004) |
| `collections.Counter` | counts the skipped files per reason for the "left out" section |
| integer arithmetic | `format_share` rounds a percentage to one decimal with `//`, never a float, and prints `<0.1%` so a small failing share is not rounded to zero (ADR-5 of spec 004). `share_tenths` is the integer under it: the verdict asks it whether a failed rule rounds to its own limit and then prints `>0.5%` (or `<80%`) instead of a number that reads as a pass beside `FAIL` (ADR-8 of spec 005) |
| `NO_COLOR` | convention for turning terminal colors off, honored by the output (**planned**) |

---

## What is deliberately not in the stack

- **click, typer, rich** — nice CLIs, but each is a dependency; `argparse` and a few ANSI codes do the job.
- **defusedxml, lxml** — hardened or faster XML parsers; refusing `DOCTYPE`/`ENTITY` inside `expat` makes the standard parser safe enough for this input.
- **gettext / Babel** — the CLI text exists in two languages (English and Portuguese), a small dictionary is simpler than a translation toolchain.
- **Elasticsearch, Splunk, Kibana, a web dashboard served by the tool** — permanent non-goals: that is parsedmarc's territory, and a server breaks "offline, nothing to run" (reasons in `specs/README.md`). `--json` feeds them from outside.
- **Sending e-mail** — a permanent non-goal: SMTP credentials and deliverability for no unmet need, since exit codes and `--json` compose with `cron`.
- **IMAP fetching** — planned as an opt-in `fetch` command (spec 009, standard-library `imaplib`); `summary` and `verdict` stay offline and read files you already have.
- **Docker / GHCR** — a pure-Python wheel installs with `pipx` or `uv tool`; an image adds a release surface for no gain.
- **Pydantic** — would validate the report records, but it is a dependency and the shape is small enough to check by hand.
