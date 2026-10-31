"""
The English text of MailVigil.

Moved out of ``render.py``, ``render_verdict.py`` and ``cli.py`` without rewriting a word, so the
output is byte-equal to what the renderers wrote before the catalog existed (spec 006 stage 2,
RNF-02). Every number inside a sentence (a threshold, a count) is a placeholder, filled from the
constants the rules use, never typed here (RNF-05).
"""

from __future__ import annotations

from types import MappingProxyType

from mailvigil.config import ConfigReason
from mailvigil.fetch.errors import FetchReason
from mailvigil.messages.model import (
    CommonMessages,
    FetchMessages,
    HtmlMessages,
    Messages,
    Plural,
    RefusalMessages,
    SummaryMessages,
    VerdictMessages,
)
from mailvigil.reports import Reason
from mailvigil.senders import Outcome
from mailvigil.verdict import Answer, NoteKind, RuleId

# ---------------------------------------------------------------------------
# Common
# ---------------------------------------------------------------------------

# What both commands say; the nouns and the source kinds the two renderers shared.
_COMMON = CommonMessages(
    day=Plural("{n} day", "{n} days"),
    message=Plural("{n} message", "{n} messages"),
    failing_message=Plural("{n} failing message", "{n} failing messages"),
    other_source=Plural("{n} other source", "{n} other sources"),
    no_address="no address",
    # A test iterates ``Outcome``, so a kind added later cannot reach the output as a bare key.
    kinds=MappingProxyType(
        {
            Outcome.UNKNOWN: "unrecognized",
            Outcome.FOREIGN_DOMAIN: "foreign domain",
            Outcome.FAILING_SIGNATURE: "failing signature",
        }
    ),
    selectors_named=Plural("selector {names}", "selectors {names}"),
    more_failing="... and {sources}: {messages}",
)

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

# What ``summary`` says, moved from ``render.py``; the left-out block is shared with the
# no-reports message.
_SUMMARY = SummaryMessages(
    title="MailVigil summary for {domain}",
    key_config="config",
    key_period="period",
    key_reports="reports",
    key_policy="policy",
    key_messages="messages",
    config_none="none",
    selector=Plural("{n} selector", "{n} selectors"),
    no_selectors="no selectors are configured, so every sender is unrecognized",
    no_selectors_hint="(see the Configuration section of the README)",
    no_period="no reports",
    period=Plural(
        "{first} to {last} ({n} of {days} has a report)",
        "{first} to {last} ({n} of {days} have a report)",
    ),
    reporter=Plural("{n} reporter", "{n} reporters"),
    reports_line="{reports} from {reporters}",
    policy_none="none",
    policy_changed="changed during the period, earlier p: {earlier}",
    messages_line="{total} ({recognized} from recognized senders, {share})",
    situations_title="Situations",
    col_ok="ok",
    col_fragile="fragile",
    col_failing="failing",
    col_total="total",
    senders_title="Senders",
    col_sender="sender",
    no_messages="no messages counted",
    senders_more="... and {sources}: {messages}, {failing} failing",
    unrecognized_who="unrecognized, {kind}",
    mechanism_none="none",
    source_detail="{messages}  dkim: {dkim}, spf: {spf}",
    source=Plural("{n} source", "{n} sources"),
    no_failures="No failing messages.",
    failing_title="! FAILING: {messages} in {sources}",
    failing_recognized="Recognized senders that fail",
    failing_unrecognized="Unrecognized sources that fail",
    left_out_title="Left out of these numbers",
    key_skipped="skipped files",
    key_duplicates="duplicates",
    key_other_domains="other domains",
    key_passed_over="passed over by name",
    # One phrase per refusal. A test iterates ``Reason``, so a reason added by a later spec cannot
    # reach the output as a bare key.
    reasons=MappingProxyType(
        {
            Reason.UNSUPPORTED_EXTENSION: "unsupported file type",
            Reason.UNREADABLE: "could not be read",
            Reason.FILE_TOO_LARGE: "too large",
            Reason.DECOMPRESSED_TOO_LARGE: "too large once decompressed",
            Reason.NOT_AN_ARCHIVE: "not a valid archive",
            Reason.NO_XML_MEMBER: "no XML file inside",
            Reason.MULTIPLE_XML_MEMBERS: "more than one XML file inside",
            Reason.FORBIDDEN_DECLARATION: "unsafe XML (DOCTYPE or ENTITY)",
            Reason.MALFORMED_XML: "malformed XML",
            Reason.NOT_A_REPORT: "not a DMARC report",
            Reason.UNSUPPORTED_VERSION: "unsupported report version",
            Reason.INVALID_FIELD: "invalid value in the report",
            Reason.MESSAGE_TOO_LARGE: "message too large",
            Reason.MESSAGE_TOO_COMPLEX: "message too complex",
            Reason.NO_REPORT_ATTACHMENT: "no report attached",
            Reason.MALFORMED_MESSAGE: "malformed message",
            Reason.XML_TOO_COMPLEX: "XML too complex",
        }
    ),
    skipped_more="... and {n} more",
)

# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

# What ``verdict`` says, moved from ``render_verdict.py``.
_VERDICT = VerdictMessages(
    title="MailVigil verdict for {domain}",
    enforcing="already at p=reject: {words}",
    # The title words. A test iterates ``Answer``, so an answer added later cannot reach the output
    # as a bare key.
    words=MappingProxyType(
        {
            Answer.READY: "READY for p=reject",
            Answer.TOO_EARLY: "TOO EARLY to say",
            Answer.NOT_READY: "NOT READY for p=reject",
        }
    ),
    words_enforcing=MappingProxyType(
        {
            Answer.READY: "NO PROBLEM SEEN",
            Answer.TOO_EARLY: "TOO EARLY to say",
            Answer.NOT_READY: "BLOCKING REAL MAIL",
        }
    ),
    # One name per rule, short so the table fits in 80 columns beside a share and a count.
    rule_names=MappingProxyType(
        {
            RuleId.PERIOD: "period covered",
            RuleId.COVERAGE: "days with a report",
            RuleId.VOLUME: "messages seen",
            RuleId.RECOGNIZED_FAILURES: "recognized failures",
            RuleId.UNRECOGNIZED_FAILURES: "unrecognized failures",
        }
    ),
    why_label="Why:",
    why_ready="every rule passes.",
    still_failing="Still failing from unrecognized sources, under the limit:",
    why_too_early="not enough reports to tell yet.",
    no_report_kept="no report was kept for this domain",
    need_days=Plural("need {n} more day", "need {n} more days"),
    need_messages=Plural("need {n} more message", "need {n} more messages"),
    why_recognized="a recognized sender fails DMARC.",
    why_unrecognized=(
        "failures from unrecognized sources are {share} of the messages ({measured} of "
        "{whole}); the limit is {limit}."
    ),
    recognized_tail=": {messages} from {where}",
    other_tail="  {kind}: {messages}",
    rules_title="Rules",
    col_rule="rule",
    col_measured="measured",
    col_needed="needed",
    col_result="result",
    measured_coverage="{measured} of {whole} ({share})",
    result_pass="pass",
    result_fail="FAIL",
    result_too_early="fail (too early)",
    notes_title="Notes",
    notes=MappingProxyType(
        {
            NoteKind.FRAGILE: (
                "Fragile traffic: {fragile} of {total} messages ({share}) pass by only one of "
                "DKIM and SPF; {spf_only} of those by SPF only, which forwarding breaks."
            ),
            NoteKind.PARTIAL_POLICY: "The policy applies to only {pct}% of the mail (pct={pct}).",
            NoteKind.POLICY_CHANGED: (
                "The policy changed during the period (earlier p: {earlier}), so the figures "
                "mix policies."
            ),
            NoteKind.SUBDOMAIN_POLICY: (
                "Subdomains have their own policy ({shown}): moving p does not change it."
            ),
            NoteKind.CURRENTLY_QUARANTINE: (
                "The policy is p=quarantine now; this verdict is about moving to p=reject."
            ),
            NoteKind.SILENT_REPORTER: (
                "{name} sent {share} of the messages but nothing in the last {days} days; the "
                "days it missed may look covered by other reporters."
            ),
            NoteKind.STALE: (
                "The latest report ended {days} days ago, so the figures may not describe the "
                "mail you send today."
            ),
        }
    ),
    next_label="Next:",
    next_each_service="each service listed above",
    next_recognized=(
        "make {who} sign with your domain (DKIM) or add its servers to SPF, then collect "
        "another period."
    ),
    next_unrecognized=(
        "look at the sources above and add the selectors of the ones that are yours to "
        "[senders] in the configuration."
    ),
    next_data="keep collecting reports until the rules marked '{marker}' pass.",
    skipped_file=Plural("{n} file skipped", "{n} files skipped"),
    duplicate=Plural("{n} duplicate", "{n} duplicates"),
    other_domain=Plural("{n} report of another domain", "{n} reports of other domains"),
    passed_over=Plural("{n} file passed over by name", "{n} files passed over by name"),
    left_out="Left out of this verdict: {parts}. mailvigil summary shows why.",
    caveat=(
        "This reads only the reports you gave it: mail that no receiver reports on, and "
        "senders that were quiet in this period, are not covered."
    ),
)

# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------

# The refusal lines of ``cli.py`` and the no-reports explanation of ``render.py``.
_REFUSALS = RefusalMessages(
    no_domain="pass --domain or --config (or put a {default} in this folder)",
    domain_mismatch="--domain {wanted} does not match the domain {domain} of {path}",
    # 003's own words: the line a configuration refusal has always had, which ``str(error)`` writes.
    config_reasons=MappingProxyType({reason: reason.value for reason in ConfigReason}),
    config_detail=frozenset(ConfigReason),
    no_reports="No DMARC report for {domain} was kept.",
    no_file_found="No report file was found. A folder is searched only for names like",
    no_file_hint="provider!domain!begin!end.zip; try --recursive, or name the file itself.",
    output_failed="could not write {path}: {reason}",
)

# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

# Many free mail plans have no IMAP, and a provider that has it off answers like a bad login or no
# server at all, so the two phrases that look that way say what to do instead.
_IMAP_HINT = (
    "; your provider must allow IMAP, otherwise download the reports by hand and use summary"
)

# What ``fetch`` prints. One phrase per reason: a test iterates ``FetchReason``, so a reason added
# later cannot go without a sentence in both languages. A refused login carries no server text.
_FETCH = FetchMessages(
    title="Report messages fetched from the mailbox.",
    key_matched="Matched:",
    key_saved="Saved:",
    key_already="Already saved:",
    key_too_large="Too large:",
    key_skipped="Skipped:",
    key_left="Left for later:",
    key_directory="Saved in:",
    saved_before_stop=Plural(
        "{n} message was saved before it stopped.",
        "{n} messages were saved before it stopped.",
    ),
    password_file_exposed="warning: {path} can be read by other users; run chmod 600 on it",
    reasons=MappingProxyType(
        {
            FetchReason.HOST_UNREACHABLE: f"could not reach the server{_IMAP_HINT}",
            FetchReason.TIMEOUT: "the server took too long to answer",
            FetchReason.DEADLINE_EXCEEDED: "the run took too long and was stopped",
            FetchReason.CERTIFICATE_INVALID: "the server certificate was not accepted",
            FetchReason.TLS_FAILED: "could not open a secure connection",
            FetchReason.LOGIN_FAILED: (
                f"the server refused the user name or the password{_IMAP_HINT}"
            ),
            FetchReason.PASSWORD_UNUSABLE: (
                "the password is empty, has a line break or a control character, or the login has "
                "characters outside ASCII that the server does not accept"
            ),
            FetchReason.PASSWORD_FILE: "could not read a password from the file",
            FetchReason.CAFILE_UNUSABLE: (
                "could not read a certificate authority from the --cafile file"
            ),
            FetchReason.FOLDER_NOT_FOUND: "the folder was not found",
            FetchReason.PROTOCOL_ERROR: "the server sent an answer that could not be used",
            FetchReason.TOO_MANY_MATCHES: "too many messages matched; narrow it with --since",
            FetchReason.WRITE_FAILED: "could not write to the folder",
        }
    ),
)

# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

# What only the HTML report says; the rest of the page reads the areas above.
_HTML = HtmlMessages(
    lang="en",
    page_title="DMARC report for {domain}",
    eyebrow="Ready for p=reject?",
    policy_label="Published policy",
    rules_title="The five rules behind the answer",
    group_data="Is there enough evidence?",
    group_problem="Is anything wrong?",
    meter_legend="The dark mark is the limit of each rule.",
    at_least="at least {value} needed",
    at_most="at most {value} allowed",
    none_allowed="none allowed",
    meter_label="{name}: {measured}, {needed}",
    of_messages=Plural("of {n} message", "of {n} messages"),
    mix_title=Plural("What happened to the {n} message", "What happened to the {n} messages"),
    situation_ok="Pass both",
    situation_dkim="DKIM only",
    situation_spf="SPF only",
    situation_failing="Failing",
    situation_label="{name}: {count} ({share})",
    days_title="Day by day",
    column_note=Plural(
        "Each column is one day, in UTC. A report counts on the day it begins.",
        "Each column is {n} days, in UTC. A report counts on the day it begins.",
    ),
    legend_failing_day="Day with failing messages",
    legend_no_report="No report",
    legend_covered="Covered by a report that counts on another day",
    scale_note=(
        "Taller column, more messages. The tallest column had {tallest}. "
        "Failing messages sit at the base of each column."
    ),
    timeline_label=Plural(
        "Messages per day from {first} to {last}: {n} column, {failing} with failing messages.",
        "Messages per day from {first} to {last}: {n} columns, {failing} with failing messages.",
    ),
    show_numbers="Show the numbers",
    numbers_region="Messages per day",
    senders_region="Senders table",
    other_sender=Plural("{n} other sender", "{n} other senders"),
    senders_more=(
        "Not listed here: {senders} ({messages}). mailvigil summary --json lists every sender."
    ),
    failing_heading="Failing sources",
    next_each_service="each service listed below",
    next_unrecognized=(
        "look at the sources below and add the selectors of the ones that are yours to "
        "[senders] in the configuration."
    ),
    col_day="Day",
    range_label="{first} to {last}",
    footer=(
        "Generated offline by MailVigil {version}. "
        "This file has no scripts and makes no network requests."
    ),
)

# ---------------------------------------------------------------------------
# The catalog
# ---------------------------------------------------------------------------

ENGLISH = Messages(
    common=_COMMON,
    summary=_SUMMARY,
    verdict=_VERDICT,
    refusals=_REFUSALS,
    fetch=_FETCH,
    html=_HTML,
)
