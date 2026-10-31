"""
Tests of the ``domains`` envelope of the JSON documents: the order of the keys, the worst answer,
and the promise that each element is the document a run of that one domain prints (spec 010, RF-07,
ADR-7).

Isolation: nothing touches the disk and no command runs. The three domains are the invented
``example.com`` (ready), ``example.net`` (too early: no reports) and ``example.org`` (not ready: a
recognized sender fails), built from the ``html_helpers`` run and ``make_summary`` (RNF-06).
"""

from __future__ import annotations

import dataclasses

import pytest
from tests.html_helpers import ready_summary
from tests.test_render_json import make_summary
from tests.test_render_json_top import busy_summary

from mailvigil.render_json import (
    dumps,
    summaries_document,
    summary_document,
    verdict_document,
    verdicts_document,
)
from mailvigil.summary import Summary
from mailvigil.verdict import Answer, Verdict, judge

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def three_summaries() -> list[Summary]:
    """
    Build a ready, a too early and a not ready summary, each of its own domain.

    Returns:
        list[Summary]: ``example.com``, ``example.net`` and ``example.org``, in that order.
    """
    ready = ready_summary()
    early = dataclasses.replace(make_summary(days=0), domain="example.net")
    not_ready = dataclasses.replace(busy_summary(), domain="example.org")
    return [ready, early, not_ready]


def judged_all(summaries: list[Summary]) -> list[Verdict]:
    """
    Judge each summary, as the command does.

    Args:
        summaries (list[Summary]): The summaries.

    Returns:
        list[Verdict]: One verdict per summary.
    """
    return [judge(summary) for summary in summaries]


# ---------------------------------------------------------------------------
# summaries_document
# ---------------------------------------------------------------------------


def test_the_summaries_envelope_has_three_keys_in_order_and_no_domain() -> None:
    """The envelope is a version, a command and the list; it is about no one domain."""
    document = summaries_document(three_summaries(), "mailvigil.toml")

    assert list(document) == ["schema_version", "command", "domains"]
    assert document["schema_version"] == 1
    assert document["command"] == "summary"


def test_each_summary_element_is_the_document_of_that_domain_byte_for_byte() -> None:
    """An element is what a run of that one domain prints, so a script reads it the same way."""
    summaries = three_summaries()

    document = summaries_document(summaries, "mailvigil.toml")

    elements = document["domains"]
    assert isinstance(elements, list)
    assert [dumps(element) for element in elements] == [
        dumps(summary_document(summary, "mailvigil.toml")) for summary in summaries
    ]


def test_the_summary_elements_come_in_the_order_of_the_run() -> None:
    """The order is the caller's (the file's, or the order of ``--domain``), never sorted."""
    summaries = three_summaries()[::-1]

    document = summaries_document(summaries, None)

    elements = document["domains"]
    assert isinstance(elements, list)
    assert [element["domain"] for element in elements] == [
        "example.org",
        "example.net",
        "example.com",
    ]


def test_top_trims_inside_each_summary_element_and_each_says_so() -> None:
    """Each element carries its own ``top`` key; the envelope has none (ADR-7)."""
    summaries = [busy_summary(), dataclasses.replace(busy_summary(3, 3), domain="example.net")]

    document = summaries_document(summaries, None, top=2)

    elements = document["domains"]
    assert isinstance(elements, list)
    assert [element["top"] for element in elements] == [
        {"limit": 2, "left_out": {"senders": 5, "failing": 5}},
        {"limit": 2, "left_out": {"senders": 1, "failing": 1}},
    ]
    assert "top" not in document
    assert [dumps(element) for element in elements] == [
        dumps(summary_document(summary, None, 2)) for summary in summaries
    ]


def test_the_summaries_envelope_is_ascii() -> None:
    """The envelope is written by ``dumps`` like any document."""
    assert dumps(summaries_document(three_summaries(), None)).isascii()


# ---------------------------------------------------------------------------
# verdicts_document
# ---------------------------------------------------------------------------


def test_the_verdicts_envelope_carries_the_worst_answer_before_the_list() -> None:
    """The answer is there so a script reads the meaning of the exit code from the document."""
    verdicts = judged_all(three_summaries())
    assert [verdict.answer for verdict in verdicts] == [
        Answer.READY,
        Answer.TOO_EARLY,
        Answer.NOT_READY,
    ]

    document = verdicts_document(verdicts)

    assert list(document) == ["schema_version", "command", "answer", "domains"]
    assert document["schema_version"] == 1
    assert document["command"] == "verdict"
    assert document["answer"] == "not_ready"


@pytest.mark.parametrize(
    ("indexes", "answer"),
    [
        ((0, 0), "ready"),
        ((0, 1), "too_early"),
        ((1, 2), "not_ready"),
        ((0, 2, 1), "not_ready"),
    ],
)
def test_the_envelope_answer_is_the_worst_of_the_elements(
    indexes: tuple[int, ...], answer: str
) -> None:
    """Not ready beats too early, and too early beats ready (005 ADR-6, 010 ADR-6)."""
    verdicts = judged_all(three_summaries())

    document = verdicts_document([verdicts[index] for index in indexes])

    assert document["answer"] == answer


def test_each_verdict_element_is_the_document_of_that_domain_byte_for_byte() -> None:
    """An element is what a run of that one domain prints."""
    verdicts = judged_all(three_summaries())

    document = verdicts_document(verdicts)

    elements = document["domains"]
    assert isinstance(elements, list)
    assert [dumps(element) for element in elements] == [
        dumps(verdict_document(verdict)) for verdict in verdicts
    ]


def test_top_trims_inside_each_verdict_element_and_each_says_so() -> None:
    """The answer and the rules are not touched by the trim; each element has its own key."""
    verdicts = judged_all([busy_summary(), dataclasses.replace(busy_summary(), domain="b.example")])

    document = verdicts_document(verdicts, top=1)

    elements = document["domains"]
    assert isinstance(elements, list)
    assert [dumps(element) for element in elements] == [
        dumps(verdict_document(verdict, 1)) for verdict in verdicts
    ]
    assert all("top" in element for element in elements)
    assert "top" not in document


def test_the_verdicts_of_no_domain_are_a_mistake_of_the_caller() -> None:
    """There is no answer to carry for an empty run; ``worst_answer`` says so."""
    with pytest.raises(ValueError):
        verdicts_document([])
