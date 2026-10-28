"""
Sender identification: which configured service signed a record, and whether it can be trusted.

The owner maps DKIM selectors to service names in the configuration; this module reads one
``Record`` against that map and answers with an ``Identification``. It looks only at each DKIM
block's selector, signer domain and result (ADR-3): combining the answer with the evaluated results,
the IP or the volume is the summary's job. It does no I/O, prints nothing and never raises on
report content, which is already sanitized.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from mailvigil.config import Config
from mailvigil.reports import Record
from mailvigil.text import is_within_domain

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------


class Outcome(StrEnum):
    """
    What a record's DKIM signatures say about who sent it.

    Attributes:
        KNOWN: A configured selector, passing, signed under the owner's domain.
        FOREIGN_DOMAIN: A configured selector signed under someone else's domain.
        FAILING_SIGNATURE: A configured selector, the owner's domain, a result that is not ``pass``.
        UNKNOWN: No configured selector at all.
    """

    KNOWN = "known"
    FOREIGN_DOMAIN = "foreign_domain"
    FAILING_SIGNATURE = "failing_signature"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Identification:
    """
    The answer for one record. It carries no printable label: that is spec 006's.

    Attributes:
        outcome (Outcome): The classification.
        service (str): The service name when ``KNOWN``, otherwise empty. Default: empty.
        selector (str): The configured selector that matched, lower case; empty when ``UNKNOWN``.
            Default: empty.
    """

    outcome: Outcome
    service: str = ""
    selector: str = ""


# ---------------------------------------------------------------------------
# Identification
# ---------------------------------------------------------------------------


def identify_sender(record: Record, config: Config) -> Identification:
    """
    Say which configured service sent a record.

    One pass over the DKIM blocks in document order, each classified on its own. The first passing
    block under the owner's domain wins at once. Otherwise the answer is the first foreign block,
    else the first failing one, else unknown: the more suspicious reading comes first (ADR-2).

    Args:
        record (Record): The row of the report.
        config (Config): The loaded configuration; its selectors are lower case.

    Returns:
        Identification: The outcome, with the service and selector when there is one.
    """
    foreign: Identification | None = None
    failing: Identification | None = None
    for block in record.dkim:
        selector = block.selector.strip().lower()
        # An empty selector or signer is "not said", never a match, even against an odd map.
        if not selector or not block.domain or selector not in config.senders:
            continue
        # The domain test comes first, so a foreign signature that also failed stays foreign.
        if not is_within_domain(block.domain, config.domain):
            foreign = foreign or Identification(Outcome.FOREIGN_DOMAIN, selector=selector)
        elif block.result.strip().lower() != "pass":
            failing = failing or Identification(Outcome.FAILING_SIGNATURE, selector=selector)
        else:
            return Identification(Outcome.KNOWN, config.senders[selector], selector)
    return foreign or failing or Identification(Outcome.UNKNOWN)
