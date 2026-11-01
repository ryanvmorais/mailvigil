# Architecture: the module tree

Every module of `src/mailvigil/`, the tests, the specs and the other folders of the repository,
with what each one does. [CLAUDE.md](../../CLAUDE.md) keeps the layers and the map of what to read
before touching each part.

```text
src/mailvigil/
  __init__.py        # __version__ read from package metadata
  cli.py             # argparse entry point (`mailvigil = mailvigil.cli:main`): `--version`, `summary`
                     # (resolve_config, ingest → summarize → render, exit 0/1/2) and `verdict` (same
                     # load, then judge → render_verdict; exit 0 ready, 3 too early, 4 not ready);
                     # the exit code is decided before the format; a parent parser shares
                     # paths/--config/--domain/--recursive/--json/--top/--lang (`--lang` is parsed to a Messages;
                     # `--top N` needs `--json`, or `--html` on `verdict`, and is refused before any work);
                     # `--html` exists on `verdict` only and is refused together with `--json`;
                     # `--output FILE` (ADR-11) needs `--html` and `_write_page` writes it atomically,
                     # and for several domains it is a folder of `mailvigil-<domain>.html` (`_write_pages`);
                     # `fetch` (spec 009) is added by `cli_fetch.add_fetch_parser` and run by
                     # `cli_fetch.run_fetch`
  cli_common.py      # the eight EXIT_* codes (the one table), `echo` (a command-line value made safe to
                     # print), `write` (a line to a stream, whatever it can encode) and `config_line`
                     # (the line of a refused configuration); shared by cli and cli_fetch, which may
                     # not import each other
  cli_fetch.py       # the `fetch` command (spec 009): option types (`--port`, `--limit`, `--since`,
                     # `--folder`), the subparser (takes only `--lang` from the parents and has its own
                     # `--json`, the six numbers of a run), the password
                     # helpers, `_connection` (flag, else the [fetch] table of `--config`, else the
                     # default; the file is never searched for, ADR-12) and `run_fetch`, which loads `fetch.imap` (imaplib, ssl) inside the
                     # function, never at import (#82)
  py.typed           # marks the package as typed (PEP 561)
  reports/           # report ingestion (spec 002); public API re-exported by __init__.py
    errors.py        #   Reason (StrEnum) and ReportRefused: every refusal is typed
    model.py         #   frozen dataclasses: Report, Record, PolicyPublished, IngestionResult…
    xmlsafe.py       #   the only XML parser: expat handlers refuse DOCTYPE and ENTITY, and a
                     #                document past MAX_DEPTH levels or MAX_ELEMENTS elements
    reader.py        #   .xml/.gz/.zip to bytes, capped at MAX_BYTES (5 MiB) as it decompresses
    mail.py          #   .eml/.mbox (spec 007): report attachments out of messages, bounded in size,
                     #   lines, parts and depth before and while the `email` parser works
    parser.py        #   XML tree to Report: sanitized text, strict numbers, IPs normalized
    discovery.py     #   paths (files and folders) to an ordered list of `Source`s, deduplicated;
                     #   `--recursive` goes down 8 levels (no link entered) and the report-suffix
                     #   files whose name did not qualify are counted (`passed_over`, ADR-9 of 002)
    ingest.py        #   ingest_many(paths, domains): one reading, a result per domain (spec 010);
                     #   ingest(paths, domain) is the loop of one; refusals go to `skipped`
  text.py            # text and domain rules shared by reports and config (clean_text, normalize_domain…)
  config.py          # load_configs(path) → tuple of frozen Config, one per `domain` or `[[domains]]`
                     # entry (50 at most; an IDN goes through the `idna` codec and is refused if it
                     # changes; spec 010): domain + selector map + the [spf] and [ips] maps + the
                     # [fetch] settings (host, user, port, folder, never a password);
                     # check_domain is shared with the CLI's --domain; ConfigError is typed (spec 003)
  senders.py         # identify_sender(record, config) → Identification: a DKIM selector, an SPF domain
                     # or an address range names a sender only on an authentication aligned with the
                     # domain (ADR-8 of spec 003); the address needs a passing block as well
  summary.py         # summarize(result, config) → frozen Summary: rows per sender, failing sources, period,
                     # policy, what was left out (spec 004), the messages per day (`DayCounts`, spec 008,
                     # internal: not in `--json`), what each reporter sent (`ReporterActivity`, internal),
                     # the SPF domains that passed on a row not recognized (`spf_domains`, ADR-8);
                     # a day is covered when the merged report periods cover 12 h of it; never imports render
  render.py          # render_summary(summary, config_source, messages) → 80-column text;
                     # no_reports_message; also the public helpers fit, address, format_share,
                     # share_tenths
  verdict.py         # worst_answer(verdicts): the exit code of several domains;
                     # judge(summary) → frozen Verdict: Answer (READY/TOO_EARLY/NOT_READY), five Rules
                     # with the four threshold constants, Notes, LeftOut (what the summary did not
                     # count; it never changes the answer); integer arithmetic; never imports a
                     # text module (spec 005)
  render_verdict.py  # render_verdict(verdict, messages) → 80-column text: reason, rules table,
                     # notes, what was left out, next step
  render_json.py     # summary_document / verdict_document / fetch_document (+ the `domains`
                     # envelopes) → dict, dumps → ASCII JSON, no language
                     # (spec 006); the schema is public contract, see docs/json-schema.md; `top=N`
                     # trims the long lists and adds the last key `top` (ADR-8)
  htmlkit.py         # the ONLY module that builds markup (spec 008): `text()` escapes a str into a `Safe`
                     # (a NewType), `el()` takes only `Safe` children and allowlisted tags
  html_style.py      # the palette (light and dark dicts, contrast measured by a test), the stylesheet
                     # and the CSP constant: no `url()`, no `@import`, no `<`
  html_charts.py     # meter, stacked_bar and timeline as inline SVG, integer geometry, figures in words
  render_html.py     # render_html(summary, verdict, messages) → one self-contained ASCII page: no script,
                     # no network, no path or file name; the senders table stops at 50 rows or `top` (ADR-12)
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
                     # with accents, NFC), fold.py (PORTUGUESE_ASCII = the same without accents,
                     # one character for one; `catalog_for_streams` picks the catalog from the
                     # streams: UTF-8 on both and, on Windows, a console); language_by_code;
                     # imports no renderer
tests/               # pytest, one test file per module (test_reports_*.py, test_text.py, test_config.py,
                     # test_senders.py, test_summary.py, test_verdict.py, test_render*.py, test_messages*.py,
                     # test_json_schema_doc.py, test_cli_*.py, test_htmlkit.py, test_html_*.py,
                     # test_fetch_*.py, test_smoke.py, test_gitignore.py, test_readme_*.py,
                     # test_properties.py (Hypothesis: the readers only refuse and a parsed report
                     # reaches every output; the `thorough` profile is for a long hunt) and
                     # test_offline_isolation.py, which runs fresh interpreters to prove that
                     # summary and verdict never load the network code); fixtures are synthetic,
                     # built in conftest.py and the *_helpers.py, schema_examples.py, imap_peer.py (a
                     # scripted IMAP server), help_golden.py (the recorded --help texts) or tmp_path
specs/               # spec-driven development: requirements → design → tasks per feature
docs/stack.md        # each technology of the stack, why it was chosen, what to study first
docs/json-schema.md  # every field of the three --json documents and the compatibility promise
docs/stability.md    # what is public (commands, exit codes, JSON, config) and what is not; deprecation
CHANGELOG.md         # Keep a Changelog; a change a user would notice goes in [Unreleased] in the same PR
scripts/             # benchmark_ingest.py: times the reading of synthetic reports (not a test; issue #70)
docs/demo/           # build_demo.py makes the invented reports and runs the CLI to write verdict.cast,
                     # the recording behind the README demo (see its docstring for the SVG and the
                     # page captures); tidy_svg.py pins the SVG text to a character grid;
                     # docs/images/ holds the README pictures
.githooks/           # versioned pre-commit hook (core.hooksPath)
.claude/             # Claude Code hooks: format on edit, validate at turn end, guard uv.lock
.github/             # CI, CodeQL, dependency review, weekly pip-audit, the release workflow (release.yml),
                     # Dependabot, issue/PR templates
uv.lock              # never edit by hand (generated; a hook blocks it)
```
