"""
Tests of the configuration loader: the vocabulary, the file, the domain, the selector map and
the ``[fetch]`` table.

Isolation: every file is written in ``tmp_path`` as explicit bytes, so the newline style and the
encoding of the platform do not matter, and nothing outside it is touched. The domains
(``example.com`` and friends) and the service names are invented (RNF-07). Each refusal test expects
a ``ConfigError`` and checks its ``reason`` and its ``key``.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType

import pytest

from mailvigil.config import (
    MAX_CONFIG_BYTES,
    MAX_SERVICE_NAME,
    Config,
    ConfigError,
    ConfigReason,
    FetchSettings,
    check_domain,
    load_config,
)
from mailvigil.text import normalize_domain

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

# The smallest valid file: tests append one line to it, so a refusal comes only from that line.
_VALID = 'domain = "example.com"\n'


def write(tmp_path: Path, content: str | bytes, name: str = "mailvigil.toml") -> Path:
    """
    Write a configuration file as explicit bytes.

    Args:
        tmp_path (Path): The test's private folder.
        content (str | bytes): The file content; text is encoded as UTF-8.
        name (str, optional): The file name. Default: ``mailvigil.toml``.

    Returns:
        Path: The file written.
    """
    path = tmp_path / name
    path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
    return path


def refusal(path: Path) -> ConfigError:
    """
    Load a file that must be refused.

    Args:
        path (Path): The configuration file.

    Returns:
        ConfigError: The refusal, for the test to inspect.
    """
    with pytest.raises(ConfigError) as caught:
        load_config(path)
    return caught.value


# ---------------------------------------------------------------------------
# Vocabulary (RF-07, RNF-04, ADR-5)
# ---------------------------------------------------------------------------


def test_config_reason_is_a_string_enum_with_the_fifteen_members() -> None:
    """``ConfigReason`` has exactly the fifteen refusals of the design, each a string."""
    assert issubclass(ConfigReason, StrEnum)
    assert len(ConfigReason) == 15


def test_config_reason_values_are_unique_lower_snake_strings() -> None:
    """Values are the stable keys spec 006 translates, so they must never collide."""
    values = [member.value for member in ConfigReason]

    assert len(set(values)) == len(values)
    assert all(value == value.lower() and " " not in value for value in values)
    assert ConfigReason.NON_ASCII_DOMAIN == "non_ascii_domain"


def test_config_error_keeps_reason_key_and_detail() -> None:
    """The exception exposes the machine-readable reason, the key and the English detail."""
    error = ConfigError(ConfigReason.INVALID_SELECTOR, "bad key!", "not a selector")

    assert error.reason is ConfigReason.INVALID_SELECTOR
    assert error.key == "bad key!"
    assert error.detail == "not a selector"


def test_config_error_message_mentions_reason_and_key() -> None:
    """``str(error)`` carries both, so an unhandled refusal is still readable in a log."""
    message = str(ConfigError(ConfigReason.DUPLICATE_SELECTOR, "resend", "twice"))

    assert "duplicate_selector" in message
    assert "resend" in message


def test_config_error_cleans_and_cuts_the_key() -> None:
    """A key comes straight from the file, so it never reaches a terminal raw (RF-05)."""
    hostile = "a\nb\N{RIGHT-TO-LEFT OVERRIDE}c" + "x" * 500

    error = ConfigError(ConfigReason.UNKNOWN_KEY, hostile)

    assert error.key == "a b" + "c" + "x" * 96
    assert len(error.key) == 100


def test_config_error_key_and_detail_default_to_empty() -> None:
    """File-level reasons concern no key."""
    error = ConfigError(ConfigReason.UNREADABLE)

    assert error.key == ""
    assert error.detail == ""
    assert str(error) == "unreadable"


def test_config_is_frozen_and_its_senders_are_read_only() -> None:
    """Neither a field nor the selector map can be changed after the load (RNF-04)."""
    config = Config("example.com", MappingProxyType({"resend": "Example Mailer"}))

    with pytest.raises(FrozenInstanceError):
        config.domain = "example.org"  # type: ignore[misc]  # frozen dataclass: read-only field
    with pytest.raises(TypeError):
        config.senders["zoho"] = "Example Mail"  # type: ignore[index]  # read-only view


# ---------------------------------------------------------------------------
# Reading the file (RF-01, RNF-02)
# ---------------------------------------------------------------------------


def test_a_minimal_valid_file_loads(tmp_path: Path) -> None:
    """A domain alone is a complete configuration: every sender will be unknown."""
    config = load_config(write(tmp_path, _VALID))

    assert config.domain == "example.com"
    assert dict(config.senders) == {}


def test_a_missing_path_is_unreadable(tmp_path: Path) -> None:
    """A path that does not exist is a refusal, not a crash."""
    error = refusal(tmp_path / "absent.toml")

    assert error.reason is ConfigReason.UNREADABLE
    assert error.key == ""


def test_a_folder_is_unreadable(tmp_path: Path) -> None:
    """Only a regular file is read."""
    assert refusal(tmp_path).reason is ConfigReason.UNREADABLE


def test_exactly_the_size_cap_is_accepted(tmp_path: Path) -> None:
    """The cap is inclusive: 64 KiB is the largest file read."""
    base = _VALID.encode()
    content = base + b"#" * (MAX_CONFIG_BYTES - len(base))
    assert len(content) == MAX_CONFIG_BYTES

    assert load_config(write(tmp_path, content)).domain == "example.com"


def test_one_byte_over_the_cap_is_refused_without_parsing(tmp_path: Path) -> None:
    """The content is not valid TOML, so a parse would say ``malformed_toml`` instead."""
    error = refusal(write(tmp_path, b"\xff" * (MAX_CONFIG_BYTES + 1)))

    assert error.reason is ConfigReason.FILE_TOO_LARGE


def test_bytes_that_are_not_utf8_are_refused(tmp_path: Path) -> None:
    """The decoder is strict: invalid bytes are never replaced."""
    error = refusal(write(tmp_path, b'domain = "\xff\xfe.example.com"\n'))

    assert error.reason is ConfigReason.NOT_UTF8


def test_a_byte_order_mark_is_accepted(tmp_path: Path) -> None:
    """Windows editors add one; ``tomllib`` alone would reject it as an invalid statement."""
    config = load_config(write(tmp_path, b"\xef\xbb\xbf" + _VALID.encode()))

    assert config.domain == "example.com"


def test_malformed_toml_is_refused_with_the_line(tmp_path: Path) -> None:
    """The parser's own position reaches the detail, not a stack trace."""
    error = refusal(write(tmp_path, 'domain = "example.com"\nsenders = \n'))

    assert error.reason is ConfigReason.MALFORMED_TOML
    assert "line 2" in error.detail


def test_a_deeply_nested_array_is_refused_not_a_crash(tmp_path: Path) -> None:
    """Within the size cap, 30,000 nested brackets still exhaust the parser's recursion."""
    depth = 30_000
    content = "a = " + "[" * depth + "]" * depth + "\n" + _VALID
    assert len(content) <= MAX_CONFIG_BYTES

    error = refusal(write(tmp_path, content))

    assert error.reason is ConfigReason.MALFORMED_TOML


def test_loading_creates_and_writes_nothing(tmp_path: Path) -> None:
    """The file is opened for reading only (RNF-02)."""
    path = write(tmp_path, _VALID + '[senders]\nresend = "Example Mailer"\n')
    before = (sorted(tmp_path.iterdir()), path.read_bytes(), path.stat().st_mtime_ns)

    load_config(path)

    assert (sorted(tmp_path.iterdir()), path.read_bytes(), path.stat().st_mtime_ns) == before


# ---------------------------------------------------------------------------
# The domain (RF-02, RF-04)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw", ["Example.COM.", "  example.com  ", "EXAMPLE.com", "example.com."])
def test_the_domain_is_normalized_like_ingest_does(tmp_path: Path, raw: str) -> None:
    """The loaded domain is the one ``ingest`` would use for the same text."""
    config = load_config(write(tmp_path, f'domain = "{raw}"\n'))

    assert config.domain == "example.com"
    assert config.domain == normalize_domain(raw)


def test_a_missing_domain_is_refused(tmp_path: Path) -> None:
    """Without a domain the tool has nothing to report on."""
    error = refusal(write(tmp_path, "[senders]\n"))

    assert error.reason is ConfigReason.MISSING_DOMAIN
    assert error.key == "domain"


@pytest.mark.parametrize(
    "line",
    [
        'domain = ""',
        'domain = "   "',
        "domain = 42",
        'domain = ["example.com"]',
        'domain = "https://example.com"',
        'domain = "example.com/path"',
        'domain = "user@example.com"',
        'domain = "example.com:25"',
        'domain = "a..com"',
        'domain = "ex ample.com"',
        'domain = "exam\\nple.com"',
        'domain = "exa\\u0000mple.com"',
        'domain = "localhost"',
        'domain = "com"',
        'domain = "-a.example.com"',
        'domain = "a-.example.com"',
        f'domain = "{"a" * 64}.com"',
        f'domain = "{".".join(["a" * 63] * 3 + ["b" * 62])}"',
    ],
    ids=[
        "empty",
        "blank",
        "integer",
        "list",
        "scheme",
        "path",
        "at-sign",
        "port",
        "empty-label",
        "space",
        "line-break",
        "control",
        "single-label",
        "tld-only",
        "leading-hyphen",
        "trailing-hyphen",
        "label-64",
        "name-254",
    ],
)
def test_a_domain_that_is_not_a_host_name_is_refused(tmp_path: Path, line: str) -> None:
    """Every shape that cannot be a DMARC domain fails the same label rule."""
    error = refusal(write(tmp_path, line + "\n"))

    assert error.reason is ConfigReason.INVALID_DOMAIN
    assert error.key == "domain"


def test_the_longest_valid_name_is_accepted(tmp_path: Path) -> None:
    """253 characters with labels of at most 63 is the edge that still loads."""
    name = ".".join(["a" * 63] * 3 + ["b" * 61])
    assert len(name) == 253

    assert load_config(write(tmp_path, f'domain = "{name}"\n')).domain == name


@pytest.mark.parametrize("raw", ["exämple.com", "日本語.jp", chr(0x212A) + "ample.com"])
def test_a_non_ascii_domain_is_refused_with_the_punycode_advice(tmp_path: Path, raw: str) -> None:
    """Reports carry the ``xn--`` form; the Kelvin sign would lower-case to an ASCII ``k``."""
    error = refusal(write(tmp_path, f'domain = "{raw}"\n'))

    assert error.reason is ConfigReason.NON_ASCII_DOMAIN
    assert error.key == "domain"
    assert "xn--" in error.detail


# ---------------------------------------------------------------------------
# The domain rules on a bare value (ADR-7)
# ---------------------------------------------------------------------------


def test_check_domain_normalizes_like_the_loader() -> None:
    """A value from a flag gets the same normalization as the one from the file."""
    assert check_domain(" Example.COM. ") == "example.com"


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        (42, ConfigReason.INVALID_DOMAIN),
        ("", ConfigReason.INVALID_DOMAIN),
        ("https://example.com", ConfigReason.INVALID_DOMAIN),
        ("a..com", ConfigReason.INVALID_DOMAIN),
        ("localhost", ConfigReason.INVALID_DOMAIN),
        ("a" * 64 + ".com", ConfigReason.INVALID_DOMAIN),
        ("exämple.com", ConfigReason.NON_ASCII_DOMAIN),
        (chr(0x212A) + "ample.com", ConfigReason.NON_ASCII_DOMAIN),
    ],
    ids=[
        "integer",
        "empty",
        "scheme",
        "empty-label",
        "single-label",
        "label-64",
        "non-ascii",
        "kelvin-sign",
    ],
)
def test_check_domain_refuses_what_the_loader_refuses(value: object, reason: ConfigReason) -> None:
    """The same inputs fail with the same reasons, so the flag and the file agree."""
    with pytest.raises(ConfigError) as caught:
        check_domain(value)

    assert caught.value.reason is reason


def test_check_domain_reports_the_key_it_was_given() -> None:
    """The refusal names the flag when the value came from one, and ``domain`` by default."""
    with pytest.raises(ConfigError) as default:
        check_domain("localhost")
    with pytest.raises(ConfigError) as flag:
        check_domain("localhost", key="--domain")

    assert default.value.key == "domain"
    assert flag.value.key == "--domain"


def test_check_domain_cleans_a_hostile_key() -> None:
    """The key is cleaned like any key of a ``ConfigError``: a flag name is still text."""
    with pytest.raises(ConfigError) as caught:
        check_domain("localhost", key="--do\nmain‮")

    assert caught.value.key == "--do main"


@pytest.mark.parametrize(
    ("key", "suggestion"),
    [("domian", "domain"), ("sender", "senders")],
    ids=["domain", "senders"],
)
def test_an_unknown_key_is_refused_and_a_close_one_is_suggested(
    tmp_path: Path, key: str, suggestion: str
) -> None:
    """A typo must not silently turn every sender into unknown (ADR-1)."""
    error = refusal(write(tmp_path, f'{_VALID}{key} = "x"\n'))

    assert error.reason is ConfigReason.UNKNOWN_KEY
    assert error.key == key
    assert suggestion in error.detail


def test_an_unrelated_unknown_key_has_no_suggestion(tmp_path: Path) -> None:
    """Only a close match is offered; a guess that is far off would mislead."""
    error = refusal(write(tmp_path, f"{_VALID}colour = 1\n"))

    assert error.reason is ConfigReason.UNKNOWN_KEY
    assert "did you mean" not in error.detail


def test_an_unknown_table_is_refused_like_an_unknown_key(tmp_path: Path) -> None:
    """The format defines three top-level keys; a table of another name is not one of them."""
    error = refusal(write(tmp_path, f"{_VALID}[sender]\nresend = 'Example Mailer'\n"))

    assert error.reason is ConfigReason.UNKNOWN_KEY
    assert error.key == "sender"


def test_a_hostile_unknown_key_is_cleaned_in_the_error(tmp_path: Path) -> None:
    """The key is arbitrary text from the file; the error must be safe to print (RF-05)."""
    hostile = "a\\nb\\u202ec\\u0085" + "x" * 300
    error = refusal(write(tmp_path, f'{_VALID}"{hostile}" = 1\n'))

    assert error.reason is ConfigReason.UNKNOWN_KEY
    assert error.key.startswith("a bc")
    assert len(error.key) == 100
    assert not any(char in error.key for char in "\n‮\u0085")


# ---------------------------------------------------------------------------
# The selector map (RF-03, RF-04, RF-05)
# ---------------------------------------------------------------------------


def test_selectors_are_stored_lower_case_and_the_map_is_read_only(tmp_path: Path) -> None:
    """Lookups are case-insensitive because the stored keys are all lower case."""
    config = load_config(write(tmp_path, f'{_VALID}[senders]\nResend = "Example Mailer"\n'))

    assert dict(config.senders) == {"resend": "Example Mailer"}
    with pytest.raises(TypeError):
        config.senders["zoho"] = "x"  # type: ignore[index]  # the map is a read-only view


@pytest.mark.parametrize("first", ["Resend", "resend"])
def test_selectors_differing_only_by_case_are_a_duplicate(tmp_path: Path, first: str) -> None:
    """Keeping one silently would be a guess; the same one is named whichever comes first."""
    second = "resend" if first == "Resend" else "Resend"
    error = refusal(write(tmp_path, f'{_VALID}[senders]\n"{first}" = "One"\n"{second}" = "Two"\n'))

    assert error.reason is ConfigReason.DUPLICATE_SELECTOR
    assert error.key == "resend"


@pytest.mark.parametrize(
    "key",
    ['""', '"two words"', '"bad key!"', '"a\\n"', '"sélecteur"', '"a/b"'],
    ids=["empty", "space", "punctuation", "trailing-newline", "non-ascii", "slash"],
)
def test_a_selector_dkim_cannot_have_is_refused(tmp_path: Path, key: str) -> None:
    """Only letters, digits, ``.``, ``-`` and ``_`` are accepted; the whole key is matched."""
    error = refusal(write(tmp_path, f'{_VALID}[senders]\n{key} = "Example Mailer"\n'))

    assert error.reason is ConfigReason.INVALID_SELECTOR


def test_senders_that_is_not_a_table_is_refused(tmp_path: Path) -> None:
    """``senders = "x"`` is a type mistake, not an empty map."""
    error = refusal(write(tmp_path, f'{_VALID}senders = "x"\n'))

    assert error.reason is ConfigReason.WRONG_TYPE
    assert error.key == "senders"


@pytest.mark.parametrize(
    "value",
    ["42", '""', '"   "', f'"{"n" * (MAX_SERVICE_NAME + 1)}"', '["a"]', "{ x = 'y' }"],
    ids=["integer", "empty", "blank", "101-characters", "list", "nested-table"],
)
def test_a_service_name_that_is_not_a_usable_string_is_refused(tmp_path: Path, value: str) -> None:
    """The name is what the owner will read in the summary: it must be a short, real string."""
    error = refusal(write(tmp_path, f"{_VALID}[senders]\nresend = {value}\n"))

    assert error.reason is ConfigReason.INVALID_SERVICE_NAME
    assert error.key == "resend"


def test_a_dotted_key_is_read_as_a_nested_table_and_refused(tmp_path: Path) -> None:
    """``a.b = "x"`` is TOML for a table ``a``; nested forms are reserved for later (RF-04)."""
    error = refusal(write(tmp_path, f'{_VALID}[senders]\na.b = "x"\n'))

    assert error.reason is ConfigReason.INVALID_SERVICE_NAME
    assert error.key == "a"


def test_a_quoted_dotted_selector_is_accepted(tmp_path: Path) -> None:
    """The way to write a selector that contains a dot, as the README will say."""
    config = load_config(write(tmp_path, f'{_VALID}[senders]\n"a.b" = "Example Campaigns"\n'))

    assert dict(config.senders) == {"a.b": "Example Campaigns"}


@pytest.mark.parametrize(
    "escape",
    ["\\n", "\\r", "\\t", "\\u202e", "\\u0085", "\\u200b", "\\u2028"],
    ids=["line-feed", "carriage-return", "tab", "bidi-override", "c1", "zero-width", "separator"],
)
def test_a_forbidden_character_in_a_service_name_is_refused(tmp_path: Path, escape: str) -> None:
    """A name is written on purpose, so a control character is a mistake to fix, not to repair."""
    error = refusal(write(tmp_path, f'{_VALID}[senders]\nresend = "Example{escape}Mailer"\n'))

    assert error.reason is ConfigReason.FORBIDDEN_CHARACTER
    assert error.key == "resend"


def test_a_service_name_is_stripped_when_stored(tmp_path: Path) -> None:
    """Spaces around a name are padding, not part of it."""
    config = load_config(write(tmp_path, f'{_VALID}[senders]\nresend = "  Example Mailer  "\n'))

    assert dict(config.senders) == {"resend": "Example Mailer"}


def test_a_name_of_exactly_the_limit_is_accepted(tmp_path: Path) -> None:
    """The limit is inclusive."""
    name = "n" * MAX_SERVICE_NAME

    config = load_config(write(tmp_path, f'{_VALID}[senders]\nresend = "{name}"\n'))

    assert config.senders["resend"] == name


@pytest.mark.parametrize("senders", ["", "[senders]\n"], ids=["absent", "empty"])
def test_an_absent_or_empty_senders_table_is_accepted(tmp_path: Path, senders: str) -> None:
    """A first run on a new domain is a legitimate case: every sender will be unknown."""
    config = load_config(write(tmp_path, _VALID + senders))

    assert dict(config.senders) == {}


# ---------------------------------------------------------------------------
# The [fetch] table (spec 003 ADR-7, spec 009 ADR-12)
# ---------------------------------------------------------------------------


def test_a_file_without_a_fetch_table_gives_empty_settings(tmp_path: Path) -> None:
    """Absent is not an error: every field stays ``None`` for the flags and defaults to fill."""
    config = load_config(write(tmp_path, _VALID))

    assert config.fetch == FetchSettings()


def test_the_four_keys_of_the_fetch_table_are_read(tmp_path: Path) -> None:
    """Host, user, port and folder come back as the file wrote them, stripped."""
    table = '[fetch]\nhost = " imap.example.com "\nuser = "reports"\nport = 143\nfolder = "DMARC"\n'

    config = load_config(write(tmp_path, _VALID + table))

    assert config.fetch == FetchSettings("imap.example.com", "reports", 143, "DMARC")


def test_a_fetch_table_may_hold_only_some_keys(tmp_path: Path) -> None:
    """The flags fill the rest, so a partial table is valid."""
    config = load_config(write(tmp_path, f'{_VALID}[fetch]\nhost = "imap.example.com"\n'))

    assert config.fetch == FetchSettings(host="imap.example.com")


def test_a_folder_name_may_hold_a_space(tmp_path: Path) -> None:
    """Only a host and a login are one word; a mailbox folder is not."""
    config = load_config(write(tmp_path, f'{_VALID}[fetch]\nfolder = "DMARC reports"\n'))

    assert config.fetch.folder == "DMARC reports"


def test_fetch_that_is_not_a_table_is_refused(tmp_path: Path) -> None:
    """``fetch = "x"`` is a mistake the loader names instead of ignoring."""
    error = refusal(write(tmp_path, 'fetch = "x"\n' + _VALID))

    assert error.reason is ConfigReason.WRONG_TYPE
    assert error.key == "fetch"


@pytest.mark.parametrize("key", ["password", "Password", "passwd", "imap_pass", "secret", "token"])
def test_a_key_that_would_hold_a_password_is_refused_by_name(tmp_path: Path, key: str) -> None:
    """The password never lives in the file; the refusal says where it goes."""
    error = refusal(write(tmp_path, f'{_VALID}[fetch]\n{key} = "hunter2"\n'))

    assert error.reason is ConfigReason.PASSWORD_NOT_ALLOWED
    assert error.key == f"fetch.{key}"
    assert "--password-file" in error.detail
    assert "hunter2" not in str(error)


def test_an_unknown_fetch_key_is_refused_and_a_close_one_is_suggested(tmp_path: Path) -> None:
    """The strict reading of the file reaches inside ``[fetch]``."""
    error = refusal(write(tmp_path, f'{_VALID}[fetch]\nhots = "imap.example.com"\n'))

    assert error.reason is ConfigReason.UNKNOWN_KEY
    assert error.key == "fetch.hots"
    assert "host" in error.detail


@pytest.mark.parametrize("key", ["to", "since", "limit", "cafile"])
def test_the_other_flags_are_not_keys_of_the_table(tmp_path: Path, key: str) -> None:
    """A path or a date does not belong in a shared file (ADR-12)."""
    error = refusal(write(tmp_path, f"{_VALID}[fetch]\n{key} = 1\n"))

    assert error.reason is ConfigReason.UNKNOWN_KEY
    assert error.key == f"fetch.{key}"


@pytest.mark.parametrize(
    "line",
    [
        "host = 1",
        'host = ""',
        'host = "   "',
        'host = "imap example.com"',
        'user = ["a"]',
        'user = "a b"',
        'folder = ""',
        "folder = 7",
        'port = "993"',
        "port = 0",
        "port = 65536",
        "port = true",
        "port = 993.0",
    ],
)
def test_a_fetch_value_of_the_wrong_kind_is_refused(tmp_path: Path, line: str) -> None:
    """The same ranges the flags have: a string where a string goes, a port in 1..65535."""
    error = refusal(write(tmp_path, f"{_VALID}[fetch]\n{line}\n"))

    assert error.reason is ConfigReason.INVALID_FETCH_VALUE
    assert error.key == f"fetch.{line.split()[0]}"


def test_the_edges_of_the_port_are_accepted(tmp_path: Path) -> None:
    """1 and 65535 are ports."""
    for port in (1, 65535):
        config = load_config(write(tmp_path, f"{_VALID}[fetch]\nport = {port}\n"))
        assert config.fetch.port == port


@pytest.mark.parametrize("key", ["host", "user", "folder"])
@pytest.mark.parametrize("escape", ["\\n", "\\u202e", "\\u0085", "\\u200b"])
def test_a_control_or_format_character_in_a_fetch_value_is_refused(
    tmp_path: Path, key: str, escape: str
) -> None:
    """A line break in a folder would end the IMAP command line and start another one."""
    error = refusal(write(tmp_path, f'{_VALID}[fetch]\n{key} = "a{escape}b"\n'))

    assert error.reason is ConfigReason.FORBIDDEN_CHARACTER
    assert error.key == f"fetch.{key}"


def test_the_fetch_table_is_checked_after_the_senders(tmp_path: Path) -> None:
    """The fixed order grows by one step: file, parse, keys, domain, senders, fetch."""
    text = f"{_VALID}[senders]\nresend = 42\n[fetch]\nport = 0\n"

    assert refusal(write(tmp_path, text)).reason is ConfigReason.INVALID_SERVICE_NAME


def test_two_bad_fetch_keys_report_the_same_one_in_any_order(tmp_path: Path) -> None:
    """Keys are visited in sorted order, not in the order of the file."""
    keys = ("zzz = 1", "aaa = 2")
    found = {
        refusal(write(tmp_path, f"{_VALID}[fetch]\n{first}\n{second}\n")).key
        for first, second in (keys, keys[::-1])
    }

    assert found == {"fetch.aaa"}


# ---------------------------------------------------------------------------
# Order and determinism (RF-07, RNF-05)
# ---------------------------------------------------------------------------


def test_a_file_with_two_problems_reports_the_same_one_in_any_order(tmp_path: Path) -> None:
    """The first problem found does not depend on the order of the lines (RF-07)."""
    lines = ['domain = "localhost"', "colour = 1", "[senders]", "resend = 42"]
    reasons = set()
    for ordered in (lines, [lines[1], lines[0], lines[2], lines[3]]):
        reasons.add(refusal(write(tmp_path, "\n".join(ordered) + "\n")).reason)

    assert reasons == {ConfigReason.UNKNOWN_KEY}


def test_the_domain_is_checked_before_the_senders(tmp_path: Path) -> None:
    """The fixed order: file, parse, keys, domain, senders."""
    error = refusal(write(tmp_path, 'domain = "localhost"\n[senders]\nresend = 42\n'))

    assert error.reason is ConfigReason.INVALID_DOMAIN


def test_two_bad_selectors_report_the_same_one_in_any_order(tmp_path: Path) -> None:
    """Selectors are visited in sorted order, not in the order of the file."""
    keys = ('"b" = 1', '"a" = 2')
    found = {
        refusal(write(tmp_path, f"{_VALID}[senders]\n{first}\n{second}\n")).key
        for first, second in (keys, keys[::-1])
    }

    assert found == {"a"}


def test_the_same_content_in_two_orders_gives_equal_configs(tmp_path: Path) -> None:
    """Equal values whatever the order of the keys (RNF-05)."""
    one = write(
        tmp_path,
        f'{_VALID}[senders]\nzoho = "Example Mail"\nresend = "Example Mailer"\n',
        "one.toml",
    )
    other = write(
        tmp_path,
        f'{_VALID}[senders]\nresend = "Example Mailer"\nzoho = "Example Mail"\n',
        "other.toml",
    )

    assert load_config(one) == load_config(other)
    assert list(load_config(one).senders) == ["resend", "zoho"]
