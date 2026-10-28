"""
Tests of sender identification: which configured service sent a record, and how sure we are.

Isolation: nothing touches the disk. A ``Record`` and its ``DkimResult`` blocks are built in the
test and a ``Config`` by a small helper, from invented domains (``example.com``, ``example.org``)
and invented selectors and service names (RNF-07).
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from enum import StrEnum
from types import MappingProxyType

import pytest

from mailvigil.config import Config
from mailvigil.reports import DkimResult, Record
from mailvigil.senders import Identification, Outcome, identify_sender

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

# Two invented services, so no real one is named (RNF-07); selectors are lower case as the loader
# guarantees (ADR-5).
_SENDERS = {"newsletter": "Example Mailer", "mailbox": "Example Mail"}


def config(senders: dict[str, str] | None = None) -> Config:
    """
    Build a configuration for ``example.com`` without going through the file loader.

    Args:
        senders (dict[str, str] | None, optional): Selector (lower case) to service name. Default:
            two invented services.

    Returns:
        Config: The configuration.
    """
    return Config("example.com", MappingProxyType(_SENDERS if senders is None else senders))


def block(
    selector: str = "newsletter", domain: str = "example.com", result: str = "pass"
) -> DkimResult:
    """
    Build one DKIM block.

    Args:
        selector (str, optional): The ``s=`` selector. Default: ``newsletter``.
        domain (str, optional): The ``d=`` domain. Default: ``example.com``.
        result (str, optional): The DKIM verdict. Default: ``pass``.

    Returns:
        DkimResult: The block.
    """
    return DkimResult(domain=domain, selector=selector, result=result)


def identify(*blocks: DkimResult) -> Identification:
    """
    Identify the sender of a record that carries exactly these DKIM blocks.

    Args:
        *blocks (DkimResult): The blocks, in document order.

    Returns:
        Identification: The answer for ``example.com`` and the default senders.
    """
    return identify_sender(Record(dkim=blocks), config())


# ---------------------------------------------------------------------------
# The vocabulary
# ---------------------------------------------------------------------------


def test_outcome_members_are_unique_strings() -> None:
    """The outcomes are the stable keys later specs translate, so they are plain unique strings."""
    assert issubclass(Outcome, StrEnum)
    values = [member.value for member in Outcome]
    assert len(values) == len(set(values)) == 4
    assert {member.name for member in Outcome} == {
        "KNOWN",
        "FOREIGN_DOMAIN",
        "FAILING_SIGNATURE",
        "UNKNOWN",
    }


def test_identification_is_frozen() -> None:
    """An answer cannot be edited after the fact (RNF-04)."""
    answer = identify(block())
    with pytest.raises(FrozenInstanceError):
        answer.outcome = Outcome.UNKNOWN  # type: ignore[misc]  # frozen on purpose


def test_identification_defaults_are_empty_text() -> None:
    """Only the outcome is required; service and selector default to empty."""
    answer = Identification(Outcome.UNKNOWN)
    assert (answer.service, answer.selector) == ("", "")


# ---------------------------------------------------------------------------
# Known
# ---------------------------------------------------------------------------


def test_passing_signature_under_the_domain_is_known() -> None:
    """The configured selector, signed by the owner's domain and passing, names the service."""
    assert identify(block()) == Identification(Outcome.KNOWN, "Example Mailer", "newsletter")


def test_passing_signature_under_a_subdomain_is_known() -> None:
    """A service that signs with ``mail.example.com`` is still the owner's."""
    answer = identify(block(domain="mail.example.com"))
    assert answer.outcome is Outcome.KNOWN


def test_signer_domain_in_upper_case_with_a_dot_is_known() -> None:
    """The signer domain is normalized before the comparison."""
    answer = identify(block(domain="MAIL.Example.com."))
    assert answer.outcome is Outcome.KNOWN


def test_selector_is_compared_case_insensitively() -> None:
    """The map stores lower-case selectors; a report may spell them in any case."""
    answer = identify(block(selector="  NewsLetter "))
    assert answer == Identification(Outcome.KNOWN, "Example Mailer", "newsletter")


def test_result_is_compared_case_insensitively() -> None:
    """``PASS`` counts as a pass."""
    assert identify(block(result=" PASS ")).outcome is Outcome.KNOWN


def test_the_selector_decides_the_service() -> None:
    """Two configured selectors give two services."""
    assert identify(block(selector="mailbox")).service == "Example Mail"


# ---------------------------------------------------------------------------
# Failing signature
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("result", ["fail", "neutral", "temperror", "permerror", "none", ""])
def test_signature_not_passing_under_the_domain_is_failing(result: str) -> None:
    """Anything but ``pass`` from the owner's own service is a failing signature to fix."""
    answer = identify(block(result=result))
    assert answer == Identification(Outcome.FAILING_SIGNATURE, "", "newsletter")


# ---------------------------------------------------------------------------
# Foreign domain
# ---------------------------------------------------------------------------


def test_configured_selector_under_another_domain_is_foreign() -> None:
    """The selector is right but the signer is someone else: the service field stays empty."""
    answer = identify(block(domain="example.org"))
    assert answer == Identification(Outcome.FOREIGN_DOMAIN, "", "newsletter")


@pytest.mark.parametrize("domain", ["notexample.com", "example.com.evil.net", "com"])
def test_lookalike_signer_domains_are_not_subdomains(domain: str) -> None:
    """A plain suffix test would accept ``notexample.com``; the dot makes the difference (ADR-6)."""
    assert identify(block(domain=domain)).outcome is Outcome.FOREIGN_DOMAIN


def test_foreign_signature_that_also_failed_is_foreign() -> None:
    """The domain test comes before the result test."""
    answer = identify(block(domain="example.org", result="fail"))
    assert answer.outcome is Outcome.FOREIGN_DOMAIN


# ---------------------------------------------------------------------------
# Unknown
# ---------------------------------------------------------------------------


def test_record_without_dkim_blocks_is_unknown() -> None:
    """No signature at all: nobody to name."""
    assert identify() == Identification(Outcome.UNKNOWN)


def test_selector_not_configured_is_unknown() -> None:
    """A selector the owner did not list says nothing about who sent it."""
    assert identify(block(selector="other")) == Identification(Outcome.UNKNOWN)


def test_empty_selector_never_matches() -> None:
    """An empty selector is never a key, even if the map held an empty one by hand."""
    answer = identify_sender(Record(dkim=(block(selector=""),)), config({"": "Nobody"}))
    assert answer.outcome is Outcome.UNKNOWN


def test_blank_selector_never_matches() -> None:
    """A selector of spaces is stripped to empty first."""
    answer = identify_sender(Record(dkim=(block(selector="   "),)), config({"": "Nobody"}))
    assert answer.outcome is Outcome.UNKNOWN


def test_empty_signer_never_matches() -> None:
    """A block without a ``d=`` domain cannot be placed under the owner's domain."""
    assert identify(block(domain="")).outcome is Outcome.UNKNOWN


def test_empty_senders_map_makes_everything_unknown() -> None:
    """The advised starting file has an empty ``[senders]``: every record is unknown."""
    answer = identify_sender(Record(dkim=(block(),)), config({}))
    assert answer.outcome is Outcome.UNKNOWN


# ---------------------------------------------------------------------------
# Several blocks and precedence
# ---------------------------------------------------------------------------


def test_two_qualifying_blocks_give_the_first() -> None:
    """Document order breaks the tie, so the answer is deterministic (RNF-05)."""
    answer = identify(block(selector="mailbox"), block(selector="newsletter"))
    assert answer == Identification(Outcome.KNOWN, "Example Mail", "mailbox")


def test_foreign_plus_failing_gives_foreign() -> None:
    """The more suspicious reading comes first (ADR-2), whatever the order."""
    foreign = block(domain="example.org")
    failing = block(selector="mailbox", result="fail")
    assert identify(failing, foreign).outcome is Outcome.FOREIGN_DOMAIN
    assert identify(foreign, failing).outcome is Outcome.FOREIGN_DOMAIN


def test_two_foreign_blocks_give_the_first() -> None:
    """Within a kind, the first block in document order wins."""
    answer = identify(
        block(selector="mailbox", domain="example.org"),
        block(selector="newsletter", domain="example.net"),
    )
    assert answer == Identification(Outcome.FOREIGN_DOMAIN, "", "mailbox")


def test_two_failing_blocks_give_the_first() -> None:
    """Same rule for failing signatures."""
    answer = identify(
        block(selector="mailbox", result="fail"), block(selector="newsletter", result="fail")
    )
    assert answer == Identification(Outcome.FAILING_SIGNATURE, "", "mailbox")


@pytest.mark.parametrize("known_first", [True, False])
def test_foreign_plus_known_gives_known(known_first: bool) -> None:
    """A stranger's extra signature does not hide the owner's service (ADR-2)."""
    known = block(selector="mailbox")
    foreign = block(domain="example.org")
    answer = identify(known, foreign) if known_first else identify(foreign, known)
    assert answer == Identification(Outcome.KNOWN, "Example Mail", "mailbox")


@pytest.mark.parametrize("known_first", [True, False])
def test_failing_plus_known_gives_known(known_first: bool) -> None:
    """A broken second signature does not hide the one that passed."""
    known = block(selector="mailbox")
    failing = block(result="fail")
    answer = identify(known, failing) if known_first else identify(failing, known)
    assert answer == Identification(Outcome.KNOWN, "Example Mail", "mailbox")


def test_unconfigured_blocks_are_skipped_among_configured_ones() -> None:
    """An unknown selector before a known one does not stop the search."""
    answer = identify(block(selector="other"), block())
    assert answer.outcome is Outcome.KNOWN


# ---------------------------------------------------------------------------
# What identification does not read (ADR-3)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "blocks",
    [
        (block(),),
        (block(domain="example.org"),),
        (block(result="fail"),),
        (block(selector="other"),),
        (),
    ],
)
def test_other_record_fields_are_ignored(blocks: tuple[DkimResult, ...]) -> None:
    """The same DKIM blocks with other evaluated results, From domain and IP give equal answers."""
    base = Record(dkim=blocks)
    changed = replace(
        base,
        dkim_evaluated="fail",
        spf_evaluated="fail",
        header_from="example.org",
        source_ip="203.0.113.9",
        count=42,
        disposition="reject",
    )
    assert identify_sender(base, config()) == identify_sender(changed, config())
