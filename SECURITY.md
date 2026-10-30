# Security Policy

## Supported Versions

Only the latest release receives security fixes. A fix comes out as a patch release.

| Version | Supported |
|---|---|
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

MailVigil is a command-line tool that reads files you give it and writes to your terminal. It is
offline except for `mailvigil fetch`, which is opt-in: it connects to the IMAP server you name,
reads the report messages and saves them as files in a folder you choose. `summary` and `verdict`
make no network request, and the tool has no runtime dependency. Reports are treated as hostile
input.

**Report here** (a vulnerability in MailVigil itself): anything that lets a crafted input turn the
tool against its user, or that breaks one of its safety guarantees. For example:

- a report or archive that gets past the size cap on decompressed data (a zip or gzip bomb);
- an XML report that gets past the refusal of `DOCTYPE` and `ENTITY` declarations (entity
  expansion);
- a path inside an archive that makes the tool read or write outside the files it was given;
- a report, archive or message that stops the whole run instead of being refused as one skipped
  file (an unhandled exception), or that costs far more time or memory than its size;
- a configuration file or report that makes the tool run code or open a network connection;
- anything from a report or a configuration file reaching a place it should not (a log line, a
  file other than the requested output);
- in `mailvigil fetch`: a connection that is not TLS, or that accepts a certificate or a host name
  that does not verify (including through `--cafile`, which may only add trust);
- in `mailvigil fetch`: the password reaching an output, a log line, a file, an argument or the
  environment;
- in `mailvigil fetch`: any command that changes the mailbox or marks a message as read (the tool
  only reads it);
- in `mailvigil fetch`: text from the server shaping a file name or a path, or a read that is not
  bounded in size or in time.

**Not a vulnerability in MailVigil**: what a report says about a domain (an unknown sender, a
failing source, a spoofing attempt: that is for the domain's owner), and a wrong verdict or a
wrong classification of a report (open a regular bug report instead, with a synthetic sample).

The verdict is only as good as the reports it was given: it describes the reports you received,
not the mail you did not receive a report for.
