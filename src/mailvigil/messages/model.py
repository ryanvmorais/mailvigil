"""
The shape of the catalog: every sentence MailVigil writes, as typed templates.

A language is one ``Messages`` value whose fields are ``str.format`` templates, ``Plural`` phrases
or mappings keyed by an enum. Both languages build the same dataclasses, so a missing or misspelled
message is a type error and a ``TypeError`` on import, never a bare key in the output (spec 006
ADR-3). A template carries a whole sentence, so a language keeps its own word order; the layout (the
columns, the wrapping, the limits) stays in the renderers. Nothing here imports a renderer.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from mailvigil.config import ConfigReason
from mailvigil.fetch.errors import FetchReason
from mailvigil.reports import Reason
from mailvigil.senders import Outcome
from mailvigil.verdict import Answer, NoteKind, RuleId

# ---------------------------------------------------------------------------
# Plural
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Plural:
    """
    A phrase with a count in it, in its two forms.

    The whole phrase is stored, not the noun, so a language whose other words agree with the count
    ("1 arquivo ignorado", "2 arquivos ignorados") needs no other rule.

    Attributes:
        one (str): The template used for exactly 1. ``{n}`` is the count.
        many (str): The template used for any other count, zero included.
    """

    one: str
    many: str

    def of(self, number: int, **values: str | int) -> str:
        """
        Write the phrase for a count.

        Args:
            number (int): The count; it fills ``{n}``.
            **values (str | int): The other placeholders of the template.

        Returns:
            str: The singular for exactly 1, the plural otherwise.
        """
        template = self.one if number == 1 else self.many
        return template.format(n=number, **values)


# ---------------------------------------------------------------------------
# Areas
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CommonMessages:
    """
    What both commands say.

    Attributes:
        day (Plural): ``{n}`` days.
        message (Plural): ``{n}`` messages.
        failing_message (Plural): ``{n}`` failing messages.
        other_source (Plural): ``{n}`` other sources, for a list that was cut.
        no_address (str): What a source with no address is called.
        kinds (Mapping[Outcome, str]): How a source that was not recognized is described. ``KNOWN``
            has no entry: it is named by its service.
        selectors_named (Plural): The configured selectors involved in a failing source;
            ``{names}`` is the list.
        more_failing (str): The line that still counts the failing sources a list left out;
            ``{sources}`` and ``{messages}``.
    """

    day: Plural
    message: Plural
    failing_message: Plural
    other_source: Plural
    no_address: str
    kinds: Mapping[Outcome, str]
    selectors_named: Plural
    more_failing: str


@dataclass(frozen=True, slots=True)
class SummaryMessages:
    """
    What ``summary`` says, and the left-out block the no-reports message shares.

    Attributes:
        title (str): The first line; ``{domain}``.
        key_config (str): The label of the configuration line.
        key_period (str): The label of the period line.
        key_reports (str): The label of the reports line.
        key_policy (str): The label of the policy line.
        key_messages (str): The label of the messages line.
        config_none (str): The configuration line when no file was used.
        selector (Plural): ``{n}`` selectors configured.
        no_selectors (str): The note under the configuration line when no selector is mapped.
        no_selectors_hint (str): Where to read about the configuration.
        no_period (str): The period line when there are no reports.
        period (Plural): The period line, counted by the days with a report (``{n}``); ``{first}``,
            ``{last}`` and ``{days}``, the phrase of the days spanned.
        reporter (Plural): ``{n}`` reporters.
        reports_line (str): The reports line; ``{reports}`` and ``{reporters}``.
        policy_none (str): The policy line when none was published.
        policy_changed (str): The note under the policy line; ``{earlier}``.
        messages_line (str): The messages line; ``{total}``, ``{recognized}`` and ``{share}``.
        situations_title (str): The title of the situations block.
        col_ok (str): The name of the messages that pass.
        col_fragile (str): The name of the messages that pass by one mechanism only.
        col_failing (str): The name of the messages that fail.
        col_total (str): The header of the total column.
        senders_title (str): The title of the senders table.
        col_sender (str): The header of the label column.
        no_messages (str): The senders table when nothing was counted.
        senders_more (str): The line that counts the rows a table left out; ``{sources}``,
            ``{messages}`` and ``{failing}``.
        unrecognized_who (str): How a failing source that is not recognized is named; ``{kind}``.
        mechanism_none (str): The DKIM or SPF result when the report has none.
        source_detail (str): The second line of a failing source; ``{messages}``, ``{dkim}`` and
            ``{spf}``.
        source (Plural): ``{n}`` sources.
        no_failures (str): The failures section when there is none.
        failing_title (str): The first line of the failures section; ``{messages}`` and
            ``{sources}``.
        failing_recognized (str): The title of the recognized group.
        failing_unrecognized (str): The title of the unrecognized group.
        left_out_title (str): The title of the left-out block.
        key_skipped (str): The label of the skipped files.
        key_duplicates (str): The label of the duplicates.
        key_other_domains (str): The label of the reports of other domains.
        key_passed_over (str): The label of the files a folder search passed over by name.
        reasons (Mapping[Reason, str]): One phrase per refusal of a file.
        skipped_more (str): The line that counts the files a list left out; ``{n}``.
    """

    title: str
    key_config: str
    key_period: str
    key_reports: str
    key_policy: str
    key_messages: str
    config_none: str
    selector: Plural
    no_selectors: str
    no_selectors_hint: str
    no_period: str
    period: Plural
    reporter: Plural
    reports_line: str
    policy_none: str
    policy_changed: str
    messages_line: str
    situations_title: str
    col_ok: str
    col_fragile: str
    col_failing: str
    col_total: str
    senders_title: str
    col_sender: str
    no_messages: str
    senders_more: str
    unrecognized_who: str
    mechanism_none: str
    source_detail: str
    source: Plural
    no_failures: str
    failing_title: str
    failing_recognized: str
    failing_unrecognized: str
    left_out_title: str
    key_skipped: str
    key_duplicates: str
    key_other_domains: str
    key_passed_over: str
    reasons: Mapping[Reason, str]
    skipped_more: str


@dataclass(frozen=True, slots=True)
class VerdictMessages:
    """
    What ``verdict`` says.

    Attributes:
        title (str): The domain part of the first line; ``{domain}``.
        enforcing (str): The phrase when the policy is already ``p=reject``; ``{words}``.
        words (Mapping[Answer, str]): The answer, as the title says it.
        words_enforcing (Mapping[Answer, str]): The answer under ``p=reject``.
        rule_names (Mapping[RuleId, str]): One short name per rule.
        why_label (str): The label that opens the reason, without the colon-space after it.
        why_ready (str): The reason for ``ready``.
        still_failing (str): The line before the unrecognized sources a ``ready`` verdict allows.
        why_too_early (str): The reason for ``too early``.
        no_report_kept (str): The detail of ``too early`` when no report was kept.
        need_days (Plural): ``need {n} more days``.
        need_messages (Plural): ``need {n} more messages``.
        why_recognized (str): The reason when a recognized sender fails.
        why_unrecognized (str): The reason when the unrecognized failures are over the limit;
            ``{share}``, ``{measured}``, ``{whole}`` and ``{limit}``.
        recognized_tail (str): The end of a recognized source's line; ``{messages}`` and
            ``{where}``.
        other_tail (str): The end of an unrecognized source's line; ``{kind}`` and ``{messages}``.
        rules_title (str): The title of the rules table.
        col_rule (str): The header of the rule column.
        col_measured (str): The header of the measured column.
        col_needed (str): The header of the needed column.
        col_result (str): The header of the result column.
        measured_coverage (str): What rule 2 measured; ``{measured}``, ``{whole}`` and ``{share}``.
        result_pass (str): The result of a rule that passes.
        result_fail (str): The result of a problem rule that fails.
        result_too_early (str): The result of a data rule that fails.
        notes_title (str): The title of the notes.
        notes (Mapping[NoteKind, str]): One sentence per note; each kind has its own placeholders.
        next_label (str): The label that opens the next step, without the colon-space after it.
        next_each_service (str): What names the services when more than one fails.
        next_recognized (str): The next step when a recognized sender fails; ``{who}``.
        next_unrecognized (str): The next step when unrecognized failures are over the limit.
        next_data (str): The next step when there is not enough data; ``{marker}`` is the result
            word of a data rule that fails.
        skipped_file (Plural): ``{n}`` files skipped.
        duplicate (Plural): ``{n}`` duplicates.
        other_domain (Plural): ``{n}`` reports of another domain.
        passed_over (Plural): ``{n}`` files passed over by name.
        left_out (str): The sentence about what was not counted; ``{parts}``.
        caveat (str): The sentence that closes every verdict.
    """

    title: str
    enforcing: str
    words: Mapping[Answer, str]
    words_enforcing: Mapping[Answer, str]
    rule_names: Mapping[RuleId, str]
    why_label: str
    why_ready: str
    still_failing: str
    why_too_early: str
    no_report_kept: str
    need_days: Plural
    need_messages: Plural
    why_recognized: str
    why_unrecognized: str
    recognized_tail: str
    other_tail: str
    rules_title: str
    col_rule: str
    col_measured: str
    col_needed: str
    col_result: str
    measured_coverage: str
    result_pass: str
    result_fail: str
    result_too_early: str
    notes_title: str
    notes: Mapping[NoteKind, str]
    next_label: str
    next_each_service: str
    next_recognized: str
    next_unrecognized: str
    next_data: str
    skipped_file: Plural
    duplicate: Plural
    other_domain: Plural
    passed_over: Plural
    left_out: str
    caveat: str


@dataclass(frozen=True, slots=True)
class RefusalMessages:
    """
    The lines of a run that cannot start, and the no-reports explanation.

    Attributes:
        no_domain (str): No ``--domain`` and no configuration file; ``{default}`` is the file name
            looked for in the current folder.
        domain_mismatch (str): ``--domain`` and the file name different domains; ``{wanted}``,
            ``{domain}`` and ``{path}``.
        config_reasons (Mapping[ConfigReason, str]): The phrase of each configuration refusal.
        config_detail (frozenset[ConfigReason]): The refusals whose detail, which ``config.py``
            writes in English, is kept after the phrase and the key.
        no_reports (str): The first line of the no-reports explanation; ``{domain}``.
        no_file_found (str): The line when no report file was found at all.
        no_file_hint (str): How a folder is searched, and how to read a renamed file or a subfolder.
        output_failed (str): ``--output`` could not write the page; ``{path}`` and ``{reason}``,
            the system's own words for it.
    """

    no_domain: str
    domain_mismatch: str
    config_reasons: Mapping[ConfigReason, str]
    config_detail: frozenset[ConfigReason]
    no_reports: str
    no_file_found: str
    no_file_hint: str
    output_failed: str


@dataclass(frozen=True, slots=True)
class FetchMessages:
    """
    What ``fetch`` says (spec 009): the outcome of a run and the phrase of each refusal.

    Attributes:
        title (str): The first line of the outcome.
        key_matched (str): The label of the messages the search listed.
        key_saved (str): The label of the messages written in this run.
        key_already (str): The label of the messages already on disk.
        key_too_large (str): The label of the messages over the size cap.
        key_skipped (str): The label of the messages that could not be used.
        key_left (str): The label of the new messages left for a later run.
        key_directory (str): The label of the folder the messages were saved in.
        saved_before_stop (Plural): The second line of a refusal after some work; ``{n}`` is the
            files saved, which are valid.
        password_file_exposed (str): The warning for a password file other users can read;
            ``{path}`` is the file as the user typed it.
        reasons (Mapping[FetchReason, str]): One phrase per refusal of a run.
    """

    title: str
    key_matched: str
    key_saved: str
    key_already: str
    key_too_large: str
    key_skipped: str
    key_left: str
    key_directory: str
    saved_before_stop: Plural
    password_file_exposed: str
    reasons: Mapping[FetchReason, str]


@dataclass(frozen=True, slots=True)
class HtmlMessages:
    """
    What only the HTML report says (spec 008). Every sentence the text format already has (rule
    names, answers, reasons, notes, left-out) is read from the other areas, never repeated here.

    Attributes:
        lang (str): The language code of the ``lang`` attribute of the page.
        page_title (str): The title of the page; ``{domain}``.
        eyebrow (str): The small line above the answer.
        policy_label (str): The accessible name of the published-policy box.
        rules_title (str): The title of the rules section.
        group_data (str): The title of the group of data rules.
        group_problem (str): The title of the group of problem rules.
        meter_legend (str): What the dark mark on a meter is.
        at_least (str): The limit of an "at least" rule; ``{value}``.
        at_most (str): The limit of an "at most" rule; ``{value}``.
        none_allowed (str): The limit of a rule that allows nothing.
        meter_label (str): The accessible name of a meter; ``{name}``, ``{measured}`` and
            ``{needed}``.
        of_messages (Plural): ``of {n} messages``, after a share.
        mix_title (Plural): The title of the mix of messages; ``{n}`` is all of them.
        situation_ok (str): The messages where DKIM and SPF both pass.
        situation_dkim (str): The messages where only DKIM passes.
        situation_spf (str): The messages where only SPF passes.
        situation_failing (str): The messages where neither passes.
        situation_label (str): One situation in an accessible name; ``{name}``, ``{count}`` and
            ``{share}``.
        days_title (str): The title of the timeline.
        column_note (Plural): What a column is and on which day a report counts; ``{n}`` is the
            days in a column.
        legend_failing_day (str): The key of the mark above a column with failing messages.
        legend_no_report (str): The key of a day with no report.
        legend_covered (str): The key of a day a report covers but does not count on.
        scale_note (str): How to read the height of a column; ``{tallest}``.
        timeline_label (Plural): The accessible name of the timeline; ``{n}`` is the columns,
            ``{first}``, ``{last}`` and ``{failing}`` (the columns with failing messages).
        show_numbers (str): The summary of the table behind the timeline.
        numbers_region (str): The accessible name of that table.
        senders_region (str): The accessible name of the senders table.
        other_sender (Plural): ``{n}`` senders the table does not list.
        senders_more (str): The line after a table that left rows out; ``{senders}`` and
            ``{messages}``.
        failing_heading (str): The title of the failing-sources block.
        next_each_service (str): ``VerdictMessages.next_each_service`` for the page, where the
            sources come after the next step, not before it.
        next_unrecognized (str): ``VerdictMessages.next_unrecognized`` for the page, same reason.
        col_day (str): The header of the day column.
        range_label (str): A column of several days; ``{first}`` and ``{last}``.
        footer (str): The last line; ``{version}``.
    """

    lang: str
    page_title: str
    eyebrow: str
    policy_label: str
    rules_title: str
    group_data: str
    group_problem: str
    meter_legend: str
    at_least: str
    at_most: str
    none_allowed: str
    meter_label: str
    of_messages: Plural
    mix_title: Plural
    situation_ok: str
    situation_dkim: str
    situation_spf: str
    situation_failing: str
    situation_label: str
    days_title: str
    column_note: Plural
    legend_failing_day: str
    legend_no_report: str
    legend_covered: str
    scale_note: str
    timeline_label: Plural
    show_numbers: str
    numbers_region: str
    senders_region: str
    other_sender: Plural
    senders_more: str
    failing_heading: str
    next_each_service: str
    next_unrecognized: str
    col_day: str
    range_label: str
    footer: str


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Messages:
    """
    Everything MailVigil writes, in one language.

    Attributes:
        common (CommonMessages): What both commands say.
        summary (SummaryMessages): What ``summary`` says.
        verdict (VerdictMessages): What ``verdict`` says.
        refusals (RefusalMessages): The refusal lines and the no-reports explanation.
        fetch (FetchMessages): What ``fetch`` says.
        html (HtmlMessages): What only the HTML report says.
    """

    common: CommonMessages
    summary: SummaryMessages
    verdict: VerdictMessages
    refusals: RefusalMessages
    fetch: FetchMessages
    html: HtmlMessages
