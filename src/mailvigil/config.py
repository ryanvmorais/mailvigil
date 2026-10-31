"""
The configuration file: the domain the reports are about, the maps from DKIM selector, SPF domain
and address range to service name and, for ``fetch``, the connection settings of the mailbox.

Only the owner knows which selector, SPF domain or address is which service, so the answer comes
from a short TOML file.
Unlike a report, which is third-party text shown despite being dirty, the file is written on purpose
and feeds a security decision: every problem is a refusal that stops the load, never a repair
(ADR-1). The loader takes a path and nothing else, prints nothing and reads no environment; where
the file lives is the command's job (RNF-02, RNF-03).
"""

from __future__ import annotations

import difflib
import ipaddress
import re
import stat
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any

from mailvigil.text import (
    clean_text,
    has_dropped_characters,
    is_within_domain,
    normalize_domain,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# The cap on the file, in bytes. A configuration is a few lines; the reader must not take an
# arbitrary file. Raising it is a decision for a spec, not a silent edit.
MAX_CONFIG_BYTES = 64 * 1024

# The longest service name, in characters: it is printed in a table column later.
MAX_SERVICE_NAME = 100

# The longest key kept in a ``ConfigError``: a mistyped key is arbitrary text from the file.
_MAX_KEY = 100

# The top-level keys of the format. Anything else is a typo or a feature from the future.
_ALLOWED_KEYS = ("domain", "senders", "spf", "ips", "fetch")

# The keys of the ``[fetch]`` table (ADR-7 of spec 003, ADR-12 of spec 009). The password is not one
# of them and never will be; ``to``, ``since``, ``limit`` and ``cafile`` stay flags.
_FETCH_KEYS = ("host", "user", "port", "folder")

# A ``[fetch]`` key that names a secret gets a refusal of its own instead of "unknown key", so the
# reader is told where the password goes, not only that it may not be here.
_SECRET_WORDS = ("pass", "secret", "token")

# The longest value kept for a host, a login or a folder; the file is capped anyway.
_MAX_FETCH_TEXT = 253

# DNS limits: 253 characters in all, 63 per label, letters-digits-hyphen with no hyphen at the ends.
_MAX_DOMAIN = 253
_LABEL = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?")

# The narrowest prefix an ``[ips]`` key may have (ADR-8 of spec 003): a wider range would name a
# whole network as the owner's, which is almost certainly a mistake. /16 is 65,536 IPv4 addresses.
MIN_PREFIX_V4 = 16
MIN_PREFIX_V6 = 32

# What a selector key can hold: enough to keep out whitespace, symbols and control characters.
_SELECTOR = re.compile(r"[A-Za-z0-9._-]+")

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------


class ConfigReason(StrEnum):
    """
    Why a configuration file was refused.

    The values are the stable keys spec 006 translates, so they never change once released.

    Attributes:
        UNREADABLE (str): Missing, no permission, a folder, or not a regular file.
        FILE_TOO_LARGE (str): The file is over the cap.
        NOT_UTF8 (str): The bytes are not valid UTF-8.
        MALFORMED_TOML (str): Not valid TOML, or nested too deeply to parse.
        UNKNOWN_KEY (str): A top-level key or table, or a ``[fetch]`` key, the format does not
            define.
        MISSING_DOMAIN (str): There is no ``domain``.
        INVALID_DOMAIN (str): Not a string, empty, or not a plausible host name.
        NON_ASCII_DOMAIN (str): The domain must be written in its ``xn--`` form.
        WRONG_TYPE (str): ``senders``, ``spf``, ``ips`` or ``fetch`` is not a table.
        INVALID_SELECTOR (str): A selector key a DKIM selector cannot be.
        DUPLICATE_SELECTOR (str): Two selector keys that differ only by case.
        INVALID_SERVICE_NAME (str): Not a string, blank, too long, or a nested value.
        FORBIDDEN_CHARACTER (str): A control, format or separator character in a name.
        INVALID_FETCH_VALUE (str): A ``[fetch]`` value of the wrong type or outside its range.
        PASSWORD_NOT_ALLOWED (str): A ``[fetch]`` key that would hold a password or a token.
        INVALID_SPF_DOMAIN (str): An ``[spf]`` key that is not a plausible host name.
        FOREIGN_SPF_DOMAIN (str): An ``[spf]`` key outside the configured domain.
        INVALID_IP_RANGE (str): An ``[ips]`` key that is no address range, has bits set past its
            prefix, or is wider than the floor.
        DUPLICATE_KEY (str): Two keys of ``[spf]`` or ``[ips]`` that mean the same thing.
    """

    UNREADABLE = "unreadable"
    FILE_TOO_LARGE = "file_too_large"
    NOT_UTF8 = "not_utf8"
    MALFORMED_TOML = "malformed_toml"
    UNKNOWN_KEY = "unknown_key"
    MISSING_DOMAIN = "missing_domain"
    INVALID_DOMAIN = "invalid_domain"
    NON_ASCII_DOMAIN = "non_ascii_domain"
    WRONG_TYPE = "wrong_type"
    INVALID_SELECTOR = "invalid_selector"
    DUPLICATE_SELECTOR = "duplicate_selector"
    INVALID_SERVICE_NAME = "invalid_service_name"
    FORBIDDEN_CHARACTER = "forbidden_character"
    INVALID_FETCH_VALUE = "invalid_fetch_value"
    PASSWORD_NOT_ALLOWED = "password_not_allowed"
    INVALID_SPF_DOMAIN = "invalid_spf_domain"
    FOREIGN_SPF_DOMAIN = "foreign_spf_domain"
    INVALID_IP_RANGE = "invalid_ip_range"
    DUPLICATE_KEY = "duplicate_key"


class ConfigError(Exception):
    """
    Raised when the configuration file is refused.

    It has the shape of 002's ``ReportRefused`` plus the key it concerns (RF-07).

    Attributes:
        reason (ConfigReason): The machine-readable cause.
        key (str): The key it concerns, cleaned and cut; empty for a file-level reason. It comes
            straight from the file, so it is never kept raw.
        detail (str): A short English explanation, for logs.
    """

    def __init__(self, reason: ConfigReason, key: str = "", detail: str = "") -> None:
        """
        Build a refusal.

        Args:
            reason (ConfigReason): The machine-readable cause.
            key (str, optional): The key it concerns, as written in the file. Default: empty.
            detail (str, optional): A short English explanation. Default: empty.
        """
        super().__init__(reason, key, detail)
        self.reason = reason
        self.key = clean_text(key, _MAX_KEY)
        self.detail = detail

    def __str__(self) -> str:
        """
        Describe the refusal for a log line.

        Returns:
            str: The reason value, then the key and the detail when there are any.
        """
        text = self.reason.value
        if self.key:
            text += f" [{self.key}]"
        if self.detail:
            text += f": {self.detail}"
        return text


@dataclass(frozen=True, slots=True)
class FetchSettings:
    """
    The connection settings of the ``[fetch]`` table; ``None`` is a key the file does not give.

    Attributes:
        host (str | None): The IMAP server.
        user (str | None): The login name.
        port (int | None): The port, 1 to 65535.
        folder (str | None): The mailbox folder to read.
    """

    host: str | None = None
    user: str | None = None
    port: int | None = None
    folder: str | None = None


IpNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network

_NO_NAMES: Mapping[str, str] = MappingProxyType({})
_NO_RANGES: Mapping[IpNetwork, str] = MappingProxyType({})


@dataclass(frozen=True, slots=True)
class Config:
    """
    A loaded configuration.

    Attributes:
        domain (str): The domain the reports are about: lower case, no trailing dot.
        senders (Mapping[str, str]): Lower-case DKIM selector to service name, as a read-only view.
            The loader builds it in sorted order, so two loads of the same content are equal.
        fetch (FetchSettings): The ``[fetch]`` table; every field is ``None`` when it is absent.
        spf (Mapping[str, str]): Lower-case SPF domain, within ``domain``, to service name
            (ADR-8). Default: empty.
        ranges (Mapping[IpNetwork, str]): Canonical address range to service name (ADR-8).
            Default: empty.
        range_lengths (Mapping[int, tuple[int, ...]]): The prefix lengths present in ``ranges``,
            longest first, by IP version (4 and 6). Derived, so a lookup masks the address once per
            length instead of scanning every range.
    """

    domain: str
    senders: Mapping[str, str]
    fetch: FetchSettings = FetchSettings()
    spf: Mapping[str, str] = _NO_NAMES
    ranges: Mapping[IpNetwork, str] = _NO_RANGES
    range_lengths: Mapping[int, tuple[int, ...]] = field(
        init=False, default=MappingProxyType({}), repr=False, compare=False
    )

    def __post_init__(self) -> None:
        """Derive ``range_lengths`` from ``ranges``."""
        lengths: dict[int, set[int]] = {}
        for network in self.ranges:
            lengths.setdefault(network.version, set()).add(network.prefixlen)
        derived = {
            version: tuple(sorted(found, reverse=True)) for version, found in lengths.items()
        }
        object.__setattr__(self, "range_lengths", MappingProxyType(derived))


# ---------------------------------------------------------------------------
# Reading the file (RF-01)
# ---------------------------------------------------------------------------


def _read_table(path: Path) -> dict[str, Any]:
    """
    Read the file and parse it (steps 1 to 4).

    Args:
        path (Path): The configuration file.

    Returns:
        dict[str, Any]: The parsed top-level table.

    Raises:
        ConfigError: ``UNREADABLE``, ``FILE_TOO_LARGE``, ``NOT_UTF8`` or ``MALFORMED_TOML``.
    """
    # 1. Only a regular file: a named pipe would block the run.
    try:
        if not stat.S_ISREG(path.stat().st_mode):
            raise ConfigError(ConfigReason.UNREADABLE, detail="not a regular file")
        # 2. The cap acts on the bytes actually read, not on a size from ``stat`` that could change.
        with path.open("rb") as stream:
            data = stream.read(MAX_CONFIG_BYTES + 1)
    except OSError as error:
        raise ConfigError(ConfigReason.UNREADABLE, detail=type(error).__name__) from None
    if len(data) > MAX_CONFIG_BYTES:
        raise ConfigError(ConfigReason.FILE_TOO_LARGE, detail=f"more than {MAX_CONFIG_BYTES} bytes")

    # 3. ``utf-8-sig`` drops the byte order mark that Windows editors add.
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ConfigError(ConfigReason.NOT_UTF8, detail="the file is not valid UTF-8") from None

    # 4. A file of nested arrays fits the size cap and still exhausts the parser's recursion.
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(ConfigReason.MALFORMED_TOML, detail=str(error)) from None
    except RecursionError:
        raise ConfigError(ConfigReason.MALFORMED_TOML, detail="nested too deeply") from None


# ---------------------------------------------------------------------------
# Checking the content (RF-02 to RF-05)
# ---------------------------------------------------------------------------


def _check_keys(table: dict[str, Any]) -> None:
    """
    Refuse the first top-level key the format does not define (step 5).

    Args:
        table (dict[str, Any]): The parsed file.

    Raises:
        ConfigError: ``UNKNOWN_KEY``, with the closest allowed key in the detail when there is one.
    """
    for key in sorted(table):
        if key in _ALLOWED_KEYS:
            continue
        close = difflib.get_close_matches(key, _ALLOWED_KEYS, n=1)
        detail = (
            f'did you mean "{close[0]}"?' if close else "allowed keys: " + ", ".join(_ALLOWED_KEYS)
        )
        raise ConfigError(ConfigReason.UNKNOWN_KEY, key, detail)


def check_domain(value: object, key: str = "domain") -> str:
    """
    Validate and normalize a domain: the rules of the file, usable on any value (ADR-7).

    The command applies the same rules to ``--domain``, so the flag and the file can never disagree
    about what a plausible domain is.

    Args:
        value (object): The domain as the file or the flag gave it.
        key (str, optional): What to name in a refusal, such as ``--domain``. Default: ``domain``.

    Returns:
        str: The normalized domain.

    Raises:
        ConfigError: ``INVALID_DOMAIN`` or ``NON_ASCII_DOMAIN``, naming ``key``.
    """
    if not isinstance(value, str):
        raise ConfigError(ConfigReason.INVALID_DOMAIN, key, "the domain must be a string")
    # Checked before lower-casing: the Kelvin sign (U+212A) lower-cases to an ASCII ``k``, which
    # would let a different name through as if it were plain.
    if not value.strip().isascii():
        raise ConfigError(
            ConfigReason.NON_ASCII_DOMAIN, key, "write the domain in its xn-- (punycode) form"
        )

    domain = normalize_domain(value)
    labels = domain.split(".")
    # The label rule excludes spaces, ``:``, ``/``, ``@``, empty labels and control characters in
    # one test; a scheme or a path fails it because ``:`` and ``/`` are not letters or digits.
    if (
        len(domain) > _MAX_DOMAIN
        or len(labels) < 2
        or not all(_LABEL.fullmatch(label) for label in labels)
    ):
        raise ConfigError(ConfigReason.INVALID_DOMAIN, key, "not a plausible host name")
    return domain


def _read_domain(table: dict[str, Any]) -> str:
    """
    Validate and normalize the domain of the file (step 6).

    Args:
        table (dict[str, Any]): The parsed file.

    Returns:
        str: The normalized domain.

    Raises:
        ConfigError: ``MISSING_DOMAIN``, ``INVALID_DOMAIN`` or ``NON_ASCII_DOMAIN``.
    """
    if "domain" not in table:
        raise ConfigError(ConfigReason.MISSING_DOMAIN, "domain", "the file has no domain")
    return check_domain(table["domain"])


def _read_senders(table: dict[str, Any]) -> dict[str, str]:
    """
    Validate the selector map (step 7).

    Args:
        table (dict[str, Any]): The parsed file.

    Returns:
        dict[str, str]: Lower-case selector to stripped service name, in sorted key order.

    Raises:
        ConfigError: ``WRONG_TYPE``, ``INVALID_SELECTOR``, ``DUPLICATE_SELECTOR``,
            ``INVALID_SERVICE_NAME`` or ``FORBIDDEN_CHARACTER``.
    """
    raw = table.get("senders", {})
    if not isinstance(raw, dict):
        raise ConfigError(ConfigReason.WRONG_TYPE, "senders", "senders must be a table")

    senders: dict[str, str] = {}
    # Sorted, so the first problem found does not depend on the order of the file (RNF-05).
    for key, value in sorted(raw.items(), key=lambda item: (item[0].lower(), item[0])):
        # ``fullmatch``: with ``match`` and ``$`` a trailing line break would slip through.
        if not _SELECTOR.fullmatch(key):
            raise ConfigError(ConfigReason.INVALID_SELECTOR, key, "not a DKIM selector")
        selector = key.lower()
        if selector in senders:
            raise ConfigError(ConfigReason.DUPLICATE_SELECTOR, key, "differs only by case")
        # A dotted key (``a.b = "x"``) is read by TOML as a nested table, so it lands here.
        senders[selector] = _service_name(key, value)
    return senders


def _service_name(key: str, value: object) -> str:
    """
    Validate the service name of one entry of ``[senders]``, ``[spf]`` or ``[ips]``.

    Args:
        key (str): The name to give a refusal, such as the entry's key or ``spf.<domain>``.
        value (object): The value the file gave.

    Returns:
        str: The stripped name.

    Raises:
        ConfigError: ``INVALID_SERVICE_NAME`` or ``FORBIDDEN_CHARACTER``.
    """
    if isinstance(value, dict):
        # TOML reads an unquoted dotted key as nested tables, the usual way to get here.
        raise ConfigError(
            ConfigReason.INVALID_SERVICE_NAME,
            key,
            'the name must be a string; write a key with dots in quotes: "a.b" = "name"',
        )
    if not isinstance(value, str):
        raise ConfigError(ConfigReason.INVALID_SERVICE_NAME, key, "the name must be a string")
    if has_dropped_characters(value):
        raise ConfigError(ConfigReason.FORBIDDEN_CHARACTER, key, "control or format character")
    name = value.strip()
    if not name or len(name) > MAX_SERVICE_NAME:
        raise ConfigError(
            ConfigReason.INVALID_SERVICE_NAME,
            key,
            f"the name must have 1 to {MAX_SERVICE_NAME} characters",
        )
    return name


def _read_spf(table: dict[str, Any], domain: str) -> dict[str, str]:
    """
    Validate the SPF domain map (step 8, ADR-8).

    Args:
        table (dict[str, Any]): The parsed file.
        domain (str): The configured domain: every key must be within it.

    Returns:
        dict[str, str]: Normalized SPF domain to stripped service name, in sorted key order.

    Raises:
        ConfigError: ``WRONG_TYPE``, ``INVALID_SPF_DOMAIN``, ``NON_ASCII_DOMAIN``,
            ``FOREIGN_SPF_DOMAIN``, ``DUPLICATE_KEY``, ``INVALID_SERVICE_NAME`` or
            ``FORBIDDEN_CHARACTER``.
    """
    raw = table.get("spf", {})
    if not isinstance(raw, dict):
        raise ConfigError(ConfigReason.WRONG_TYPE, "spf", "spf must be a table")

    spf: dict[str, str] = {}
    for key, value in sorted(raw.items(), key=lambda item: (item[0].lower(), item[0])):
        name = f"spf.{key}"
        # The value first: an unquoted dotted domain arrives as a table under its first label.
        service = _service_name(name, value)
        try:
            spf_domain = check_domain(key, name)
        except ConfigError as error:
            if error.reason is ConfigReason.INVALID_DOMAIN:
                raise ConfigError(
                    ConfigReason.INVALID_SPF_DOMAIN, name, "not a plausible host name"
                ) from None
            raise
        # The same test as a DKIM signer's: a domain outside the owner's can never align.
        if not is_within_domain(spf_domain, domain):
            raise ConfigError(
                ConfigReason.FOREIGN_SPF_DOMAIN, name, f"not {domain} or a subdomain of it"
            )
        if spf_domain in spf:
            raise ConfigError(ConfigReason.DUPLICATE_KEY, name, "the same domain written twice")
        spf[spf_domain] = service
    return spf


def _read_ranges(table: dict[str, Any]) -> dict[IpNetwork, str]:
    """
    Validate the address range map (step 9, ADR-8).

    Args:
        table (dict[str, Any]): The parsed file.

    Returns:
        dict[IpNetwork, str]: Canonical range to stripped service name, in sorted key order.

    Raises:
        ConfigError: ``WRONG_TYPE``, ``INVALID_IP_RANGE``, ``DUPLICATE_KEY``,
            ``INVALID_SERVICE_NAME`` or ``FORBIDDEN_CHARACTER``.
    """
    raw = table.get("ips", {})
    if not isinstance(raw, dict):
        raise ConfigError(ConfigReason.WRONG_TYPE, "ips", "ips must be a table")

    ranges: dict[IpNetwork, str] = {}
    for key, value in sorted(raw.items(), key=lambda item: (item[0].lower(), item[0])):
        name = f"ips.{key}"
        service = _service_name(name, value)
        try:
            # Strict: ``192.0.2.1/24`` has bits set past its prefix and is most likely a typo.
            network = ipaddress.ip_network(key.strip(), strict=True)
        except ValueError:
            raise ConfigError(
                ConfigReason.INVALID_IP_RANGE,
                name,
                "not an address range, or it has bits set past its prefix",
            ) from None
        floor = MIN_PREFIX_V4 if network.version == 4 else MIN_PREFIX_V6
        if network.prefixlen < floor:
            raise ConfigError(ConfigReason.INVALID_IP_RANGE, name, f"wider than the /{floor} floor")
        # A mapped range would never match: the lookup reads a mapped address as its IPv4 form.
        if network.version == 6 and network.network_address.ipv4_mapped is not None:
            raise ConfigError(
                ConfigReason.INVALID_IP_RANGE, name, "write an IPv4-mapped range as IPv4"
            )
        if network in ranges:
            raise ConfigError(ConfigReason.DUPLICATE_KEY, name, "the same range written twice")
        ranges[network] = service
    return ranges


def _fetch_text(table: dict[str, Any], key: str, *, spaces: bool) -> str | None:
    """
    Read one text value of ``[fetch]``.

    Args:
        table (dict[str, Any]): The ``[fetch]`` table.
        key (str): The key to read.
        spaces (bool): Whether the value may hold a space (a folder name may, a host may not).

    Returns:
        str | None: The stripped value, ``None`` when the key is absent.

    Raises:
        ConfigError: ``INVALID_FETCH_VALUE`` for a value that is not a string, is blank or is too
            long, or ``FORBIDDEN_CHARACTER`` for a control or format character.
    """
    if key not in table:
        return None
    name = f"fetch.{key}"
    value = table[key]
    if not isinstance(value, str):
        raise ConfigError(ConfigReason.INVALID_FETCH_VALUE, name, "the value must be a string")
    if has_dropped_characters(value):
        raise ConfigError(ConfigReason.FORBIDDEN_CHARACTER, name, "control or format character")
    text = value.strip()
    if not text or len(text) > _MAX_FETCH_TEXT or (not spaces and any(c.isspace() for c in text)):
        raise ConfigError(
            ConfigReason.INVALID_FETCH_VALUE,
            name,
            f"the value must have 1 to {_MAX_FETCH_TEXT} characters"
            + ("" if spaces else " and no space"),
        )
    return text


def _read_fetch(table: dict[str, Any]) -> FetchSettings:
    """
    Validate the ``[fetch]`` table (step 10).

    The password has no key: a key that looks like one is refused with a reason of its own.

    Args:
        table (dict[str, Any]): The parsed file.

    Returns:
        FetchSettings: The settings the file gives; the rest stay ``None``.

    Raises:
        ConfigError: ``WRONG_TYPE``, ``PASSWORD_NOT_ALLOWED``, ``UNKNOWN_KEY``,
            ``INVALID_FETCH_VALUE`` or ``FORBIDDEN_CHARACTER``.
    """
    raw = table.get("fetch", {})
    if not isinstance(raw, dict):
        raise ConfigError(ConfigReason.WRONG_TYPE, "fetch", "fetch must be a table")

    # Sorted, like the selector map, so the first problem does not depend on the file's order.
    for key in sorted(raw):
        if key in _FETCH_KEYS:
            continue
        name = f"fetch.{key}"
        if any(word in key.lower() for word in _SECRET_WORDS):
            raise ConfigError(
                ConfigReason.PASSWORD_NOT_ALLOWED,
                name,
                "the password is never kept in the file: use the prompt or --password-file",
            )
        close = difflib.get_close_matches(key, _FETCH_KEYS, n=1)
        detail = (
            f'did you mean "{close[0]}"?' if close else "allowed keys: " + ", ".join(_FETCH_KEYS)
        )
        raise ConfigError(ConfigReason.UNKNOWN_KEY, name, detail)

    port = raw.get("port")
    # ``bool`` is an ``int`` in Python: ``port = true`` must not read as port 1.
    if port is not None and (
        isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535
    ):
        raise ConfigError(
            ConfigReason.INVALID_FETCH_VALUE,
            "fetch.port",
            "the port must be a whole number 1-65535",
        )
    return FetchSettings(
        host=_fetch_text(raw, "host", spaces=False),
        user=_fetch_text(raw, "user", spaces=False),
        port=port,
        folder=_fetch_text(raw, "folder", spaces=True),
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def load_config(path: Path) -> Config:
    """
    Load a configuration file.

    The checks run in a fixed order and the first failure is the one reported (RF-07): the file,
    its bytes, its TOML, the top-level keys, the domain, the selector map, ``[spf]``, ``[ips]``,
    then ``[fetch]``.

    Args:
        path (Path): The TOML file. The loader never searches for one.

    Returns:
        Config: The immutable configuration.

    Raises:
        ConfigError: For any problem in the file; ``reason`` and ``key`` say which.
    """
    table = _read_table(path)
    _check_keys(table)
    domain = _read_domain(table)
    senders = _read_senders(table)
    spf = _read_spf(table, domain)
    ranges = _read_ranges(table)
    fetch = _read_fetch(table)
    return Config(
        domain, MappingProxyType(senders), fetch, MappingProxyType(spf), MappingProxyType(ranges)
    )
