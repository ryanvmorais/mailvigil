# JSON output reference

`mailvigil summary --json`, `mailvigil verdict --json` and `mailvigil fetch --json` print one JSON
document on standard output, a newline, and nothing on standard error. This page lists every field,
the promise about how the fields may change, and one example per command. The examples are the real
output for invented data, and a test compares them with the code, so this page cannot drift from it.

## The promise

- Every document starts with `schema_version` (an integer, `1` today) and `command`. The `summary`
  and `verdict` documents go on with `domain`; the `fetch` document is about a mailbox and has none.
- A field is only **added** inside a `schema_version`; a consumer must ignore keys it does not know.
- A field is **renamed, removed or given another type** only with a new `schema_version`.
- Keys come in a fixed order, and lists come in the order stated below; the same reports give the
  same bytes, in any order of files, with no timestamp and no path of the machine.
- The document is data: integers, booleans, identifiers and values copied from the reports (already
  sanitized). It has no sentence, no language and no rounded percentage: a share is the two integers
  it is made of, and the threshold.
- A value the model may not have is `null`, never missing and never an empty string.
- Non-ASCII characters are written as `\uXXXX` escapes, so the text is ASCII whatever the console.
- `--json` does not change the exit code, and neither will `--lang`.

## Exit codes

| Code | Meaning | Commands |
|---|---|---|
| `0` | An answer was printed; for `verdict`, the answer is `ready`; for `fetch`, the run finished, even with nothing new | all |
| `1` | The run was refused: invalid configuration or domain, no report kept, or (for `fetch`) a connection or login refusal | all |
| `2` | Usage error | all |
| `3` | `verdict` printed `too early` | `verdict` |
| `4` | `verdict` printed `not ready` | `verdict` |
| `70` | Internal error (a bug); one line on standard error, no document | all |
| `130` | Interrupted with Ctrl+C; no document | all |
| `141` | The output pipe was closed | all |

A refused run (`1`) prints no document: standard output is empty and the one line goes to standard
error. A `too early` or `not ready` verdict still prints the full document.

## The `summary` document

### `summary`

The keys, in order.

| Key | Type | Meaning |
|---|---|---|
| `schema_version` | integer | `1` |
| `command` | string | `"summary"` |
| `domain` | string | The domain the reports are about |
| `config` | object | See `summary.config` |
| `reports` | object | See `summary.reports` |
| `period` | object or null | See `period`; null without reports |
| `policy` | object or null | See `policy`; null without reports |
| `earlier_p` | list of strings | Other `p` values seen in the period, oldest first |
| `totals` | object | See `counts`: all the messages |
| `recognized_messages` | integer | Messages of recognized senders |
| `senders` | list of `sender` | Every row, the biggest first, with no display limit unless `--top` is given |
| `failing` | list of `source` | Every failing source, the worst first, with no display limit unless `--top` is given |
| `skipped` | list of `skipped` | The refused files, ordered by path |
| `skipped_by_reason` | list of `skipped_by_reason` | The refusals per reason, the most frequent first |
| `duplicates` | integer | Reports dropped as already seen |
| `other_domain` | integer | Reports dropped for belonging to another domain |
| `passed_over` | integer | Files a folder search did not read because the name is not a provider's, although the suffix is `.zip`, `.gz` or `.xml` |

### `summary.config`

| Key | Type | Meaning |
|---|---|---|
| `source` | string or null | The configuration file as typed on the command line; null when there was none |
| `selectors` | integer | How many DKIM selectors the configuration maps |
| `spf_domains` | integer | How many SPF domains the configuration maps |
| `ip_ranges` | integer | How many address ranges the configuration maps |

### `summary.reports`

| Key | Type | Meaning |
|---|---|---|
| `count` | integer | The reports kept |
| `reporters` | integer | The distinct reporting organizations |

### `period`

| Key | Type | Meaning |
|---|---|---|
| `first_day` | string | The first UTC day covered, `YYYY-MM-DD` |
| `last_day` | string | The last UTC day any report touches, `YYYY-MM-DD` |
| `days_spanned` | integer | `first_day` to `last_day`, inclusive |
| `days_with_reports` | integer | The days in that span that at least one report touches |

### `policy`

The policy published in the latest report.

| Key | Type | Meaning |
|---|---|---|
| `p` | string | The policy: `none`, `quarantine`, `reject` or `?` when the report does not say |
| `sp` | string or null | The subdomain policy; null when absent |
| `np` | string or null | The policy for non-existent subdomains; null when absent |
| `pct` | integer | The sampling percentage, 0 to 100 |

### `counts`

Messages per situation.

| Key | Type | Meaning |
|---|---|---|
| `ok` | integer | DKIM and SPF both passed |
| `dkim_only` | integer | Only DKIM passed |
| `spf_only` | integer | Only SPF passed |
| `failing` | integer | Neither passed |
| `total` | integer | The four together |

### `sender`

One row of the senders table.

| Key | Type | Meaning |
|---|---|---|
| `outcome` | string | `known`, `foreign_domain`, `failing_signature` or `unknown` |
| `service` | string or null | The service name when `known`, otherwise null |
| `source_ip` | string or null | The address when not `known`, otherwise null |
| `selectors` | list of strings | The configured selectors seen on a row that is not `known`, sorted |
| `spf_domains` | list of strings | The SPF domains that passed under your domain on a row that is not `known`, sorted: the ones `[spf]` could name |
| `counts` | object | See `counts` |

### `source`

One address whose messages failed. It is the same object in both documents.

| Key | Type | Meaning |
|---|---|---|
| `outcome` | string | What identification said, as in `sender` |
| `service` | string or null | The service name when `known`, otherwise null |
| `source_ip` | string | The address the failing messages came from |
| `messages` | integer | The failing messages, at least 1 |
| `selectors` | list of strings | The configured selectors seen on this source when it is not `known`, sorted |
| `spf_domains` | list of strings | The SPF domains that passed under your domain on this source when it is not `known`, sorted |
| `dkim` | list of strings | Why DKIM did not count, sorted: `fail`, `unaligned` or `none` |
| `spf` | list of strings | The same vocabulary for SPF |
| `override_reasons` | list of strings | The receiver's override types, sorted and unique |

### `skipped`

| Key | Type | Meaning |
|---|---|---|
| `name` | string | The file name, without its folder |
| `part` | string or null | For a mail file (`.eml`, `.mbox`), the message and the attachment that were refused, such as `#3 report.zip` (the number counts the messages of a mailbox from 1); null for a loose file |
| `reason` | string | Why it was refused, for example `malformed_xml`, `file_too_large` or `message_too_large` |

### `skipped_by_reason`

| Key | Type | Meaning |
|---|---|---|
| `reason` | string | A refusal reason |
| `count` | integer | How many files were refused for it |

## The `verdict` document

### `verdict`

The keys, in order.

| Key | Type | Meaning |
|---|---|---|
| `schema_version` | integer | `1` |
| `command` | string | `"verdict"` |
| `domain` | string | The domain the verdict is about |
| `answer` | string | `ready`, `too_early` or `not_ready`; the same whether or not the policy already enforces |
| `enforcing` | string or null | The latest published `p`; null without reports |
| `deciding` | string or null | The id of the rule that decided the answer; null exactly when `answer` is `ready` |
| `rules` | list of `rule` | Always five, in the order of the table below |
| `recognized_failing` | list of `source` | Every failing source of a recognized sender, the worst first (unless `--top` is given) |
| `unrecognized_failing` | list of `source` | Every other failing source, the worst first (unless `--top` is given) |
| `notes` | list of `note` | What is worth saying and does not change the answer |
| `left_out` | object | See `left_out` |

### `rule`

| Key | Type | Meaning |
|---|---|---|
| `id` | string | The stable word of the rule |
| `kind` | string | `data` (is there enough evidence) or `problem` (is something wrong already) |
| `measured` | integer | The value found |
| `whole` | integer | The denominator of a share; 0 when the rule is not a share |
| `needed` | integer | The threshold |
| `unit` | string | What `measured` and `needed` count |
| `comparison` | string | `at_least` or `at_most` |
| `passed` | boolean | Whether the rule passes |
| `missing` | integer | How much a failed data rule lacks, in days or messages; 0 otherwise |

The five rules, in order:

| `id` | `kind` | `unit` | `comparison` | `measured`, `whole`, `needed` |
|---|---|---|---|---|
| `period_covered` | `data` | `days` | `at_least` | days spanned, 0, days required |
| `days_with_report` | `data` | `percent_of_days` | `at_least` | days with a report, days spanned, percent required |
| `messages_seen` | `data` | `messages` | `at_least` | messages seen, 0, messages required |
| `recognized_failures` | `problem` | `messages` | `at_most` | failing messages of recognized senders, 0, 0 |
| `unrecognized_failures` | `problem` | `per_mille_of_messages` | `at_most` | failing messages of other sources, all messages, tenths of a percent allowed |

A share is `measured` over `whole`, compared with integers: rule 2 passes when
`100 * measured >= needed * whole`, and rule 5 when `1000 * measured <= needed * whole`.

### `note`

| Key | Type | Meaning |
|---|---|---|
| `kind` | string | `fragile`, `partial_policy`, `policy_changed`, `subdomain_policy`, `currently_quarantine`, `silent_reporter` or `stale` |
| `numbers` | list of integers | The figures of the note: `fragile` has fragile messages, those that pass by SPF only and all messages; `partial_policy` has `pct`; `silent_reporter` has the whole days a large reporter has been silent, its messages and all messages; `stale` has the whole days since the latest report ended |
| `texts` | list of strings or nulls | The words of the note: `policy_changed` has the earlier `p` values, oldest first; `subdomain_policy` has `sp` and `np`, with null for the one that is absent; `silent_reporter` has the reporter's name |

### `left_out`

What the summary did not count. It never changes the answer.

| Key | Type | Meaning |
|---|---|---|
| `skipped` | integer | Files that were refused |
| `duplicates` | integer | Reports dropped as already seen |
| `other_domain` | integer | Reports that belong to another domain |
| `passed_over` | integer | Files a folder search did not read because of their name |

## Trimming the lists with `--top N`

The document keeps every entry by default. `--top N` (a whole number of 1 or more, with `--json`) keeps the first `N`
entries of each long list, which are already the biggest or worst first: `senders` and `failing` in
the `summary` document, `recognized_failing` and `unrecognized_failing` in the `verdict` document.

A trimmed document gains one last key, `top`, an object with two keys: `limit`, the `N` that was
given, and `left_out`, an object with one integer for each trimmed list (the entries that were
dropped, `0` when the list was shorter than `N`). Without `--top` the key is absent and the document
is the same bytes as before the option existed, so a consumer that ignores keys it does not know
needs no change. Nothing outside the lists changes: the totals, the rules, the answer and the exit
code are computed from everything the reports said.

```json
"top": {"limit": 2, "left_out": {"senders": 4, "failing": 4}}
```

## The `fetch` document

`mailvigil fetch --json` replaces the text of a finished run with this document. A refused run
prints no document, as above; the files it had already saved are valid, and the one line on
standard error says how many there are. The document holds no host, user, folder or path.

### `fetch`

The keys, in order. The six numbers always add up: `matched` equals `saved + already + too_large +
skipped + left`.

| Key | Type | Meaning |
|---|---|---|
| `schema_version` | integer | `1` |
| `command` | string | `"fetch"` |
| `matched` | integer | Messages the server listed for the search, plus the tokens it sent that were not valid UIDs |
| `saved` | integer | Messages written in this run |
| `already` | integer | Messages found on disk by name and so not downloaded |
| `too_large` | integer | Messages over the size cap, announced or cut while arriving |
| `skipped` | integer | A UID that could not be used, or a message the server would not give |
| `left` | integer | New messages beyond `--limit` or the deadline, for a later run |

## Examples

All three use invented data: `example.com`, a made-up service and the documentation address ranges.

### A summary

```json
{
  "schema_version": 1,
  "command": "summary",
  "domain": "example.com",
  "config": {
    "source": "mailvigil.toml",
    "selectors": 1,
    "spf_domains": 0,
    "ip_ranges": 0
  },
  "reports": {
    "count": 29,
    "reporters": 2
  },
  "period": {
    "first_day": "2026-09-01",
    "last_day": "2026-09-29",
    "days_spanned": 29,
    "days_with_reports": 29
  },
  "policy": {
    "p": "none",
    "sp": "reject",
    "np": null,
    "pct": 100
  },
  "earlier_p": [],
  "totals": {
    "ok": 6300,
    "dkim_only": 975,
    "spf_only": 0,
    "failing": 48,
    "total": 7323
  },
  "recognized_messages": 6300,
  "senders": [
    {
      "outcome": "known",
      "service": "Example Mailer",
      "source_ip": null,
      "selectors": [],
      "spf_domains": [],
      "counts": {
        "ok": 6300,
        "dkim_only": 0,
        "spf_only": 0,
        "failing": 0,
        "total": 6300
      }
    },
    {
      "outcome": "known",
      "service": "Example Mail",
      "source_ip": null,
      "selectors": [],
      "spf_domains": [],
      "counts": {
        "ok": 0,
        "dkim_only": 950,
        "spf_only": 0,
        "failing": 0,
        "total": 950
      }
    },
    {
      "outcome": "unknown",
      "service": null,
      "source_ip": "203.0.113.5",
      "selectors": [],
      "spf_domains": [],
      "counts": {
        "ok": 0,
        "dkim_only": 0,
        "spf_only": 0,
        "failing": 40,
        "total": 40
      }
    },
    {
      "outcome": "failing_signature",
      "service": null,
      "source_ip": "198.51.100.99",
      "selectors": [
        "s1"
      ],
      "spf_domains": [],
      "counts": {
        "ok": 0,
        "dkim_only": 25,
        "spf_only": 0,
        "failing": 0,
        "total": 25
      }
    },
    {
      "outcome": "unknown",
      "service": null,
      "source_ip": "2001:db8::7",
      "selectors": [],
      "spf_domains": [],
      "counts": {
        "ok": 0,
        "dkim_only": 0,
        "spf_only": 0,
        "failing": 8,
        "total": 8
      }
    }
  ],
  "failing": [
    {
      "outcome": "unknown",
      "service": null,
      "source_ip": "203.0.113.5",
      "messages": 40,
      "selectors": [],
      "spf_domains": [],
      "dkim": [
        "fail"
      ],
      "spf": [
        "fail"
      ],
      "override_reasons": [
        "forwarded"
      ]
    },
    {
      "outcome": "unknown",
      "service": null,
      "source_ip": "2001:db8::7",
      "messages": 8,
      "selectors": [],
      "spf_domains": [],
      "dkim": [
        "none"
      ],
      "spf": [
        "none"
      ],
      "override_reasons": []
    }
  ],
  "skipped": [
    {
      "name": "broken.xml",
      "part": null,
      "reason": "malformed_xml"
    }
  ],
  "skipped_by_reason": [
    {
      "reason": "malformed_xml",
      "count": 1
    }
  ],
  "duplicates": 1,
  "other_domain": 0,
  "passed_over": 0
}
```

### A verdict

```json
{
  "schema_version": 1,
  "command": "verdict",
  "domain": "example.com",
  "answer": "not_ready",
  "enforcing": "none",
  "deciding": "unrecognized_failures",
  "rules": [
    {
      "id": "period_covered",
      "kind": "data",
      "measured": 29,
      "whole": 0,
      "needed": 28,
      "unit": "days",
      "comparison": "at_least",
      "passed": true,
      "missing": 0
    },
    {
      "id": "days_with_report",
      "kind": "data",
      "measured": 29,
      "whole": 29,
      "needed": 80,
      "unit": "percent_of_days",
      "comparison": "at_least",
      "passed": true,
      "missing": 0
    },
    {
      "id": "messages_seen",
      "kind": "data",
      "measured": 7006,
      "whole": 0,
      "needed": 100,
      "unit": "messages",
      "comparison": "at_least",
      "passed": true,
      "missing": 0
    },
    {
      "id": "recognized_failures",
      "kind": "problem",
      "measured": 0,
      "whole": 0,
      "needed": 0,
      "unit": "messages",
      "comparison": "at_most",
      "passed": true,
      "missing": 0
    },
    {
      "id": "unrecognized_failures",
      "kind": "problem",
      "measured": 56,
      "whole": 7006,
      "needed": 5,
      "unit": "per_mille_of_messages",
      "comparison": "at_most",
      "passed": false,
      "missing": 0
    }
  ],
  "recognized_failing": [],
  "unrecognized_failing": [
    {
      "outcome": "unknown",
      "service": null,
      "source_ip": "203.0.113.5",
      "messages": 56,
      "selectors": [],
      "spf_domains": [],
      "dkim": [
        "fail"
      ],
      "spf": [
        "fail"
      ],
      "override_reasons": [
        "forwarded"
      ]
    }
  ],
  "notes": [
    {
      "kind": "fragile",
      "numbers": [
        950,
        0,
        7006
      ],
      "texts": []
    },
    {
      "kind": "subdomain_policy",
      "numbers": [],
      "texts": [
        "reject",
        null
      ]
    }
  ],
  "left_out": {
    "skipped": 0,
    "duplicates": 0,
    "other_domain": 2,
    "passed_over": 0
  }
}
```

### A fetch

```json
{
  "schema_version": 1,
  "command": "fetch",
  "matched": 12,
  "saved": 9,
  "already": 2,
  "too_large": 0,
  "skipped": 0,
  "left": 1
}
```
