---
feature: Reject verdict — "is this domain ready for p=reject?", with the criterion stated
status: done
date: 2026-10-28
related:
  - 003-config-and-senders/requirements.md
  - 004-summary/requirements.md
origin: conception
---

# 005 — Reject verdict

## Context and problem

After [004](../004-summary/) `mailvigil summary` shows who sends as a domain and what fails. It
deliberately stops there: it never says "safe" or "ready". The owner still has to read the table and
decide alone whether moving the policy to `p=reject` will block real mail. That decision is the one
MailVigil exists for, and the one other tools leave to the reader.

This spec adds the **verdict**: a short answer with its reason, computed from the `Summary` that 004
already exposes as data. Its one design rule comes from the roadmap: **a verdict that cannot say
which rule produced it does not ship.** So the verdict is a fixed, small list of rules. Each one has
a name, a measured value, a threshold and a pass or fail, and the answer is derived from them in a
way anyone can follow by hand.

Two things make the answer honest:

- **It distinguishes "no" from "not yet".** A recognized service that fails today is a *no*: more
  reports will not fix it. Three days of reports with a clean table is a *not yet*: nothing is
  wrong, but nothing is proven. Collapsing the two into one red light would teach the owner to
  ignore it.
- **It claims only what the reports show.** Reports say what receivers saw in a period, not what
  the owner sends once a month, nor mail that no receiver reports on. The output says so in one
  line, every time.

The thresholds below are a first proposal, in the sense that a rule needs a number to be testable.
They are constants in one place, chosen from the usual operational advice (observe at least a few
weeks, fix every legitimate source, then enforce), and they will be checked against the
maintainer's own reports (never committed) before `0.1`. Nothing here is a contract before `0.1`.

## Goals

- **Answer one question** with one of three verdicts and the rules behind it: `ready`, `not ready`
  or `too early`.
- **Show the criterion**: every rule, its measured value, its threshold and its result, so the
  owner can disagree with a rule instead of with a mystery.
- **Say what to do next**: the first thing to fix, taken from the failing sources 004 already lists.
- **Stay pure**: the verdict is a function of a `Summary`, unit-tested without files, XML or a
  terminal.
- **Wire the command** that prints it.

## Non-goals

- Changing the policy, reading DNS, or checking that the published record is valid (offline is the
  product promise).
- A staged plan (`p=quarantine; pct=10` and onwards). The verdict answers the `reject` question
  only; it does not generate a rollout.
- Per-domain tuning of the thresholds in the configuration file, or flags that change them (see
  Resolved decision 3).
- `--json`, the stable exit-code contract and the Portuguese text: spec `006`. This spec keeps the
  text in one place, as 004 does.
- Judging whether an unrecognized failing source is an attack. The verdict counts it and names the
  first ones to look at; it does not guess (004, Resolved decision 3 still holds for the summary).
- Predicting the effect of `sp`, `np` or subdomains beyond showing the published values.

## Personas

- As the **owner of a domain about to enforce DMARC**, I want a yes, a no or a "wait" with the
  reason, so that I stop reading the table to reach a conclusion.
- As a **skeptical reader**, I want to see the rule and the number that produced the answer, so that
  I can judge whether the rule is fair for my domain.
- As a **contributor**, I want `judge(summary)` to be a pure function, so that every rule and every
  boundary is a unit test.

## What the output looks like

A sketch with invented data. The three parts (answer, rules, next step) and their order are the
contract of this spec; the exact spacing is not.

```text
MailVigil verdict for example.com: NOT READY for p=reject

Why: a recognized sender fails DMARC.
  Example Mailer (newsletters): 12 messages fail (192.0.2.10)

Rules                                  measured    needed    result
  1  period covered                    27 days     >= 28     fail (too early)
  2  days with a report                27 of 28    >= 80%    pass
  3  messages seen                     12480       >= 1000   pass
  4  recognized senders that fail      12          0         FAIL
  5  unrecognized failures             0.3%        <= 0.5%   pass

Next: make Example Mailer (newsletters) sign with your domain (DKIM) or add its servers to SPF,
then collect another period.

This reads only the reports you gave it: mail that no receiver reports on, and senders that were
quiet in this period, are not covered.
```

## Functional requirements

### RF-01 — The three verdicts

- **Given** any problem rule fails (rules 4 or 5)
  **When** the verdict is built
  **Then** it is `not ready`, whatever the data rules say: a problem already seen does not need
  more data to be real.
- **Given** no problem rule fails and any data rule fails (rules 1 to 3)
  **When** the verdict is built
  **Then** it is `too early`.
- **Given** every rule passes
  **When** the verdict is built
  **Then** it is `ready`.
- **Given** a `Summary` with no reports
  **When** the verdict is built
  **Then** it is `too early`, with all the data rules failing and no division by zero.

### RF-02 — The rules

Each rule has a stable id, a name, a measured value, a threshold and a result. The thresholds are
named constants in one module (Resolved decisions 1 and 2).

| Id | Kind | Rule | Pass when |
|---|---|---|---|
| 1 | data | period covered (`days_spanned`) | at least 28 days |
| 2 | data | days with a report over days spanned | at least 80% |
| 3 | data | messages seen (`totals.total`) | at least 1000 |
| 4 | problem | messages failing under a recognized sender | exactly 0 |
| 5 | problem | failing messages of unrecognized sources over all messages | at most 0.5% |

- **Given** a measured value equal to its threshold
  **When** the rule is checked
  **Then** the boundary passes for "at least" and "at most" rules alike, and a test asserts each
  boundary and the value just beside it.
- **Given** a rule
  **When** it is reported
  **Then** it carries its id, name, measured value, threshold and result as fields of a frozen
  dataclass, not as text.

### RF-03 — The reason and the next step

- **Given** a `not ready` verdict
  **When** the reason is built
  **Then** it names the first failing problem rule and the sources behind it: for rule 4 every
  recognized sender with its failing messages and source IPs (004's failing sources), for rule 5 the
  unrecognized sources with the most failing messages, at most 5, and a line with how many more.
- **Given** a `too early` verdict
  **When** the reason is built
  **Then** it names each data rule that failed, with how much is missing (days, messages).
- **Given** a `ready` verdict
  **When** the reason is built
  **Then** it says which rules passed and lists the notes of RF-04, if any; it never says "safe".
- **Given** any verdict other than `ready`
  **When** the next step is built
  **Then** it is one sentence about the first thing to do, chosen by rule (fix a recognized sender;
  look at the unrecognized sources and add the selectors of the ones that are yours; collect more
  reports).
- **Given** a failing source with override reasons such as `forwarded` or `mailing_list`
  **When** it is listed in the reason
  **Then** the reason types are shown next to it (004 RF-04): they explain the failure, they do not
  excuse it.

### RF-04 — Notes that do not change the verdict

- **Given** fragile traffic above zero
  **When** the verdict is built
  **Then** a note gives its share and how much of it passes by SPF only, since forwarding breaks
  SPF; it is a note, not a rule.
- **Given** a published `pct` below 100
  **When** the verdict is built
  **Then** a note says that the policy is applied to that share of the mail only.
- **Given** a policy that changed during the period (004 `earlier_p`)
  **When** the verdict is built
  **Then** a note says so: the figures mix two policies, and the verdict is about the traffic, not
  about which policy produced it.
- **Given** a `sp` or `np` different from `p`
  **When** the verdict is built
  **Then** a note shows it: moving `p` does not change what they already say.

### RF-05 — A policy that already enforces

- **Given** the latest published `p` is `reject`
  **When** the verdict is built
  **Then** the same rules apply, but the title reads "already at p=reject" and the verdict words are
  read as "is enforcement blocking mail it should not": `not ready` becomes `blocking real mail`,
  and `ready` becomes `no problem seen`. The rules and thresholds do not change.
- **Given** the latest published `p` is `quarantine`
  **When** the verdict is built
  **Then** it answers the same question about `reject`, with a note that the current policy is
  `quarantine`.

### RF-06 — The command

- **Given** `mailvigil verdict PATH [PATH ...] [--config FILE] [--domain DOMAIN]`
  **When** it runs
  **Then** it resolves the configuration and the domain exactly as `summary` does (004 RF-08), builds
  the `Summary`, judges it and prints the verdict, with the same refusals and the same standard-error
  messages (004 RF-10).
- **Given** a printed verdict
  **When** the command ends
  **Then** the exit code is `0` for `ready`, `3` for `too early` and `4` for `not ready` (open
  question 4); `1` and `2` keep their meaning from 004. The codes are provisional until spec `006`.
- **Given** `mailvigil summary`
  **When** it runs
  **Then** its output and exit codes are unchanged (Resolved decision 5).
- **Given** a verdict
  **When** it is printed
  **Then** the layout follows 004 RF-09: at most 80 columns, ASCII, no color, no control code.

### RF-07 — Edge cases are tested, not assumed

- **Given** the test suite for this spec
  **When** it runs
  **Then** it contains, at least: each boundary of each rule and the value beside it; no reports;
  a clean table with a short window (`too early`); a recognized failure with a short window
  (`not ready`, not `too early`); zero messages with reports present; unrecognized failures exactly
  at and just over 0.5%; more than 5 unrecognized failing sources; a policy of `reject`, of
  `quarantine` and of `none`; a changed policy; `pct` below 100; the same reports in a different
  order giving an equal verdict; a share just over each percentage limit (RF-08); and skipped files,
  duplicates and another domain each alone and together (RF-09).

### RF-08 — A share never reads against its result

Added after testing the command end to end (issue #28). The shares of rules 2 and 5 are printed to
one decimal, so a failure just over its limit (151 of 30000 is 0.503%) printed as `0.5%` beside
`<= 0.5%` and `FAIL`.

- **Given** a rule with a percentage threshold (2 or 5) that fails
  **When** its share, rounded for the text, would equal the threshold
  **Then** the text prints the share as beyond the limit (`>0.5%` for rule 5, `<80%` for rule 2),
  in the table and in the reason, so the printed value never reads as a pass.
- **Given** the same rule when it passes
  **When** its share is printed
  **Then** the text is unchanged: a share that equals the threshold after rounding and passes still
  prints as the rounded value.
- **Given** the counts beside the share
  **When** the text is built
  **Then** they stay (`151 of 30000`), and the decision to print the beyond-the-limit form is
  taken from the integers the rule compared, not from the rounded text.

### RF-09 — The verdict says what was left out

Added with RF-08. `summary` ends with "Left out of these numbers"; the verdict did not, so a `ready`
could be printed while reports had been refused (unsafe XML, too large once decompressed, malformed).

- **Given** a `Summary` in which at least one file was skipped, a report was dropped as a duplicate
  or a report belonged to another domain
  **When** the verdict is built
  **Then** `Verdict` carries those counts as data (a frozen dataclass), whatever the answer.
- **Given** a verdict with something left out
  **When** it is printed
  **Then** the text has one line, after the notes and before the closing sentence, with the count of
  skipped files and, when above zero, of duplicates and of reports of another domain, and it points
  to `mailvigil summary` for the reasons. It never lists file names: that stays in the summary.
- **Given** a verdict with nothing left out
  **When** it is printed
  **Then** the text is exactly what it was before this requirement: no line, no empty section.
- **Given** a `ready` verdict with skipped files
  **When** it is printed
  **Then** the answer stays `ready` (a refused file is not a failing message), and the line is the
  only difference; the closing sentence still reads the same.
- **Given** the line
  **When** it is built
  **Then** it is at most 80 columns, ASCII, and its numbers come from the `Summary`, not from
  counting text (RNF-05 applied here).

## Non-functional requirements

### RNF-01 — Standard library only

- **Given** the project at any commit
  **When** `[project].dependencies` is read
  **Then** it is still empty.

- **Given** the caller passes the moment of the run and the latest report ended more than 14 days
  before it
  **When** the verdict is built
  **Then** a note says how many days ago it ended: the figures may not describe the mail sent
  today. It never changes the answer, and without a moment there is no such note.

### RNF-02 — Pure and deterministic

- **Given** a `Summary`
  **When** it is judged twice
  **Then** the verdicts are equal: nothing depends on the clock, the locale, the file system or the
  order of the reports. `judge` does no I/O and reads no clock: the moment of the run, when there is
  one, is its parameter.

### RNF-03 — Rules apart from text

- **Given** the layer
  **When** it is read
  **Then** `judge` returns a frozen `Verdict` with the rules, the sources, the notes and the verdict
  as data; a renderer turns it into lines, as 004 does, so `006` replaces the text and adds `--json`
  without touching the rules.

### RNF-04 — Typed and immutable

- **Given** the model
  **When** `mypy` runs in strict mode
  **Then** it passes, and `Verdict` and its parts are frozen dataclasses with tuples.

### RNF-05 — The criterion cannot drift from the text

- **Given** the thresholds
  **When** the rules are reported
  **Then** the "needed" column and the explanation are built from the same constants the rules use,
  never retyped, and a test asserts it.

### RNF-06 — Synthetic fixtures only

- **Given** the tests and the docs
  **When** they need a report, an address or a domain
  **Then** they use the documentation ranges and domains of 004 RNF-07. No real report, IP or
  domain of the maintainer enters the repository.

### RNF-07 — Fits the Python floor

- **Given** the Python floor `3.12`
  **When** the layer is written
  **Then** it uses nothing newer, and the CI matrix passes.

## Open questions

None. Questions 1 to 6 were answered on 2026-10-28 (the maintainer approved the recommendations)
and are Resolved decisions 1 to 6. The second half of question 2 (a single large unrecognized
source failing rule 5 on its own) had no recommendation; the design settles it (Resolved decision 7).

## Resolved decisions

1. **The data thresholds** are 28 days spanned, 80% of those days with a report and 1000 messages.
   A domain that sends little stays `too early` until it has enough traffic; that is the honest
   answer, since a percentage over a handful of messages proves nothing.
2. **Rule 5 allows at most 0.5% of all messages** failing from unrecognized sources. Zero would
   punish every public domain that is spoofed daily, which is what `reject` is for.
3. **The thresholds are constants, not configuration.** Every verdict means the same thing
   everywhere and outputs can be compared; revisit if real use shows a domain that cannot fit.
4. **Exit codes** are `0` ready, `3` too early, `4` not ready, so a script can tell "wait" from
   "no". Provisional until spec `006`.
5. **A sibling command**, `mailvigil verdict`; `summary` stays a description and the verdict an
   opinion.
6. **Recognized failures with a `forwarded` or `mailing_list` reason still fail rule 4**, with the
   reason shown. The receiver said the message would have been blocked; the owner decides.
7. **Rule 5 is a share of the total, with no per-source limit** (design ADR-3). The sources are
   named in the reason, so a large one is seen; a second threshold would be a sixth rule with no
   evidence behind its number.

## Tests

Following [specs/README.md](../README.md#how-a-spec-is-tested):

- **Unit tests, no CLI:** `judge` is called with built `Summary` values; every rule, boundary,
  verdict and note is asserted on values.
- **The CLI through `main(argv)` and `capsys`:** the sections of the output, the standard error on
  each refusal and the exit codes; reports are synthetic files in `tmp_path`.
- **Synthetic only** (RNF-06).
- **Quality gate last:** `ruff` → `black --check` → `mypy` → `pytest --cov`, with its real result
  recorded in `tasks.md`.
