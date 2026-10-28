# Specs

MailVigil is built with spec-driven development. Each feature is designed as a spec under
`specs/NNN-name/` before implementation, driven by the `/spec` skill. Specs are plain Markdown and
stay readable without any tool.

## Conventions

- **Numbering:** `NNN` sequential, three digits (`001`, `002`, …), in the order specs are opened.
  The name is short and in English (`001-foundation`).
- **Files:** each spec has `requirements.md` (what and why), `design.md` (how) and `tasks.md`
  (an executable breakdown). Each one carries the same frontmatter: `feature`, `status`, `date`,
  `related`, `origin`.
- **Phases and gates:** `requirements → design → tasks → implementation`. Every phase ends with
  explicit human approval before the next one starts.
- **Valid statuses:** `planned` → `draft` → `approved` → `in progress` → `done`. (`planned` is a
  roadmap entry without spec files yet. `origin: conception` for specs written before the
  implementation; `reverse-engineering` only to document something already finished.)
- **Acceptance criteria:** Given / When / Then, one bullet per scenario.
- **Traceability:** requirements are `RF-NN` (functional) and `RNF-NN` (non-functional). Each task
  and each design decision cites the requirement it satisfies.
- **Language:** specs are in English. The conversation with the maintainer is in Portuguese.

## How a spec is tested

1. **Logic is unit-tested.** Classification, the verdict and the parser are tested by calling the
   function with built inputs, not through the whole CLI.
2. **Reports in tests are always synthetic**, built in the test (or small files under `tests/`).
   Never a real report: it carries IP addresses and domains.
3. **Hostile input is tested**, not assumed: every defense (decompressed size cap, `DOCTYPE` and
   `ENTITY` refusal) has at least one test that feeds it the attack and expects a refusal.
4. **The CLI is tested through `main(argv)`** and `capsys`, and the exit codes are asserted.
5. **The quality gate is the last task of every stage**, with its real result recorded.

## Workflow

```text
requirements → design → tasks → implementation
```

No phase starts without the maintainer's explicit approval of the previous one.

| Command | What it does |
|---|---|
| `/spec nova <name>` | Opens `specs/NNN-name/` with `requirements.md` as a draft |
| `/spec design` | Writes `design.md` once the requirements are approved |
| `/spec tasks` | Writes `tasks.md` once the design is approved |
| `/spec implementar` | Runs the tasks one by one and records each quality gate |
| `/spec status` | Summarizes every spec's status and current phase |

## Roadmap

The first six rows are a proposal for the first release (`v0.1`). Each one is refined, and may be
merged or split, when its spec is opened.

| Spec | Scope | Delivery | Status |
|---|---|---|---|
| [`001-foundation`](001-foundation/) | package skeleton, `mailvigil --version`, the local quality gate, CI, supply-chain hygiene | — | **in progress** |
| [`002-report-ingestion`](002-report-ingestion/) | read folders and files (`.zip`, `.gz`, `.xml`), domain filter, the hostile-input defenses, the report record model | `v0.1` | **done** |
| [`003-config-and-senders`](003-config-and-senders/) | TOML config with the domain and the DKIM selector → service name map, and sender identification | `v0.1` | **done** |
| [`004-summary`](004-summary/) | per-sender and per-situation summary (ok, fragile, failing), failures highlighted, and the first command (`mailvigil summary`) | `v0.1` | **done** |
| [`005-reject-verdict`](005-reject-verdict/) | "ready for `reject`?" with a declared criterion (minimum window, minimum volume, no legitimate failures); the thresholds are decided there | `v0.1` | **done** |
| [`006-output-and-exit-codes`](006-output-and-exit-codes/) | `--json`, stable exit codes, English and Portuguese text (`--lang`) | `v0.1` | **done** |
| [`007-mail-message-input`](007-mail-message-input/) | read `.eml` and `.mbox` files: the report attachment is taken out of the message in memory and goes through the same reader, parser, filter and dedup | — | **done** |
| [`008-html-report`](008-html-report/) | a single static HTML file with the summary and the verdict (`--html` on `verdict`): no server, no script, no network. Interface decided on 2026-10-28 from a mockup: the verdict first, then each rule as a meter against its limit (alternative B), with the stacked bar of the message mix (from C); WebVigil's visual language (slate palette, 0.5 rem radius, icon plus text on every badge, 4.5:1 contrast, dark mode from the system); a per-day timeline drawn from the reports' own dates, in inline SVG | — | **in progress** |
| `009-imap-fetch` | `mailvigil fetch`: download the report messages from a mailbox into a folder, opt-in; `summary` and `verdict` stay offline | — | planned |

Specs 007 to 009 were planned on 2026-10-28, after the first six were done. 009 depends on 007: the
fetch only saves raw messages and leaves the reading to the ingestion.

## Permanent non-goals

These are decisions, not a backlog. Each one has a reason that the product depends on, so reopening
one means writing a spec that answers the reason, not adding a flag.

| Not doing | Why | Instead |
|---|---|---|
| **Indexing reports in Elasticsearch, Splunk or Kibana** | It is the ground of `parsedmarc`, and the product is the opposite: one question, answered offline. Indexing needs a running store, a network and credentials, and the value lives in the dashboards, not in an answer. | `--json` is a stable document (`docs/json-schema.md`): pipe it into whatever you already run. |
| **A web dashboard served by MailVigil** | A server breaks "nothing to run but the tool" and turns hostile text from reports (organization names, domains, selectors, IPs) into a web attack surface: escaping, sessions, exposure to a network. Dashboards are also what the competitors already do. | Spec 008: one static HTML file, no script, opened from disk. |
| **Sending e-mail** (digests, alerts) | It needs SMTP credentials and deliverability, and a DMARC tool that sends mail is one more sender to authenticate. There is no unmet need: the exit codes and `--json` already compose with `cron` and any mailer. | `mailvigil verdict …` in a script; the exit code (`0`, `3`, `4`) is the signal. |

## Maintenance notes

> ⚠️ **Zero runtime dependencies.** A spec that seems to need a library designs it with the
> standard library first, and records the trade-off as an ADR. The CI `package` job fails if the
> wheel declares a dependency. See [001](001-foundation/).

> ⚠️ **The verdict must state its criterion.** The product is not a parser: it is an answer with a
> reason. A verdict that cannot say which rule produced it does not ship (spec 005).

> ⚠️ **Exit codes and `--json` are public contract** once released. Changing them is a breaking
> change (spec 006).
> Since stage 1 of 006 the codes are no longer provisional and `--json` exists on `summary` and
> `verdict`; the table lives in `cli.py` and the schema in `docs/json-schema.md`.

There is no gold-standard spec yet; once `001-foundation` is `done`, use it as the format reference.
