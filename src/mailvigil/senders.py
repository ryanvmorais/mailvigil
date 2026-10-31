"""
Sender identification: which configured service sent a record, and whether it can be trusted.

The owner maps DKIM selectors, SPF domains and address ranges to service names in the
configuration; this module reads one ``Record`` against those maps and answers with an
``Identification``. A name counts only on a passing authentication aligned with the owner's domain
(ADR-8): a DKIM block, an SPF block, or, for an address range, any such block plus the address.
It looks at each block's selector, domain and result and, for a range, at the source address
(ADR-3): combining the answer with the evaluated results or the volume is the summary's job. It does
no I/O, prints nothing and never raises on report content, which is already sanitized.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from enum import StrEnum

from mailvigil.config import Config
from mailvigil.reports import Record
from mailvigil.text import is_within_domain, normalize_domain

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------


class Outcome(StrEnum):
    """
    What a record's authentication says about who sent it.

    Attributes:
        KNOWN: A configured selector, SPF domain or address range, authenticated as the owner.
        FOREIGN_DOMAIN: A configured selector signed under someone else's domain.
        FAILING_SIGNATURE: A configured selector, the owner's domain, a result that is not ``pass``.
        UNKNOWN: Nothing configured names the record.
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
        selector (str): The configured selector that matched, lower case; empty when the name came
            from an SPF domain or an address range, and when ``UNKNOWN``. Default: empty.
    """

    outcome: Outcome
    service: str = ""
    selector: str = ""


# ---------------------------------------------------------------------------
# Identification
# ---------------------------------------------------------------------------


def _passed_spf(record: Record, config: Config) -> str:
    """
    Find the first SPF block that passed on a configured SPF domain.

    Args:
        record (Record): The row of the report.
        config (Config): The loaded configuration; its SPF domains are within its domain.

    Returns:
        str: The service name, empty when no block qualifies.
    """
    for block in record.spf:
        # An empty domain is "not said", never a match.
        domain = normalize_domain(block.domain)
        if domain and block.result.strip().lower() == "pass" and domain in config.spf:
            return config.spf[domain]
    return ""


def _authenticated_as_owner(record: Record, config: Config) -> bool:
    """
    Say whether any DKIM or SPF block passed under the owner's domain.

    Args:
        record (Record): The row of the report.
        config (Config): The loaded configuration.

    Returns:
        bool: True when a passing block carries the owner's domain or a subdomain of it.
    """
    pairs = [(block.domain, block.result) for block in record.dkim]
    pairs += [(block.domain, block.result) for block in record.spf]
    return any(
        domain and result.strip().lower() == "pass" and is_within_domain(domain, config.domain)
        for domain, result in pairs
    )


def _range_service(record: Record, config: Config) -> str:
    """
    Find the service of the narrowest configured range holding the source address.

    The address is masked once per prefix length in the map, so a long map costs no more than a
    short one. An IPv4-mapped IPv6 address is read as its IPv4 form.

    Args:
        record (Record): The row of the report.
        config (Config): The loaded configuration.

    Returns:
        str: The service name, empty when no range holds the address or it is not an address.
    """
    if not config.ranges:
        return ""
    try:
        address = ipaddress.ip_address(record.source_ip)
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
            address = address.ipv4_mapped
        for length in config.range_lengths.get(address.version, ()):
            network = ipaddress.ip_network((address, length), strict=False)
            if network in config.ranges:
                return config.ranges[network]
    except ValueError:
        pass
    return ""


def identify_sender(record: Record, config: Config) -> Identification:
    """
    Say which configured service sent a record.

    Three ways to a name, the first that holds winning (ADR-8): a passing DKIM block under the
    owner's domain with a configured selector, a passing SPF block on a configured SPF domain, then
    the source address inside a configured range when the record also authenticated as the owner.
    When none holds, the answer is the first foreign DKIM block, else the first failing one, else
    unknown: the more suspicious reading comes first (ADR-2).

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

    # A pass on the owner's own SPF domain, or the owner's address plus proof of authentication,
    # is a name a stranger reusing a selector cannot have, so it beats foreign and failing.
    service = _passed_spf(record, config)
    if not service and _authenticated_as_owner(record, config):
        service = _range_service(record, config)
    if service:
        return Identification(Outcome.KNOWN, service)
    return foreign or failing or Identification(Outcome.UNKNOWN)
