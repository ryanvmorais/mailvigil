# MailVigil

![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)
![deps](https://img.shields.io/badge/deps-uv-DE5FE9)
[![CI](https://github.com/ryanvmorais/mailvigil/actions/workflows/ci.yml/badge.svg)](https://github.com/ryanvmorais/mailvigil/actions/workflows/ci.yml)
![Lint](https://img.shields.io/badge/lint-ruff-261230)
![Format](https://img.shields.io/badge/style-black-000000)
![Types](https://img.shields.io/badge/types-mypy%20strict-2A6DB2)
![License](https://img.shields.io/badge/license-Apache%202.0-blue)

**MailVigil is an offline, zero-dependency DMARC report analyzer: a command-line tool that reads
the aggregate reports (RUA) your mail providers send you and tells you, in plain language, who is
sending mail as your domain and whether it is safe to move your policy to `p=reject`.**

Everyone who deploys DMARC receives a daily XML file (usually inside a `.zip` or `.gz`) from each
provider, and nobody reads them. The result is people who stay on `p=none` forever, afraid of
blocking legitimate mail. MailVigil reads them for you, groups the traffic by sender, and gives a
verdict with an explicit, documented criterion instead of a wall of numbers.

It is built for site owners, developers, agencies and infrastructure freelancers who are rolling
out DMARC, and it runs entirely on your machine: your reports are never sent to anyone.

> **Status:** under development (pre-0.1). Nothing is released yet and the interface will change
> until the first version is out. The table below is the plan, not what works today.

## What it will do

| Area | What | Version | Status |
|---|---|---|---|
| Input | Read a folder or files (`.zip`, `.gz`, `.xml`), filter by domain | v0.1 | Library built, not wired to the CLI yet |
| Hostile input | Cap decompressed size (zip bombs) and refuse XML with `DOCTYPE` or `ENTITY` (entity expansion) | v0.1 | Library built, not wired to the CLI yet |
| Configuration | A TOML file with your domain and a map from DKIM selector to service name; a signature only counts under your own domain | v0.1 | Library built, not wired to the CLI yet |
| Summary | Per sender and per situation (ok, fragile, failing), failures highlighted | v0.1 | Planned |
| Verdict | "Ready for `reject`?" with a declared criterion (minimum window, minimum volume, no legitimate failures) | v0.1 | Planned |
| Output | `--json` and stable exit codes for scripts and CI | v0.1 | Planned |

Out of scope for now: a web dashboard, Elasticsearch, fetching reports over IMAP and sending
e-mail.

## Configuration

MailVigil names a sender from the DKIM selector in its reports, using a map you write. The file is
TOML, and the names below are invented:

```toml
domain = "example.com"

[senders]
newsletter = "Example Mailer (newsletters)"
mailbox = "Example Mail (staff mailboxes)"
"k1.v2" = "Example Campaigns"
```

- **Start with an empty `[senders]`** and fill it from what the first summary shows as unknown.
- **A selector must identify one service.** Names such as `default` are shared by unrelated
  services, so MailVigil ships no built-in table and shows an unlisted sender as unknown.
- **A selector with a dot is written in quotes** (`"k1.v2"`). Without them TOML reads `k1.v2` as a
  nested table and MailVigil refuses the file.
- **A selector alone is not trusted.** It names a service only on a passing DKIM signature under
  your domain or one of its subdomains; the same selector under another domain is reported as a
  foreign domain.
- **The file is strict.** An unknown key (`domian`), a duplicate selector or a control character in
  a name is an error with a reason, never a silent guess, because a typo would change the answer.

The loader exists in the library (`mailvigil.config`), but no command reads the file yet.

## MailVigil vs. other tools

| | MailVigil | [parsedmarc](https://github.com/domainaware/parsedmarc) | Hosted services (dmarcian, EasyDMARC, Postmark) |
|---|---|---|---|
| Shape | One small CLI, standard library only | Parser and pipeline for Elasticsearch, Splunk and Kibana | Web dashboards |
| Where your reports go | Nowhere: offline | Your own stack | To a third party |
| Answer | A verdict on `p=reject` with a stated criterion | Parsed data (JSON, CSV, dashboards) | Dashboards and recommendations |
| Best for | Deciding if you can enforce DMARC, from the terminal | Continuous monitoring at scale | Teams that want a managed product |

MailVigil is not a replacement for a monitoring pipeline: if you already run parsedmarc, keep it.
It answers one question, and answers it without a stack to install.

## Quick start

Not published yet, so for now run it from a clone. You need [uv](https://docs.astral.sh/uv/).

```bash
# Clone and install the (dev) environment
git clone https://github.com/ryanvmorais/mailvigil.git
cd mailvigil
uv sync

# Check that the command runs (the only command that exists so far)
uv run mailvigil --version
```

Exit codes: not defined yet. They arrive with the output spec and become a stable contract at the
first release.

Installing with `pipx install mailvigil` or `uv tool install mailvigil` will be possible once the
first version is on PyPI.

## Development

Python 3.12 is the floor (CI tests 3.12 and the newest stable release). The quality gate runs
before every commit through a versioned hook:

```bash
# Activate the pre-commit hook once per clone
git config core.hooksPath .githooks

# The same sequence the hook and the CI run
uv run ruff check .
uv run black --check .
uv run mypy
uv run pytest --cov
```

Each technology of the stack, and why it was chosen, is explained in [docs/stack.md](docs/stack.md).
Features are specified under [specs/](specs/) before they are built.

Contributions are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md). To report a vulnerability in
MailVigil itself, use the private channel described in [SECURITY.md](SECURITY.md), never a public
issue.

## License

[Apache License 2.0](LICENSE).
