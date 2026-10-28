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

from mailvigil.cli import _config_line
from mailvigil.config import ConfigError, ConfigReason
from mailvigil.messages import ENGLISH, Messages, Plural, language_by_code
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
    "verdict.next_recognized": frozenset({"who"}),
    "verdict.next_data": frozenset({"marker"}),
    "verdict.left_out": frozenset({"parts"}),
    "refusals.no_domain": frozenset({"default"}),
    "refusals.domain_mismatch": frozenset({"wanted", "domain", "path"}),
    "refusals.no_reports": frozenset({"domain"}),
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


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------


def test_english_is_a_messages_value() -> None:
    assert isinstance(ENGLISH, Messages)


def test_no_template_is_empty() -> None:
    templates = list(_walk(ENGLISH))
    assert templates
    for path, template, _is_plural in templates:
        assert template.strip(), path


def test_every_template_is_ascii() -> None:
    for path, template, _is_plural in _walk(ENGLISH):
        assert template.isascii(), path


def test_every_template_uses_exactly_the_placeholders_its_field_declares() -> None:
    for path, template, is_plural in _walk(ENGLISH):
        declared = _PLACEHOLDERS.get(path, _PLACEHOLDERS.get(path.split("[")[0], frozenset()))
        used = _used(template)
        if is_plural:
            used -= {"n"}
        assert used == declared, path


def test_every_declared_placeholder_belongs_to_a_field_that_exists() -> None:
    paths = {path for path, _template, _is_plural in _walk(ENGLISH)}
    bases = {path.split("[")[0] for path in paths}
    for declared in _PLACEHOLDERS:
        assert declared in paths or declared in bases, declared


def test_every_template_formats_with_its_placeholders() -> None:
    for path, template, _is_plural in _walk(ENGLISH):
        values = dict.fromkeys(_used(template), "x")
        assert template.format(**values), path


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
    ],
)
def test_every_enum_keyed_mapping_covers_its_enum(
    get: Callable[[Messages], Mapping[Enum, str]], enum: type[Enum], left_out: set[Enum]
) -> None:
    mapping = get(ENGLISH)
    assert set(mapping) == set(enum) - left_out
    for text in mapping.values():
        assert text


def test_the_reasons_that_keep_their_detail_are_configuration_reasons() -> None:
    assert ENGLISH.refusals.config_detail <= set(ConfigReason)


def test_importing_the_catalog_does_not_import_a_renderer() -> None:
    code = (
        "import sys, mailvigil.messages; "
        "bad = [m for m in ('mailvigil.render', 'mailvigil.render_verdict', 'mailvigil.cli', "
        "'mailvigil.render_json') if m in sys.modules]; "
        "sys.exit(len(bad))"
    )
    assert subprocess.run([sys.executable, "-I", "-c", code], check=False).returncode == 0


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


@pytest.mark.parametrize("code", ["fr", "", "english", "en-US"])
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
    assert _config_line(error, ENGLISH) == str(error)


def test_a_language_can_drop_the_detail_of_a_reason() -> None:
    quiet = dataclasses.replace(
        ENGLISH,
        refusals=dataclasses.replace(
            ENGLISH.refusals, config_detail=frozenset({ConfigReason.UNKNOWN_KEY})
        ),
    )
    kept = ConfigError(ConfigReason.UNKNOWN_KEY, "sender", 'did you mean "senders"?')
    dropped = ConfigError(ConfigReason.NOT_UTF8, "", "the file is not valid UTF-8")
    assert _config_line(kept, quiet) == str(kept)
    assert _config_line(dropped, quiet) == "not_utf8"
