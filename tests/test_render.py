"""
Tests of the text of the summary: shares, helpers, the five sections, the 80-column layout and the
message for an empty result.

Isolation: nothing touches the disk and no command runs. Every ``Summary`` is built in the test with
the dataclasses, from invented domains (``example.com``), invented service names and the
documentation address ranges ``192.0.2.0/24``, ``198.51.100.0/24``, ``203.0.113.0/24`` and
``2001:db8::/32`` (RNF-07).
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from mailvigil.render import (
    _REASON_PHRASES,
    _label,
    fit,
    format_share,
    no_reports_message,
    render_summary,
    share_tenths,
)
from mailvigil.reports import IngestionResult, PolicyPublished, Reason, SkippedFile
from mailvigil.senders import Outcome
from mailvigil.summary import Counts, FailingSource, Period, SenderRow, Summary

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

# The right-to-left override, built here so the character is not invisible in the source.
_RLO = chr(0x202E)

_PERIOD = Period(
    begin=datetime(2026, 10, 1, tzinfo=UTC),
    end=datetime(2026, 10, 29, tzinfo=UTC),
    first_day=date(2026, 10, 1),
    last_day=date(2026, 10, 28),
    days_spanned=28,
    days_with_reports=27,
)


def make_summary(**changes: object) -> Summary:
    """
    Build the summary of the sketch of the spec: a domain with 12480 messages and a little failing.

    Args:
        **changes (object): Fields of ``Summary`` to replace.

    Returns:
        Summary: The summary, with no senders, no failing sources and nothing left out unless
            ``changes`` says so.
    """
    base = Summary(
        domain="example.com",
        selectors_configured=2,
        reports=54,
        reporters=4,
        period=_PERIOD,
        policy=PolicyPublished(domain="example.com", p="none", pct=100),
        totals=Counts(ok=11900, dkim_only=300, spf_only=240, failing=40),
        recognized_messages=12300,
    )
    return dataclasses.replace(base, **changes)  # type: ignore[arg-type]  # fields named by tests


def known(service: str, ok: int = 0, fragile: int = 0, failing: int = 0) -> SenderRow:
    """
    Build a row of a recognized service.

    Args:
        service (str): The service name.
        ok (int, optional): Messages where both passed. Default: 0.
        fragile (int, optional): Messages where one passed (counted as DKIM only). Default: 0.
        failing (int, optional): Messages where neither passed. Default: 0.

    Returns:
        SenderRow: The row.
    """
    return SenderRow(Outcome.KNOWN, service=service, counts=Counts(ok, fragile, 0, failing))


def other(
    ip: str,
    outcome: Outcome = Outcome.UNKNOWN,
    ok: int = 0,
    failing: int = 0,
) -> SenderRow:
    """
    Build a row of a source that was not recognized.

    Args:
        ip (str): The source address.
        outcome (Outcome, optional): What identification said. Default: ``UNKNOWN``.
        ok (int, optional): Messages where both passed. Default: 0.
        failing (int, optional): Messages where neither passed. Default: 0.

    Returns:
        SenderRow: The row.
    """
    return SenderRow(outcome, source_ip=ip, counts=Counts(ok=ok, failing=failing))


def failing_source(
    ip: str = "192.0.2.10",
    messages: int = 12,
    outcome: Outcome = Outcome.UNKNOWN,
    service: str = "",
    **changes: object,
) -> FailingSource:
    """
    Build a failing source.

    Args:
        ip (str, optional): The address. Default: ``192.0.2.10``.
        messages (int, optional): The failing messages. Default: 12.
        outcome (Outcome, optional): What identification said. Default: ``UNKNOWN``.
        service (str, optional): The service name, for a ``KNOWN`` source. Default: empty.
        **changes (object): Other fields of ``FailingSource`` to set.

    Returns:
        FailingSource: The source, with ``dkim`` and ``spf`` defaulting to ``fail``.
    """
    fields: dict[str, object] = {"dkim": ("fail",), "spf": ("fail",)}
    fields.update(changes)
    return FailingSource(outcome, ip, messages, service, **fields)  # type: ignore[arg-type]  # fields are named by the caller


def render(summary: Summary, source: str | None = "mailvigil.toml") -> str:
    """
    Render a summary with a configuration file named ``mailvigil.toml``.

    Args:
        summary (Summary): The summary.
        source (str | None, optional): The configuration path, or ``None`` for none. Default:
            ``mailvigil.toml``.

    Returns:
        str: The text.
    """
    return render_summary(summary, source)


def section(text: str, title: str) -> list[str]:
    """
    Pick the lines of the section that starts with ``title``.

    Args:
        text (str): The whole text.
        title (str): The first line of the section.

    Returns:
        list[str]: The lines of the section.
    """
    for block in text.split("\n\n"):
        if block.startswith(title):
            return block.split("\n")
    raise AssertionError(f"no section starts with {title!r}")


def skipped(name: str, reason: Reason = Reason.NOT_A_REPORT, part: str = "") -> SkippedFile:
    """
    Build a skipped file.

    Args:
        name (str): The file name.
        reason (Reason, optional): Why it was refused. Default: ``NOT_A_REPORT``.
        part (str, optional): The message and attachment of a mail file. Default: none.

    Returns:
        SkippedFile: The skipped file.
    """
    return SkippedFile(path=Path("reports") / name, reason=reason, detail="", part=part)


# ---------------------------------------------------------------------------
# Shares (RF-06, ADR-5)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("part", "whole", "expected"),
    [
        (11900, 12480, "95.4%"),
        (540, 12480, "4.3%"),
        (40, 12480, "0.3%"),
        (0, 10, "0%"),
        (4, 10000, "<0.1%"),
        (1, 1000, "0.1%"),
        (9997, 10000, "99.9%"),
        (10000, 10000, "100%"),
        (1, 2, "50.0%"),
        (0, 0, "0%"),
    ],
)
def test_format_share(part: int, whole: int, expected: str) -> None:
    assert format_share(part, whole) == expected


@pytest.mark.parametrize(
    ("part", "whole", "expected"),
    [
        (0, 10, 0),
        (5, 0, 0),
        (-1, 10, 0),
        (4, 10000, 0),
        (5, 10000, 1),
        (1, 2, 500),
        (150, 30000, 5),
        (151, 30000, 5),
        (160, 30000, 5),
        (170, 30000, 6),
        (2399, 3000, 800),
        (10000, 10000, 1000),
    ],
)
def test_share_tenths_is_the_tenths_of_a_percent_rounded_half_up(
    part: int, whole: int, expected: int
) -> None:
    """The integer under ``format_share``, public so the verdict can compare it to a limit."""
    assert share_tenths(part, whole) == expected


def test_a_share_does_not_depend_on_a_float() -> None:
    # A float cannot tell 10**30 - 1 from 10**30: it would print 100.0% and hide the one message.
    assert format_share(10**30 - 1, 10**30) == "99.9%"
    assert format_share(1, 10**30) == "<0.1%"


# ---------------------------------------------------------------------------
# Helpers (RF-05, RF-09, RNF-08)
# ---------------------------------------------------------------------------


def test_fit_leaves_a_short_text_alone() -> None:
    assert fit("Example Mailer", 20) == "Example Mailer"
    assert fit("abcde", 5) == "abcde"


def test_fit_cuts_to_the_width_with_dots() -> None:
    assert fit("a" * 20, 10) == "aaaaaaa..."


@pytest.mark.parametrize(("width", "expected"), [(3, "..."), (2, ".."), (0, "")])
def test_fit_into_a_tiny_width_never_exceeds_it(width: int, expected: str) -> None:
    assert fit("abcdef", width) == expected


def test_fit_removes_escape_sequences_line_breaks_and_overrides_before_cutting() -> None:
    assert fit(f"a\x1b[31mb\nc{_RLO}d", 80) == "a[31mb cd"
    # The dropped characters do not take room from the visible ones.
    assert fit(f"ab\x1b\x1b\x1b{_RLO}{_RLO}cd", 4) == "abcd"


def test_every_reason_has_a_phrase_that_is_not_the_bare_key() -> None:
    assert set(_REASON_PHRASES) == set(Reason)
    for reason in Reason:
        phrase = _REASON_PHRASES[reason]
        assert phrase
        assert phrase.isascii()
        assert phrase != reason.value


def test_a_known_row_is_labeled_by_its_service() -> None:
    assert _label(known("Example Mailer (newsletters)"), 80) == "Example Mailer (newsletters)"


@pytest.mark.parametrize(
    ("outcome", "note"),
    [
        (Outcome.UNKNOWN, "unrecognized"),
        (Outcome.FOREIGN_DOMAIN, "foreign domain"),
        (Outcome.FAILING_SIGNATURE, "failing signature"),
    ],
)
def test_a_row_that_is_not_known_is_labeled_by_address_and_kind(
    outcome: Outcome, note: str
) -> None:
    assert _label(other("192.0.2.10", outcome), 80) == f"192.0.2.10 ({note})"


def test_an_empty_address_reads_as_no_address() -> None:
    assert _label(other(""), 80) == "no address (unrecognized)"


def test_a_narrow_label_cuts_the_address_and_keeps_the_kind() -> None:
    label = _label(other("2001:db8:85a3:8d3:1319:8a2e:370:7348", Outcome.FOREIGN_DOMAIN), 30)
    assert len(label) == 30
    assert label.endswith("... (foreign domain)")


def test_the_address_is_not_cut_when_a_long_service_name_widens_the_column() -> None:
    """A long name takes the column to its cap; an IPv4 address with any kind must still fit."""
    senders = (
        known("S" * 100, ok=500),
        other("255.255.255.255", Outcome.FAILING_SIGNATURE, failing=3),
    )
    lines = section(render(make_summary(senders=senders)), "Senders")
    assert any(line.startswith("! 255.255.255.255 (failing signature) ") for line in lines)


# ---------------------------------------------------------------------------
# Header and situations (RF-03, RF-06, RF-09)
# ---------------------------------------------------------------------------


def test_the_sections_come_in_order() -> None:
    text = render(make_summary(failing=(failing_source(),)))
    titles = [block.split("\n")[0] for block in text.split("\n\n")]
    assert titles[0] == "MailVigil summary for example.com"
    assert titles[1:3] == ["Situations", "Senders"]
    assert titles[3].startswith("! FAILING")
    assert titles[4] == "Left out of these numbers"
    assert len(titles) == 5


def test_the_header_shows_config_period_reports_policy_and_messages() -> None:
    assert section(render(make_summary()), "MailVigil") == [
        "MailVigil summary for example.com",
        "  config    mailvigil.toml (2 selectors)",
        "  period    2026-10-01 to 2026-10-28 (27 of 28 days have a report)",
        "  reports   54 from 4 reporters",
        "  policy    p=none, pct=100",
        "  messages  12480 (12300 from recognized senders, 98.6%)",
    ]


def test_the_policy_shows_sp_and_np_when_present() -> None:
    policy = PolicyPublished(domain="example.com", p="reject", sp="quarantine", np="reject", pct=50)
    header = section(render(make_summary(policy=policy)), "MailVigil")
    assert header[4] == "  policy    p=reject, sp=quarantine, np=reject, pct=50"


def test_a_policy_that_changed_names_the_earlier_values() -> None:
    policy = PolicyPublished(domain="example.com", p="reject")
    header = section(render(make_summary(policy=policy, earlier_p=("none", "quarantine"))), "Mail")
    assert header[4:6] == [
        "  policy    p=reject, pct=100",
        "            changed during the period, earlier p: none, quarantine",
    ]


def test_an_empty_selector_map_adds_the_note_and_points_at_the_readme() -> None:
    header = section(render(make_summary(selectors_configured=0), None), "MailVigil")
    assert header[1] == "  config    none"
    assert header[2] == "            no selectors are configured, so every sender is unrecognized"
    assert "Configuration section of the README" in header[3]


def test_a_file_with_no_selectors_still_gets_the_note() -> None:
    header = section(render(make_summary(selectors_configured=0)), "MailVigil")
    assert header[1] == "  config    mailvigil.toml (0 selectors)"
    assert "no selectors are configured" in header[2]


def test_the_singular_forms() -> None:
    period = dataclasses.replace(_PERIOD, days_spanned=1, days_with_reports=1)
    summary = make_summary(
        selectors_configured=1, reports=1, reporters=1, period=period, totals=Counts(ok=1)
    )
    header = section(render(summary), "MailVigil")
    assert header[1] == "  config    mailvigil.toml (1 selector)"
    assert header[2] == "  period    2026-10-01 to 2026-10-28 (1 of 1 day has a report)"
    assert header[3] == "  reports   1 from 1 reporter"


def test_one_day_with_a_report_among_several_uses_has() -> None:
    period = dataclasses.replace(_PERIOD, days_with_reports=1)
    header = section(render(make_summary(period=period)), "MailVigil")
    assert header[2].endswith("(1 of 28 days has a report)")


def test_a_summary_without_reports_still_renders() -> None:
    summary = Summary(domain="example.com")
    text = render(summary)
    assert "  period    no reports" in text
    assert "  policy    none" in text
    assert "  messages  0 (0 from recognized senders, 0%)" in text


def test_the_config_path_is_cleaned_before_it_is_printed() -> None:
    text = render(make_summary(), "evil\x1b[2J\nname.toml")
    assert "\x1b" not in text
    assert "  config    evil[2J name.toml (2 selectors)" in text.split("\n")


def test_the_situations_print_exact_counts_beside_each_share() -> None:
    assert section(render(make_summary()), "Situations") == [
        "Situations",
        "  ok       11900  95.4%",
        "  fragile    540   4.3%",
        "  failing     40   0.3%",
    ]


def test_a_tiny_failing_share_is_not_rounded_to_zero() -> None:
    summary = make_summary(totals=Counts(ok=9996, failing=4))
    assert "  failing     4  <0.1%" in section(render(summary), "Situations")


# ---------------------------------------------------------------------------
# Senders table (RF-02, RF-04, RF-09, Resolved decision 12)
# ---------------------------------------------------------------------------


def test_the_senders_table_aligns_its_columns_and_marks_failing_rows() -> None:
    senders = (
        known("Example Mailer (newsletters)", ok=9100, fragile=300, failing=12),
        known("Example Mail (staff mailboxes)", ok=2700, fragile=188),
        other("198.51.100.77", ok=100, failing=3),
        other("203.0.113.50", Outcome.FOREIGN_DOMAIN, failing=25),
    )
    assert section(render(make_summary(senders=senders)), "Senders") == [
        "Senders",
        "  sender                            ok  fragile  failing  total",
        "! Example Mailer (newsletters)    9100      300       12   9412",
        "  Example Mail (staff mailboxes)  2700      188        0   2888",
        "! 198.51.100.77 (unrecognized)     100        0        3    103",
        "! 203.0.113.50 (foreign domain)      0        0       25     25",
    ]


def test_every_known_row_is_shown_and_twelve_other_rows_print_ten_and_a_remainder() -> None:
    others = tuple(
        other(f"192.0.2.{i + 1}", ok=100 - i, failing=1 if i >= 10 else 0) for i in range(12)
    )
    senders = (known("Example Mailer", ok=500), *others, known("Example Mail", ok=1))
    lines = section(render(make_summary(senders=senders)), "Senders")
    labels = [line[2:] for line in lines[2:]]
    assert sum(1 for label in labels if label.startswith("Example Mail")) == 2
    assert sum(1 for label in labels if "(unrecognized)" in label) == 10
    assert any(label.startswith("192.0.2.10 (unrecognized)") for label in labels)
    assert "192.0.2.11 (" not in "".join(labels)
    # The hidden rows never hide their failing messages: 91 + 90 messages, 1 + 1 failing.
    assert lines[-1] == "  ... and 2 other sources: 181 messages, 2 failing"


def test_a_single_hidden_row_is_singular() -> None:
    others = tuple(other(f"192.0.2.{i + 1}", ok=10) for i in range(11))
    lines = section(render(make_summary(senders=others)), "Senders")
    assert lines[-1] == "  ... and 1 other source: 10 messages, 0 failing"


def test_a_summary_with_no_rows_says_so() -> None:
    assert section(render(make_summary()), "Senders") == ["Senders", "  no messages counted"]


def test_a_known_row_name_wider_than_the_column_is_cut() -> None:
    row = known("S" * 100, ok=1)
    line = section(render(make_summary(senders=(row,))), "Senders")[2]
    assert "..." in line
    assert len(line) <= 80


# ---------------------------------------------------------------------------
# Failures (RF-04)
# ---------------------------------------------------------------------------


def test_no_failing_message_says_so_in_one_line() -> None:
    text = render(make_summary(totals=Counts(ok=10)))
    assert "No failing messages." in text.split("\n")
    assert "FAILING" not in text


def test_the_title_carries_the_failing_messages_and_the_sources() -> None:
    sources = (failing_source(messages=12), failing_source("198.51.100.77", messages=3))
    title = render(make_summary(failing=sources)).split("\n\n")[3].split("\n")[0]
    assert title == "! FAILING: 15 messages in 2 sources"


def test_the_title_is_singular_for_one_message_in_one_source() -> None:
    title = render(make_summary(failing=(failing_source(messages=1),))).split("\n\n")[3]
    assert title.startswith("! FAILING: 1 message in 1 source\n")


def test_recognized_sources_come_before_unrecognized_ones_and_take_two_lines_each() -> None:
    sources = (
        failing_source("203.0.113.50", 25, Outcome.FOREIGN_DOMAIN, selectors=("newsletter",)),
        failing_source("192.0.2.10", 12, Outcome.KNOWN, "Example Mailer", dkim=("unaligned",)),
        failing_source(
            "198.51.100.77", 3, dkim=("fail",), spf=("fail",), override_reasons=("forwarded",)
        ),
    )
    lines = section(render(make_summary(failing=sources)), "! FAILING")
    assert lines == [
        "! FAILING: 40 messages in 3 sources",
        "  Recognized senders that fail",
        "  ! Example Mailer",
        "      192.0.2.10  12 messages  dkim: unaligned, spf: fail",
        "  Unrecognized sources that fail",
        "  ! unrecognized, foreign domain (selector newsletter)",
        "      203.0.113.50  25 messages  dkim: fail, spf: fail",
        "  ! 198.51.100.77",
        "      3 messages  dkim: fail, spf: fail; forwarded",
    ]


def test_several_reasons_for_one_mechanism_are_joined_with_a_slash() -> None:
    source = failing_source(dkim=("fail", "none"), spf=("unaligned",))
    lines = section(render(make_summary(failing=(source,))), "! FAILING")
    assert lines[-1] == "      12 messages  dkim: fail/none, spf: unaligned"


def test_several_override_types_are_listed() -> None:
    source = failing_source(override_reasons=("forwarded", "mailing_list"))
    lines = section(render(make_summary(failing=(source,))), "! FAILING")
    assert lines[-1].endswith("; forwarded, mailing_list")


def test_a_failing_signature_names_its_selector_and_several_selectors_are_listed() -> None:
    sources = (
        failing_source("192.0.2.10", 5, Outcome.FAILING_SIGNATURE, selectors=("mailbox",)),
        failing_source("192.0.2.11", 4, Outcome.FOREIGN_DOMAIN, selectors=("a", "b")),
    )
    lines = section(render(make_summary(failing=sources)), "! FAILING")
    assert "  ! unrecognized, failing signature (selector mailbox)" in lines
    assert "  ! unrecognized, foreign domain (selectors a, b)" in lines


def test_a_foreign_source_without_a_selector_names_only_its_kind() -> None:
    source = failing_source("192.0.2.10", 5, Outcome.FOREIGN_DOMAIN)
    lines = section(render(make_summary(failing=(source,))), "! FAILING")
    assert "  ! unrecognized, foreign domain" in lines


def test_an_unrecognized_source_is_named_by_its_address_on_the_first_line() -> None:
    """The group title already says "unrecognized"; repeating it per source hides the address."""
    lines = section(render(make_summary(failing=(failing_source("192.0.2.10"),))), "! FAILING")
    assert lines[-2:] == ["  ! 192.0.2.10", "      12 messages  dkim: fail, spf: fail"]


def test_an_empty_address_in_a_failing_source_reads_as_no_address() -> None:
    lines = section(render(make_summary(failing=(failing_source(""),))), "! FAILING")
    assert lines[-2:] == ["  ! no address", "      12 messages  dkim: fail, spf: fail"]


def test_an_empty_group_is_not_printed() -> None:
    only_unrecognized = render(make_summary(failing=(failing_source(),)))
    assert "Recognized senders that fail" not in only_unrecognized
    assert "Unrecognized sources that fail" in only_unrecognized
    only_known = render(make_summary(failing=(failing_source(service="X", outcome=Outcome.KNOWN),)))
    assert "Recognized senders that fail" in only_known
    assert "Unrecognized sources that fail" not in only_known


def test_twelve_sources_in_a_group_print_ten_and_a_remainder() -> None:
    sources = tuple(failing_source(f"192.0.2.{i + 1}", 20 - i) for i in range(12))
    lines = section(render(make_summary(failing=sources)), "! FAILING")
    assert sum(1 for line in lines if line.startswith("  ! ")) == 10
    assert "192.0.2.10  " in "".join(lines)
    assert "192.0.2.11  " not in "".join(lines)
    # The remainder keeps the failing messages of the sources it hides: 10 + 9.
    assert lines[-1] == "  ... and 2 other sources: 19 failing messages"


def test_each_group_has_its_own_limit_and_remainder() -> None:
    known_sources = tuple(
        failing_source(f"192.0.2.{i + 1}", 5, Outcome.KNOWN, f"Service {i:02d}") for i in range(11)
    )
    unknown_sources = tuple(failing_source(f"198.51.100.{i + 1}", 2) for i in range(11))
    lines = section(render(make_summary(failing=known_sources + unknown_sources)), "! FAILING")
    assert "  ... and 1 other source: 5 failing messages" in lines
    assert lines[-1] == "  ... and 1 other source: 2 failing messages"


# ---------------------------------------------------------------------------
# What was left out (RF-05)
# ---------------------------------------------------------------------------


def test_left_out_prints_zero_counts() -> None:
    assert section(render(make_summary()), "Left out") == [
        "Left out of these numbers",
        "  skipped files  0",
        "  duplicates     0",
        "  other domains  0",
    ]


def test_the_files_passed_over_by_name_print_only_when_there_are_some() -> None:
    summary = make_summary(passed_over=12)

    assert section(render(summary), "Left out") == [
        "Left out of these numbers",
        "  skipped files        0",
        "  duplicates           0",
        "  other domains        0",
        "  passed over by name  12",
    ]


def test_the_files_passed_over_by_name_show_in_the_no_reports_message() -> None:
    lines = no_reports_message(IngestionResult(passed_over=2), "example.com").split("\n")

    assert lines[-1] == "  passed over by name  2"
    assert "  provider!domain!begin!end.zip; try --recursive, or name the file itself." in lines


def test_skipped_files_show_the_counts_per_reason_and_each_file() -> None:
    summary = make_summary(
        skipped=(skipped("a.xml", Reason.FILE_TOO_LARGE), skipped("b.txt")),
        skipped_by_reason=((Reason.FILE_TOO_LARGE, 1), (Reason.NOT_A_REPORT, 1)),
        duplicates=3,
        other_domain=2,
    )
    assert section(render(summary), "Left out") == [
        "Left out of these numbers",
        "  skipped files  2 (1 too large, 1 not a DMARC report)",
        "    a.xml: too large",
        "    b.txt: not a DMARC report",
        "  duplicates     3",
        "  other domains  2",
    ]


def test_twelve_skipped_files_print_ten_and_a_remainder() -> None:
    files = tuple(skipped(f"f{i:02d}.xml") for i in range(12))
    summary = make_summary(skipped=files, skipped_by_reason=((Reason.NOT_A_REPORT, 12),))
    lines = section(render(summary), "Left out")
    assert sum(1 for line in lines if line.startswith("    f")) == 10
    assert "    ... and 2 more" in lines
    assert "    f10.xml" not in "\n".join(lines)


def test_a_skipped_attachment_of_a_mail_file_shows_its_part_after_the_name() -> None:
    summary = make_summary(
        skipped=(skipped("box.mbox", Reason.NOT_AN_ARCHIVE, "#3 r.zip"), skipped("a.eml")),
        skipped_by_reason=((Reason.NOT_A_REPORT, 1), (Reason.NOT_AN_ARCHIVE, 1)),
    )
    lines = section(render(summary), "Left out")
    assert "    box.mbox #3 r.zip: not a valid archive" in lines
    assert "    a.eml: not a DMARC report" in lines


def test_a_long_part_cuts_the_name_and_keeps_the_phrase_within_80_columns() -> None:
    summary = make_summary(
        skipped=(skipped("m" * 90 + ".mbox", Reason.MESSAGE_TOO_LARGE, "#1234 " + "a" * 200),),
        skipped_by_reason=((Reason.MESSAGE_TOO_LARGE, 1),),
    )
    lines = section(render(summary), "Left out")
    assert all(len(line) <= 80 for line in lines)
    assert lines[2].endswith(": message too large")


def test_a_skipped_file_name_with_an_escape_sequence_is_shown_cleaned() -> None:
    summary = make_summary(
        skipped=(skipped("bad\x1b[2Jname\n.xml"),),
        skipped_by_reason=((Reason.NOT_A_REPORT, 1),),
    )
    text = render(summary)
    assert "\x1b" not in text
    assert "    bad[2Jname .xml: not a DMARC report" in text.split("\n")


@pytest.mark.parametrize("reason", list(Reason))
def test_every_reason_prints_as_a_phrase_never_as_its_key(reason: Reason) -> None:
    summary = make_summary(skipped=(skipped("x.xml", reason),), skipped_by_reason=((reason, 1),))
    text = render(summary)
    assert f"    x.xml: {_REASON_PHRASES[reason]}" in text.split("\n")
    assert f": {reason.value}" not in text


# ---------------------------------------------------------------------------
# Layout limits (RF-09, RNF-05, ADR-6)
# ---------------------------------------------------------------------------


def extreme_summary() -> Summary:
    """
    Build a summary that stresses every width at once.

    Returns:
        Summary: A 100-character service name, IPv6 addresses, counts of ``10**12``, 40 override
            types, a long skipped file name and every refusal reason.
    """
    huge = 10**12
    ipv6 = "2001:db8:85a3:8d3:1319:8a2e:370:7348"
    overrides = tuple(f"override_{i:02d}" for i in range(40))
    senders = (
        known("S" * 100, ok=huge, fragile=huge, failing=huge),
        other(ipv6, Outcome.FAILING_SIGNATURE, ok=huge, failing=huge),
        other(ipv6, Outcome.FOREIGN_DOMAIN, ok=huge),
    )
    sources = (
        failing_source(ipv6, huge, Outcome.KNOWN, "S" * 100, override_reasons=overrides),
        failing_source(
            ipv6, huge, Outcome.FOREIGN_DOMAIN, selectors=("sel" * 20,), override_reasons=overrides
        ),
    )
    files = tuple(skipped("n" * 100 + ".xml", reason) for reason in Reason)
    return make_summary(
        domain="d" * 60 + ".example.com",
        selectors_configured=huge,
        reports=huge,
        reporters=huge,
        totals=Counts(huge, huge, huge, huge),
        recognized_messages=huge,
        senders=senders,
        failing=sources,
        skipped=files,
        skipped_by_reason=tuple((reason, huge) for reason in Reason),
        duplicates=huge,
        other_domain=huge,
        earlier_p=("none", "quarantine"),
    )


def test_no_line_is_over_eighty_columns_with_extreme_values() -> None:
    text = render(extreme_summary(), "p" * 100 + ".toml")
    assert max(len(line) for line in text.split("\n")) <= 80


def test_the_output_is_ascii_apart_from_names() -> None:
    assert render(extreme_summary()).isascii()


def test_the_same_summary_rendered_twice_is_the_same_text() -> None:
    summary = extreme_summary()
    assert render(summary) == render(summary)


def test_a_name_with_a_non_ascii_character_is_printed_as_it_is() -> None:
    assert "Café ★" in render(make_summary(senders=(known("Café ★", ok=1),)))


def test_the_text_has_no_trailing_newline_and_no_trailing_spaces() -> None:
    text = render(extreme_summary())
    assert not text.endswith("\n")
    assert all(line == line.rstrip() for line in text.split("\n"))


# ---------------------------------------------------------------------------
# Empty result (RF-10)
# ---------------------------------------------------------------------------


def test_no_reports_message_names_the_domain_and_what_was_left_out() -> None:
    result = IngestionResult(
        skipped=(skipped("b.txt"), skipped("a.xml", Reason.FILE_TOO_LARGE)),
        duplicates=2,
        other_domain=3,
    )
    assert no_reports_message(result, "example.com").split("\n") == [
        "No DMARC report for example.com was kept.",
        "  skipped files  2 (1 too large, 1 not a DMARC report)",
        "    a.xml: too large",
        "    b.txt: not a DMARC report",
        "  duplicates     2",
        "  other domains  3",
    ]


def test_no_reports_message_for_nothing_found_says_where_to_look() -> None:
    """A folder only yields the providers' names, so the message says so and how to bypass it."""
    lines = no_reports_message(IngestionResult(), "example.com").split("\n")
    assert lines[0] == "No DMARC report for example.com was kept."
    assert lines[1] == "No report file was found. A folder is searched only for names like"
    assert lines[2] == "  provider!domain!begin!end.zip; try --recursive, or name the file itself."
    assert lines[3:] == ["  skipped files  0", "  duplicates     0", "  other domains  0"]
    assert max(len(line) for line in lines) <= 80


def test_no_reports_message_is_short_enough_and_ends_without_a_newline() -> None:
    result = IngestionResult(skipped=(skipped("n" * 100 + ".xml"),))
    message = no_reports_message(result, "d" * 80 + ".example.com")
    assert not message.endswith("\n")
    assert max(len(line) for line in message.split("\n")) <= 80
