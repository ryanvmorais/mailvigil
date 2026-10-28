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
> until the first version is out. Rows marked "Built" work today through `mailvigil summary` and
> `mailvigil verdict`; the rest of the table is the plan.

## What it will do

| Area | What | Version | Status |
|---|---|---|---|
| Input | Read a folder or files (`.zip`, `.gz`, `.xml`), filter by domain | v0.1 | Built (`mailvigil summary`) |
| Hostile input | Cap decompressed size (zip bombs) and refuse XML with `DOCTYPE` or `ENTITY` (entity expansion) | v0.1 | Built (`mailvigil summary`) |
| Configuration | A TOML file with your domain and a map from DKIM selector to service name; a signature only counts under your own domain | v0.1 | Built (`mailvigil summary`) |
| Summary | Per sender and per situation (ok, fragile, failing), failures highlighted | v0.1 | Built (`mailvigil summary`) |
| Verdict | "Ready for `reject`?" with a declared criterion: 28 days covered, reports on 80% of the days, 1000 messages, no failure from a recognized sender, at most 0.5% of the messages failing from unrecognized sources | v0.1 | Built (`mailvigil verdict`) |
| Output and language | `--json` and stable exit codes for scripts and CI; the text in English or Brazilian Portuguese (`--lang pt-BR`) | v0.1 | Built (`--json` and `--lang` on `summary` and `verdict`) |

Planned: reading `.eml` and `.mbox` files, a static HTML report and an opt-in `fetch` over IMAP (see
[specs/](specs/README.md#roadmap)). Not planned, on purpose: indexing in Elasticsearch, a web
dashboard served by the tool and sending e-mail, each with its reason in
[Permanent non-goals](specs/README.md#permanent-non-goals).

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

`mailvigil summary --config FILE` reads it. Without `--config` the command reads `mailvigil.toml`
in the current folder, if there is one; with neither a file nor `--domain` it asks for one.

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

# Check that the command runs
uv run mailvigil --version

# Sum up a folder of reports (or name the files); mailvigil.toml is read if it is here
uv run mailvigil summary reports/
uv run mailvigil summary --config mailvigil.toml reports/
uv run mailvigil summary --domain example.com report.xml.gz

# Ask if the domain is ready for p=reject (same arguments as summary)
uv run mailvigil verdict --config mailvigil.toml reports/

# The same answers as one JSON document, for a script or a CI job
uv run mailvigil verdict --config mailvigil.toml reports/ --json

# The text in Brazilian Portuguese (English is the default)
uv run mailvigil verdict --config mailvigil.toml reports/ --lang pt-BR
```

The commands print their text and nothing else; they only read your files and touch no network.
A folder is searched, one level deep, only for the names providers use for their attachments
(`provider!domain!begin!end.zip`, also `.gz` and `.xml`). A file named on the command line is read
whatever its name. The output looks like this (invented data):

```text
MailVigil summary for example.com
  config    mailvigil.toml (3 selectors)
  period    2026-10-20 to 2026-10-20 (1 of 1 day has a report)
  reports   1 from 1 reporter
  policy    p=none, sp=none, pct=100
  messages  7335 (7250 from recognized senders, 98.8%)

Situations
  ok       6300  85.9%
  fragile   975  13.3%
  failing    60   0.8%

Senders
  sender                               ok  fragile  failing  total
  Example Mailer (newsletters)       6300        0        0   6300
  Example Mail (staff mailboxes)        0      950        0    950
! 203.0.113.5 (unrecognized)            0        0       40     40
  198.51.100.99 (failing signature)     0       25        0     25
! 203.0.113.9 (unrecognized)            0        0       12     12
! 2001:db8::7 (unrecognized)            0        0        8      8

! FAILING: 60 messages in 3 sources
  Unrecognized sources that fail
  ! 203.0.113.5
      40 messages  dkim: fail, spf: fail
  ! 203.0.113.9
      12 messages  dkim: none, spf: fail
  ! 2001:db8::7
      8 messages  dkim: none, spf: none

Left out of these numbers
  skipped files  0
  duplicates     0
  other domains  0
```

A `!` marks a sender with failing messages. Files that were refused, duplicates and reports of
another domain are counted at the bottom, so a number never silently drops out.

Installing with `pipx install mailvigil` or `uv tool install mailvigil` will be possible once the
first version is on PyPI.

### The verdict

`mailvigil verdict` answers one of three things, each with the rule that decided it. This is a
`NOT READY` (invented data):

```text
MailVigil verdict for example.com: NOT READY for p=reject

Why: failures from unrecognized sources are 0.8% of the messages (56 of 7056);
     the limit is 0.5%.
  203.0.113.5  unrecognized: 56 failing messages

Rules
  rule                      measured         needed   result
  1  period covered         29 days          >= 28    pass
  2  days with a report     29 of 29 (100%)  >= 80%   pass
  3  messages seen          7056             >= 1000  pass
  4  recognized failures    0                <= 0     pass
  5  unrecognized failures  56 (0.8%)        <= 0.5%  FAIL

Next: look at the sources above and add the selectors of the ones that are yours
      to [senders] in the configuration.

This reads only the reports you gave it: mail that no receiver reports on, and
senders that were quiet in this period, are not covered.
```

`READY` means every rule passes. `TOO EARLY` means the data rules (1 to 3) fail and nothing is
failing yet: wait for more reports. `NOT READY` means a source fails (rules 4 and 5), and the
command names it.

When files were refused, duplicated or from another domain, the verdict adds one line saying so;
`mailvigil summary` shows why. They never change the answer.

### Exit codes

The exit code is a contract: a script can tell "yes", "wait" and "no" from "I could not run"
without reading the text. `--json` does not change it.

| Code | Meaning | Commands |
|---|---|---|
| `0` | An answer was printed; for `verdict`, the answer is `ready` | both |
| `1` | The run was refused: invalid configuration or domain, or no report kept | both |
| `2` | Usage error (an unknown option, a missing argument) | both |
| `3` | `verdict` printed `too early`: wait for more reports | `verdict` |
| `4` | `verdict` printed `not ready`: a source fails | `verdict` |

Note that `1` is a refusal and `4` is "not ready"; a script that treats every non-zero code alike
mixes them up:

```bash
mailvigil verdict reports/ --domain example.com --json > verdict.json
case $? in
  0) echo "ready for p=reject" ;;
  3) echo "too early: keep collecting reports" ;;
  4) echo "not ready: see verdict.json" ;;
  *) echo "mailvigil could not run" >&2 ;;
esac
```

A change to this table is a breaking change.

### JSON

`--json` on `summary` or `verdict` prints one JSON document and a newline on standard output,
and nothing on standard error. The document is data, not text: integers, booleans, identifiers and
the report values, with no sentence and no rounded percentage. It carries every sender and every
failing source, without the limits the text keeps, and a value that may not exist (no period yet,
no `sp`) is `null`. A refused run prints no document: the one line goes to standard error, as
without `--json`, and the exit code is `1`. `docs/json-schema.md` lists every field and the
compatibility promise.

### Language

The text of both commands and the one-line refusals are in English by default. `--lang pt-BR`
(`pt-br` works too) prints them in Brazilian Portuguese; `--lang en` is the default spelled out, and
any other code is a usage error (exit `2`). The Portuguese is plain ASCII (`nao`, not `não`), so no
console encoding can break the layout. The same invented `NOT READY` as above:

```text
Veredito do MailVigil para example.com: NAO PRONTO para p=reject

Motivo: as falhas de origens nao reconhecidas sao 0.8% das mensagens (56 de
        7056); o limite e 0.5%.
  203.0.113.5  nao reconhecido: 56 mensagens com falha

Regras
  regra                       medido           necessario  resultado
  1  periodo coberto          29 dias          >= 28       passa
  2  dias com relatorio       29 de 29 (100%)  >= 80%      passa
  3  mensagens vistas         7056             >= 1000     passa
  4  falhas reconhecidas      0                <= 0        passa
  5  falhas nao reconhecidas  56 (0.8%)        <= 0.5%     FALHA

Proximo: olhe as origens acima e acrescente os seletores das que forem suas a
         [senders] na configuracao.

Isto le apenas os relatorios que voce deu: email que nenhum receptor reporta, e
remetentes que ficaram quietos neste periodo, nao sao cobertos.
```

Numbers keep the decimal point in both languages, `--json` has no language (its identifiers do not
change), `--help` stays in English, and neither the language nor `--json` changes an exit code.

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
