"""
The Portuguese text without its accents, and the rule that says when a stream gets which.

``PORTUGUESE`` is written with accents. ``PORTUGUESE_ASCII`` is the same catalog with every accent
removed, one character for one (``não`` to ``nao``), so no width changes and the two cannot say
different things. ``catalog_for_streams`` picks between them from what the streams can carry (spec
006 ADR-9): the accents go only where the reader is known to agree with the writer.
"""

from __future__ import annotations

import codecs
import dataclasses
import sys
import unicodedata
from collections.abc import Iterable, Mapping
from types import MappingProxyType
from typing import Any, TextIO

from mailvigil.messages.model import Messages, Plural
from mailvigil.messages.pt_br import PORTUGUESE

# ---------------------------------------------------------------------------
# Folding
# ---------------------------------------------------------------------------


def fold_text(text: str) -> str:
    """
    Remove the accents of a text.

    Args:
        text (str): Any text.

    Returns:
        str: The text decomposed (NFD) with the combining marks dropped, so ``ç`` is ``c`` and ``ã``
            is ``a``. A letter that does not decompose is left as it was.
    """
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(char for char in decomposed if unicodedata.category(char) != "Mn")


def _fold(value: Any) -> Any:
    """
    Fold every string inside a value of the catalog.

    Args:
        value (Any): A string, a ``Plural``, a catalog dataclass, a mapping or a set of them, or
            anything else (an enum, a number), which comes back as it is.

    Returns:
        Any: The same shape with the strings folded. Mapping keys are left alone: they are enums.
    """
    # ``type(...) is str`` and not ``isinstance``: a ``StrEnum`` is a ``str`` and must stay itself.
    if type(value) is str:
        return fold_text(value)
    if isinstance(value, Plural):
        return Plural(fold_text(value.one), fold_text(value.many))
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return type(value)(
            **{field.name: _fold(getattr(value, field.name)) for field in dataclasses.fields(value)}
        )
    if isinstance(value, Mapping):
        return MappingProxyType({key: _fold(item) for key, item in value.items()})
    if isinstance(value, frozenset):
        return frozenset(_fold(item) for item in value)
    return value


def fold_ascii(messages: Messages) -> Messages:
    """
    Make the catalog without accents.

    Args:
        messages (Messages): A catalog.

    Returns:
        Messages: A new catalog, equal to the first with every accent removed. A catalog without
            accents comes back equal to itself.
    """
    folded: Messages = _fold(messages)
    return folded


# The catalog for a stream that cannot be trusted with accents, made once at import.
PORTUGUESE_ASCII = fold_ascii(PORTUGUESE)

# ---------------------------------------------------------------------------
# Which catalog a run gets
# ---------------------------------------------------------------------------


def _is_utf8(stream: TextIO) -> bool:
    """
    Tell whether a stream writes UTF-8.

    Args:
        stream (TextIO): Standard output or standard error.

    Returns:
        bool: ``True`` when its encoding is UTF-8; ``False`` for any other, for none, or for a name
            Python does not know.
    """
    name = getattr(stream, "encoding", None)
    if not name:
        return False
    try:
        return codecs.lookup(name).name == "utf-8"
    except LookupError:
        return False


def _is_console(stream: TextIO) -> bool:
    """
    Tell whether a stream is a terminal.

    Args:
        stream (TextIO): Standard output or standard error.

    Returns:
        bool: ``True`` when ``isatty`` says so; ``False`` for a pipe, a file or a closed stream.
    """
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError):
        return False


def _on_windows() -> bool:
    """
    Tell whether the program runs on Windows; a function so a test can say it does or does not.

    Returns:
        bool: ``True`` on Windows.
    """
    return sys.platform == "win32"


def accents_allowed(streams: Iterable[TextIO]) -> bool:
    """
    Tell whether the Portuguese text may carry accents on these streams (spec 006 ADR-9).

    Every stream must write UTF-8. On Windows each must also be a console: Python talks to the
    console directly, but a pipe or a file is read by ``cmd.exe``, ``more`` or ``type`` in the OEM
    code page, whatever Python wrote. Elsewhere a UTF-8 stream is the norm for both ends.

    Args:
        streams (Iterable[TextIO]): Where the text goes: standard output and standard error.

    Returns:
        bool: ``True`` when the accented catalog is safe.
    """
    windows = _on_windows()
    return all(_is_utf8(stream) and (not windows or _is_console(stream)) for stream in streams)


def catalog_for_streams(messages: Messages, streams: Iterable[TextIO]) -> Messages:
    """
    Pick the catalog the text of a run is written with.

    Args:
        messages (Messages): The language the user asked for.
        streams (Iterable[TextIO]): Where the text goes: standard output and standard error.

    Returns:
        Messages: ``PORTUGUESE_ASCII`` when the language is Portuguese and the streams cannot be
            trusted with accents; otherwise the catalog as it came. English has no accents.
    """
    if messages is PORTUGUESE and not accents_allowed(streams):
        return PORTUGUESE_ASCII
    return messages
