# Security Policy

## Supported Versions

MailVigil is pre-1.0 and has no release yet, so only `main` receives security fixes. Once the first
version is published, only the latest release will.

| Version | Supported |
|---|---|
| `main` (until the first release) | yes |
| latest release (from `1.0.0`) | yes |
| older releases | no |

## Reporting a Vulnerability

Please report security issues in MailVigil itself **privately**, through GitHub Security
Advisories: open the repository's **Security** tab and choose **Report a vulnerability**.
Do not open a public issue or pull request for it.

Include what is needed to reproduce it: the MailVigil version (`mailvigil --version`) or commit,
the command or configuration, what you expected and what happened, and the impact you see. Build
any sample report yourself: **never attach a real DMARC report**, because it carries IP addresses
and domains.

We aim to **acknowledge a report within 7 days** and to send a first assessment within 14.

## Disclosure Policy

We follow coordinated disclosure. A fix is prepared privately, released, and then the advisory is
published; the target is **90 days** from the report at most, sooner when a fix is ready. We credit
the reporter in the advisory unless asked not to.

## Scope

MailVigil is an offline command-line tool: it reads files you give it and writes to your terminal.
It makes no network request and has no runtime dependency. Reports are treated as hostile input.

**Report here** (a vulnerability in MailVigil itself): anything that lets a crafted input turn the
tool against its user, or that breaks one of its safety guarantees. For example:

- a report or archive that gets past the size cap on decompressed data (a zip or gzip bomb);
- an XML report that gets past the refusal of `DOCTYPE` and `ENTITY` declarations (entity
  expansion);
- a path inside an archive that makes the tool read or write outside the files it was given;
- a configuration file or report that makes the tool run code or open a network connection;
- anything from a report or a configuration file reaching a place it should not (a log line, a
  file other than the requested output).

**Not a vulnerability in MailVigil**: what a report says about a domain (an unknown sender, a
failing source, a spoofing attempt: that is for the domain's owner), and a wrong verdict or a
wrong classification of a report (open a regular bug report instead, with a synthetic sample).
