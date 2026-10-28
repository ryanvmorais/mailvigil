"""
The configuration file: the domain the reports are about and the DKIM selector to service map.

Only the owner knows which selector is which service, so the answer comes from a short TOML file.
Unlike a report, which is third-party text shown despite being dirty, the file is written on purpose
and feeds a security decision: every problem is a refusal that stops the load, never a repair
(ADR-1). The loader takes a path and nothing else, prints nothing and reads no environment; where
the file lives is the command's job (RNF-02, RNF-03).
"""

from __future__ import annotations

import difflib
import re
import stat
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any

from mailvigil.text import clean_text, has_dropped_characters, normalize_domain

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
_ALLOWED_KEYS = ("domain", "senders")

# DNS limits: 253 characters in all, 63 per label, letters-digits-hyphen with no hyphen at the ends.
_MAX_DOMAIN = 253
_LABEL = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?")

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
        UNKNOWN_KEY (str): A top-level key or table the format does not define.
        MISSING_DOMAIN (str): There is no ``domain``.
        INVALID_DOMAIN (str): Not a string, empty, or not a plausible host name.
        NON_ASCII_DOMAIN (str): The domain must be written in its ``xn--`` form.
        WRONG_TYPE (str): ``senders`` is not a table.
        INVALID_SELECTOR (str): A selector key a DKIM selector cannot be.
        DUPLICATE_SELECTOR (str): Two selector keys that differ only by case.
        INVALID_SERVICE_NAME (str): Not a string, blank, too long, or a nested value.
        FORBIDDEN_CHARACTER (str): A control, format or separator character in a name.
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
class Config:
    """
    A loaded configuration.

    Attributes:
        domain (str): The domain the reports are about: lower case, no trailing dot.
        senders (Mapping[str, str]): Lower-case DKIM selector to service name, as a read-only view.
            The loader builds it in sorted order, so two loads of the same content are equal.
    """

    domain: str
    senders: Mapping[str, str]


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
        detail = f'did you mean "{close[0]}"?' if close else "allowed keys: domain, senders"
        raise ConfigError(ConfigReason.UNKNOWN_KEY, key, detail)


def _read_domain(table: dict[str, Any]) -> str:
    """
    Validate and normalize the domain (step 6).

    Args:
        table (dict[str, Any]): The parsed file.

    Returns:
        str: The normalized domain.

    Raises:
        ConfigError: ``MISSING_DOMAIN``, ``INVALID_DOMAIN`` or ``NON_ASCII_DOMAIN``.
    """
    if "domain" not in table:
        raise ConfigError(ConfigReason.MISSING_DOMAIN, "domain", "the file has no domain")
    value = table["domain"]
    if not isinstance(value, str):
        raise ConfigError(ConfigReason.INVALID_DOMAIN, "domain", "the domain must be a string")
    # Checked before lower-casing: the Kelvin sign (U+212A) lower-cases to an ASCII ``k``, which
    # would let a different name through as if it were plain.
    if not value.strip().isascii():
        raise ConfigError(
            ConfigReason.NON_ASCII_DOMAIN, "domain", "write the domain in its xn-- (punycode) form"
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
        raise ConfigError(ConfigReason.INVALID_DOMAIN, "domain", "not a plausible host name")
    return domain


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
        senders[selector] = name
    return senders


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def load_config(path: Path) -> Config:
    """
    Load a configuration file.

    The checks run in a fixed order and the first failure is the one reported (RF-07): the file,
    its bytes, its TOML, the top-level keys, the domain, then the selector map.

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
    return Config(domain, MappingProxyType(senders))
