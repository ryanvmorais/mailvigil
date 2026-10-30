"""
Tests of the message catalog: the shape every language must have, ``Plural``, the language lookup
and the configuration refusal line built from the catalog.

Isolation: nothing touches the disk and no command runs, except one child interpreter that checks
what importing the catalog pulls in. The catalog is walked through its dataclass fields, so a
message added to the model without an entry here (its placeholders) fails the walk instead of
passing unchecked (spec 006, RF-06, RNF-05).
"""

from __future__ import annotations

import dataclasses
import subprocess
import sys
from collections.abc import Callable, Iterator, Mapping
from enum import Enum
from string import Formatter

import pytest

from mailvigil.cli_common import config_line
from mailvigil.config import ConfigError, ConfigReason
from mailvigil.fetch.errors import FetchReason
from mailvigil.messages import ENGLISH, PORTUGUESE, Messages, Plural, language_by_code
from mailvigil.reports import Reason
from mailvigil.senders import Outcome
from mailvigil.verdict import Answer, NoteKind, RuleId

# ---------------------------------------------------------------------------
# The declared placeholders
# ---------------------------------------------------------------------------

# What each template that has placeholders declares, by ``area.field`` (``area.field[MEMBER]`` for
# an entry of a mapping). A field not listed declares none. ``n`` is not listed for a ``Plural``: it
# is always allowed there, and a language may leave it out of a form.
_PLACEHOLDERS: dict[str, frozenset[str]] = {
    "common.selectors_named": frozenset({"names"}),
    "common.more_failing": frozenset({"sources", "messages"}),
    "summary.title": frozenset({"domain"}),
    "summary.period": frozenset({"first", "last", "days"}),
    "summary.reports_line": frozenset({"reports", "reporters"}),
    "summary.policy_changed": frozenset({"earlier"}),
    "summary.messages_line": frozenset({"total", "recognized", "share"}),
    "summary.senders_more": frozenset({"sources", "messages", "failing"}),
    "summary.unrecognized_who": frozenset({"kind"}),
    "summary.source_detail": frozenset({"messages", "dkim", "spf"}),
    "summary.failing_title": frozenset({"messages", "sources"}),
    "summary.skipped_more": frozenset({"n"}),
    "verdict.title": frozenset({"domain"}),
    "verdict.enforcing": frozenset({"words"}),
    "verdict.why_unrecognized": frozenset({"share", "measured", "whole", "limit"}),
    "verdict.recognized_tail": frozenset({"messages", "where"}),
    "verdict.other_tail": frozenset({"kind", "messages"}),
    "verdict.measured_coverage": frozenset({"measured", "whole", "share"}),
    "verdict.notes[FRAGILE]": frozenset({"fragile", "total", "share", "spf_only"}),
    "verdict.notes[PARTIAL_POLICY]": frozenset({"pct"}),
    "verdict.notes[POLICY_CHANGED]": frozenset({"earlier"}),
    "verdict.notes[SUBDOMAIN_POLICY]": frozenset({"shown"}),
    "verdict.notes[SILENT_REPORTER]": frozenset({"name", "share", "days"}),
    "verdict.notes[STALE]": frozenset({"days"}),
    "verdict.next_recognized": frozenset({"who"}),
    "verdict.next_data": frozenset({"marker"}),
    "verdict.left_out": frozenset({"parts"}),
    "html.page_title": frozenset({"domain"}),
    "html.at_least": frozenset({"value"}),
    "html.at_most": frozenset({"value"}),
    "html.meter_label": frozenset({"name", "measured", "needed"}),
    "html.situation_label": frozenset({"name", "count", "share"}),
    "html.scale_note": frozenset({"tallest"}),
    "html.timeline_label": frozenset({"first", "last", "failing"}),
    "html.range_label": frozenset({"first", "last"}),
    "html.footer": frozenset({"version"}),
    "fetch.password_file_exposed": frozenset({"path"}),
    "refusals.no_domain": frozenset({"default"}),
    "refusals.domain_mismatch": frozenset({"wanted", "domain", "path"}),
    "refusals.no_reports": frozenset({"domain"}),
    "refusals.output_failed": frozenset({"path", "reason"}),
}


def _walk(messages: Messages) -> Iterator[tuple[str, str, bool]]:
    """
    Walk every template of a catalog.

    Args:
        messages (Messages): The catalog.

    Yields:
        tuple[str, str, bool]: The declaration path (``area.field`` or ``area.field[MEMBER]``), the
            template, and whether it is a form of a ``Plural``.
    """
    for area in dataclasses.fields(messages):
        group = getattr(messages, area.name)
        for field in dataclasses.fields(group):
            value = getattr(group, field.name)
            path = f"{area.name}.{field.name}"
            if isinstance(value, str):
                yield path, value, False
            elif isinstance(value, Plural):
                yield path, value.one, True
                yield path, value.many, True
            elif isinstance(value, Mapping):
                for key, text in value.items():
                    yield f"{path}[{key.name}]", text, False
            elif not isinstance(value, frozenset):
                raise AssertionError(f"{path} is a {type(value).__name__}: teach the walk")


def _used(template: str) -> frozenset[str]:
    """Name the placeholders a template uses."""
    return frozenset(name for _, name, _, _ in Formatter().parse(template) if name is not None)


# The two languages every shape test runs over (RF-06: both have the same shape).
_BOTH = pytest.mark.parametrize("messages", [ENGLISH, PORTUGUESE], ids=["en", "pt-BR"])

# What is the same word in both languages, by declaration path (``area.field[MEMBER]`` for a mapping
# entry; ``.one`` or ``.many`` for the form of a ``Plural`` that happens to be written alike). Each
# is a name, a code or a layout template that carries no word of its own; everything else must be
# translated, so an English sentence left in the Portuguese catalog fails the test.
_SAME_IN_BOTH: frozenset[str] = frozenset(
    {
        "summary.key_config",
        "summary.col_ok",
        "summary.col_total",
        "summary.source_detail",
        "verdict.other_tail",
        "html.meter_label",
        "html.situation_label",
    }
)

# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------


def test_english_is_a_messages_value() -> None:
    assert isinstance(ENGLISH, Messages)


def test_portuguese_is_a_messages_value() -> None:
    assert isinstance(PORTUGUESE, Messages)


@_BOTH
def test_no_template_is_empty(messages: Messages) -> None:
    templates = list(_walk(messages))
    assert templates
    for path, template, _is_plural in templates:
        assert template.strip(), path


@_BOTH
def test_every_template_is_ascii(messages: Messages) -> None:
    for path, template, _is_plural in _walk(messages):
        assert template.isascii(), path


@_BOTH
def test_every_template_uses_exactly_the_placeholders_its_field_declares(
    messages: Messages,
) -> None:
    for path, template, is_plural in _walk(messages):
        declared = _PLACEHOLDERS.get(path, _PLACEHOLDERS.get(path.split("[")[0], frozenset()))
        used = _used(template)
        if is_plural:
            used -= {"n"}
        assert used == declared, path


def test_portuguese_has_the_same_templates_as_english_and_no_other() -> None:
    english = [(path, is_plural) for path, _template, is_plural in _walk(ENGLISH)]
    portuguese = [(path, is_plural) for path, _template, is_plural in _walk(PORTUGUESE)]
    assert portuguese == english


def test_no_portuguese_template_is_its_english_twin_except_the_listed_ones() -> None:
    english = {(path, i): t for i, (path, t, _p) in enumerate(_walk(ENGLISH))}
    portuguese = {(path, i): t for i, (path, t, _p) in enumerate(_walk(PORTUGUESE))}
    alike = {path for (path, i), text in portuguese.items() if english[(path, i)] == text}
    assert alike <= _SAME_IN_BOTH, sorted(alike - _SAME_IN_BOTH)
    # An exception that is no longer needed is a stale line of this test, not a harmless one.
    assert alike >= _SAME_IN_BOTH, sorted(_SAME_IN_BOTH - alike)


def test_the_portuguese_catalog_says_neither_safe_nor_attack() -> None:
    """The verdict reads reports, it does not certify a domain (spec 006 Resolved decision 4)."""
    for path, template, _is_plural in _walk(PORTUGUESE):
        text = template.lower()
        assert "seguro" not in text, path
        assert "ataque" not in text, path


@_BOTH
def test_a_hanging_indent_label_is_one_word_with_its_colon(messages: Messages) -> None:
    """The wrapped sentences indent by the label's width, so a label cannot hold a line break."""
    for label in (messages.verdict.why_label, messages.verdict.next_label):
        assert label.endswith(":")
        assert "\n" not in label


@_BOTH
def test_every_declared_placeholder_belongs_to_a_field_that_exists(messages: Messages) -> None:
    paths = {path for path, _template, _is_plural in _walk(messages)}
    bases = {path.split("[")[0] for path in paths}
    for declared in _PLACEHOLDERS:
        assert declared in paths or declared in bases, declared


@_BOTH
def test_every_template_formats_with_its_placeholders(messages: Messages) -> None:
    for path, template, _is_plural in _walk(messages):
        values = dict.fromkeys(_used(template), "x")
        assert template.format(**values), path


@_BOTH
@pytest.mark.parametrize(
    ("get", "enum", "left_out"),
    [
        (lambda m: m.common.kinds, Outcome, {Outcome.KNOWN}),
        (lambda m: m.summary.reasons, Reason, set()),
        (lambda m: m.verdict.words, Answer, set()),
        (lambda m: m.verdict.words_enforcing, Answer, set()),
        (lambda m: m.verdict.rule_names, RuleId, set()),
        (lambda m: m.verdict.notes, NoteKind, set()),
        (lambda m: m.refusals.config_reasons, ConfigReason, set()),
        (lambda m: m.fetch.reasons, FetchReason, set()),
    ],
)
def test_every_enum_keyed_mapping_covers_its_enum(
    messages: Messages,
    get: Callable[[Messages], Mapping[Enum, str]],
    enum: type[Enum],
    left_out: set[Enum],
) -> None:
    mapping = get(messages)
    assert set(mapping) == set(enum) - left_out
    for text in mapping.values():
        assert text


@_BOTH
def test_the_reasons_that_keep_their_detail_are_configuration_reasons(messages: Messages) -> None:
    assert messages.refusals.config_detail <= set(ConfigReason)


def test_portuguese_keeps_the_detail_of_the_two_reasons_a_reader_cannot_act_without() -> None:
    """The parser's own message and the suggested key; the rest is said by the phrase (ADR-5)."""
    assert PORTUGUESE.refusals.config_detail == {
        ConfigReason.MALFORMED_TOML,
        ConfigReason.UNKNOWN_KEY,
    }


def test_every_portuguese_configuration_phrase_differs_from_its_reason_word() -> None:
    """The phrase is for a person, the reason word is for a log."""
    for reason, phrase in PORTUGUESE.refusals.config_reasons.items():
        assert phrase != reason.value
        assert "_" not in phrase


@_BOTH
def test_the_html_catalog_is_filled(messages: Messages) -> None:
    """Every field of ``HtmlMessages`` is a non-empty template or a ``Plural`` with both forms."""
    fields = dataclasses.fields(messages.html)
    assert fields
    for field in fields:
        value = getattr(messages.html, field.name)
        forms = [value.one, value.many] if isinstance(value, Plural) else [value]
        for form in forms:
            assert isinstance(form, str)
            assert form.strip(), field.name


def _sentences(messages: Messages, areas: tuple[str, ...]) -> set[str]:
    """Collect every template of the named areas of a catalog, a ``Plural`` by its two forms."""
    found: set[str] = set()
    for path, template, _is_plural in _walk(messages):
        if path.split(".")[0] in areas:
            found.add(template)
    return found


@_BOTH
def test_no_html_sentence_repeats_one_the_text_format_already_has(messages: Messages) -> None:
    """The page reads the shared sentences from ``common``, ``summary`` and ``verdict`` (RF-08)."""
    shared = _sentences(messages, ("common", "summary", "verdict"))
    own = _sentences(messages, ("html",))
    assert own
    assert not own & shared, sorted(own & shared)


def test_importing_the_catalog_does_not_import_a_renderer() -> None:
    code = (
        "import sys, mailvigil.messages; "
        "bad = [m for m in ('mailvigil.render', 'mailvigil.render_verdict', 'mailvigil.cli', "
        "'mailvigil.render_json', 'mailvigil.render_fetch') if m in sys.modules]; "
        "sys.exit(len(bad))"
    )
    assert subprocess.run([sys.executable, "-I", "-c", code], check=False).returncode == 0


def test_importing_the_catalog_takes_only_the_fetch_reasons_from_the_fetch_package() -> None:
    """``messages/`` imports ``fetch.errors`` and nothing else, so no network code is loaded."""
    code = (
        "import sys, mailvigil.messages; "
        "bad = [m for m in ('imaplib', 'mailvigil.fetch.imap', 'mailvigil.fetch.model', "
        "'mailvigil.fetch.store', 'mailvigil.fetch.run') if m in sys.modules]; "
        "sys.exit(len(bad))"
    )
    assert subprocess.run([sys.executable, "-I", "-c", code], check=False).returncode == 0


@_BOTH
def test_the_fetch_catalog_is_filled(messages: Messages) -> None:
    """Every field of ``FetchMessages`` is a non-empty template or a ``Plural`` with both forms."""
    fields = dataclasses.fields(messages.fetch)
    assert fields
    for field in fields:
        value = getattr(messages.fetch, field.name)
        if isinstance(value, Mapping):
            continue  # the reasons are checked by the coverage test above
        forms = [value.one, value.many] if isinstance(value, Plural) else [value]
        for form in forms:
            assert isinstance(form, str)
            assert form.strip(), field.name


@_BOTH
def test_a_fetch_phrase_is_not_the_reason_key(messages: Messages) -> None:
    """The phrase is for a person, the key is for a log."""
    for reason, phrase in messages.fetch.reasons.items():
        assert phrase != reason.value
        assert "_" not in phrase


# ---------------------------------------------------------------------------
# Plural
# ---------------------------------------------------------------------------


def test_a_plural_gives_the_singular_for_one_only() -> None:
    day = Plural("{n} day", "{n} days")
    assert day.of(1) == "1 day"
    assert day.of(0) == "0 days"
    assert day.of(2) == "2 days"


def test_a_plural_fills_the_other_placeholders() -> None:
    phrase = Plural("{n} item: {name}", "{n} items: {name}")
    assert phrase.of(1, name="a") == "1 item: a"
    assert phrase.of(3, name="a, b, c") == "3 items: a, b, c"


# ---------------------------------------------------------------------------
# The language lookup
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("code", ["en", "EN", "En"])
def test_english_is_found_in_any_case(code: str) -> None:
    assert language_by_code(code) is ENGLISH


@pytest.mark.parametrize("code", ["pt-BR", "pt-br", "PT-BR", "Pt-Br"])
def test_portuguese_is_found_in_any_case(code: str) -> None:
    assert language_by_code(code) is PORTUGUESE


@pytest.mark.parametrize("code", ["fr", "", "english", "en-US", "pt", "pt_BR", "portuguese"])
def test_any_other_code_is_refused(code: str) -> None:
    with pytest.raises(ValueError, match="unknown language"):
        language_by_code(code)


# ---------------------------------------------------------------------------
# The configuration refusal line
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("reason", list(ConfigReason))
@pytest.mark.parametrize(
    ("key", "detail"), [("", ""), ("senders", ""), ("", "a detail"), ("domain", "a detail")]
)
def test_the_english_line_is_what_the_error_has_always_said(
    reason: ConfigReason, key: str, detail: str
) -> None:
    error = ConfigError(reason, key, detail)
    assert config_line(error, ENGLISH) == str(error)


def test_a_language_can_drop_the_detail_of_a_reason() -> None:
    quiet = dataclasses.replace(
        ENGLISH,
        refusals=dataclasses.replace(
            ENGLISH.refusals, config_detail=frozenset({ConfigReason.UNKNOWN_KEY})
        ),
    )
    kept = ConfigError(ConfigReason.UNKNOWN_KEY, "sender", 'did you mean "senders"?')
    dropped = ConfigError(ConfigReason.NOT_UTF8, "", "the file is not valid UTF-8")
    assert config_line(kept, quiet) == str(kept)
    assert config_line(dropped, quiet) == "not_utf8"


@pytest.mark.parametrize("reason", list(ConfigReason))
def test_the_portuguese_line_is_the_phrase_then_the_key(reason: ConfigReason) -> None:
    error = ConfigError(reason, "senders")
    assert (
        config_line(error, PORTUGUESE) == f"{PORTUGUESE.refusals.config_reasons[reason]} [senders]"
    )


@pytest.mark.parametrize("reason", list(ConfigReason))
def test_the_portuguese_line_keeps_the_detail_only_where_the_language_says(
    reason: ConfigReason,
) -> None:
    error = ConfigError(reason, "k", "an English detail")
    line = config_line(error, PORTUGUESE)
    assert ("an English detail" in line) is (reason in PORTUGUESE.refusals.config_detail)


def test_the_portuguese_line_without_a_key_is_the_bare_phrase() -> None:
    error = ConfigError(ConfigReason.MISSING_DOMAIN)
    assert config_line(error, PORTUGUESE) == PORTUGUESE.refusals.config_reasons[error.reason]
