"""
The catalog of everything MailVigil says, one ``Messages`` per language (spec 006).

The renderers take a ``Messages`` and read every sentence from it; English is the default and
Brazilian Portuguese is the other language. Nothing here imports a renderer.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from mailvigil.messages.en import ENGLISH
from mailvigil.messages.fold import PORTUGUESE_ASCII, catalog_for_streams, fold_ascii
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
from mailvigil.messages.pt_br import PORTUGUESE

__all__ = [
    "ENGLISH",
    "LANGUAGES",
    "PORTUGUESE",
    "PORTUGUESE_ASCII",
    "CommonMessages",
    "FetchMessages",
    "HtmlMessages",
    "Messages",
    "Plural",
    "RefusalMessages",
    "SummaryMessages",
    "VerdictMessages",
    "catalog_for_streams",
    "fold_ascii",
    "language_by_code",
]

# The accepted codes, in lower case: the lookup folds the case of what the user typed.
LANGUAGES: Mapping[str, Messages] = MappingProxyType({"en": ENGLISH, "pt-br": PORTUGUESE})


def language_by_code(code: str) -> Messages:
    """
    Pick a language by the code the user typed.

    Args:
        code (str): The code, in any case.

    Returns:
        Messages: The catalog of that language.

    Raises:
        ValueError: For a code that is not one of ``LANGUAGES``.
    """
    try:
        return LANGUAGES[code.lower()]
    except KeyError:
        raise ValueError(f"unknown language: {code!r}") from None
