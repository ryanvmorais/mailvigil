# Invariants that must not regress

The promises of the product and the defenses that a harmless-looking change would break. Each one
has tests that feed the attack or check the promise; keep it so when touching them. [CLAUDE.md](../../CLAUDE.md) repeats each in one line.

## Zero runtime dependencies

> ⚠️ **Zero runtime dependencies is the product promise** (offline, nothing to install but the
> tool). `dependencies = []` in `pyproject.toml`, and the CI `package` job fails if the wheel
> declares any `Requires-Dist`. Dev tools go in `[dependency-groups] dev`. Parsing uses the
> standard library only (`argparse`, `tomllib`, `xml.etree`, `xml.parsers.expat`, `zipfile`,
> `gzip`, `ipaddress`).

## The one-domain path is the loop of one

> ⚠️ **The one-domain path is the loop of one** (spec 010): its text, `--json` and `--html` stay
> byte for byte as they were; the envelope and the folder of pages are for two or more domains.

## Markup is built in `htmlkit.py` only

> ⚠️ **Markup is built in `htmlkit.py` only.** Text from a report reaches the HTML page only through
> `text()`, which escapes it into a `Safe`; never write a tag, an attribute or a `Safe(...)` anywhere
> else, and keep the page free of script, network and `url()` (`test_render_html_hostile.py` feeds
> the attacks).

## `imaplib` and `ssl` are imported in `fetch/imap.py` only

> ⚠️ **`imaplib` and `ssl` are imported in `fetch/imap.py` only**, and that module is loaded inside
> `cli_fetch.run_fetch`, never at import: `summary` and `verdict` never load the network code. The TLS
> context always verifies the certificate (no `--insecure`, no plain IMAP, no STARTTLS; `--cafile`
> only adds an authority to the system's, ADR-10); the
> mailbox is only read (`BODY.PEEK`, no flag, no delete); the password is never an argument, an
> environment variable or a log line. See spec 009, ADR-2 (the library's default context does not
> verify) and ADR-3 (bounds live in the connection).

## Reports are hostile input

> ⚠️ **Reports are hostile input.** The parser refuses any XML containing `DOCTYPE` or `ENTITY`
> (entity expansion) inside `reports/xmlsafe.py`, and `reports/reader.py` caps the decompressed
> size at `MAX_BYTES` (5 MiB, against zip bombs) by counting the bytes actually read, never a
> declared size. The same parser also refuses a document nested past `MAX_DEPTH` levels or holding
> more than `MAX_ELEMENTS` elements (`Reason.XML_TOO_COMPLEX`, spec 002 ADR-8), because the byte cap
> alone does not bound the cost of the tree. Each defense has tests that feed the attack; keep it so
> when touching them, and keep `xmlsafe.py` the only module that creates an XML parser.
>
> A file that cannot be read is one skipped entry, never the end of the run: whatever the standard
> library raises while it opens an archive, decodes an encoding or parses a mail is mapped to a
> `Reason` where it happens (spec 002 ADR-10, spec 007 ADR-10). A zip member opens only when it is
> stored or deflated (`_ZIP_METHODS`), because other decompressors reserve memory before the cap
> counts a byte; a mail header is refused past `MAX_HEADER_CHARS` (4 KiB) before the `email`
> parser sees it; and a run stops past `MAX_RECORDS_PER_RUN` (1,000,000) kept records with
> `RunTooLarge`, because the caps per document do not bound a run. A new decompressor, parser or
> library call on report data gets the same treatment, with a test that it ends as a refusal.

## Never use a real DMARC report

> ⚠️ **Never use a real DMARC report** in tests, docs, issues or PRs: it carries IP addresses and
> domains. Fixtures are synthetic. `*.xml.gz`, `*.xml.zip` and `reports/` are git-ignored except
> under `tests/`.
