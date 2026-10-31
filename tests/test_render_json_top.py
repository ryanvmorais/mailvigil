"""
Tests of the ``top`` argument of the JSON documents: the lists are cut, the document says so, and
without it nothing changes (spec 006, ADR-8, issue #71).

Isolation: nothing touches the disk and no command runs. The summary is the invented ``ready``
run of ``html_helpers`` with many senders and failing sources added; every address is in
``198.51.100.0/24`` or ``203.0.113.0/24`` (RNF-06).
"""

from __future__ import annotations

import dataclasses
import json

from tests.html_helpers import judged, ready_summary

from mailvigil.render_json import dumps, summary_document, verdict_document
from mailvigil.senders import Outcome
from mailvigil.summary import Counts, FailingSource, SenderRow, Summary

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def busy_summary(senders: int = 7, failing: int = 7) -> Summary:
    """
    Build the ready summary with a number of senders and of failing sources.

    Args:
        senders (int, optional): How many unrecognized senders to list. Default: 7.
        failing (int, optional): How many failing sources, half of them recognized. Default: 7.

    Returns:
        Summary: The summary; its totals are the ones of the ready run.
    """
    rows = tuple(
        SenderRow(Outcome.UNKNOWN, source_ip=f"198.51.100.{number}", counts=Counts(failing=1))
        for number in range(1, senders + 1)
    )
    sources = tuple(
        FailingSource(
            Outcome.KNOWN if number % 2 else Outcome.UNKNOWN,
            f"203.0.113.{number}",
            100 - number,
            service="Example Mail" if number % 2 else "",
        )
        for number in range(1, failing + 1)
    )
    return dataclasses.replace(ready_summary(), senders=rows, failing=sources)


# ---------------------------------------------------------------------------
# Without --top: nothing changes
# ---------------------------------------------------------------------------


def test_without_top_the_documents_have_no_top_key_and_every_entry() -> None:
    summary, verdict = judged(busy_summary())

    document = summary_document(summary, None)
    assert "top" not in document
    assert len(document["senders"]) == 7  # type: ignore[arg-type]  # a document value is typed as object
    assert len(document["failing"]) == 7  # type: ignore[arg-type]  # same
    assert "top" not in verdict_document(verdict)


def test_top_none_is_the_same_document_as_leaving_it_out() -> None:
    summary, verdict = judged(busy_summary())

    assert dumps(summary_document(summary, None, None)) == dumps(summary_document(summary, None))
    assert dumps(verdict_document(verdict, None)) == dumps(verdict_document(verdict))


# ---------------------------------------------------------------------------
# With --top: the worst N, and the document says what it left out
# ---------------------------------------------------------------------------


def test_the_summary_keeps_the_first_n_of_each_list_and_counts_the_rest() -> None:
    summary, _verdict = judged(busy_summary(senders=7, failing=5))

    document = summary_document(summary, None, 3)

    assert [row["source_ip"] for row in document["senders"]] == [  # type: ignore[attr-defined]  # a document value is typed as object
        "198.51.100.1",
        "198.51.100.2",
        "198.51.100.3",
    ]
    assert len(document["failing"]) == 3  # type: ignore[arg-type]  # same
    assert document["top"] == {"limit": 3, "left_out": {"senders": 4, "failing": 2}}


def test_the_top_key_is_the_last_one_of_the_document() -> None:
    summary, verdict = judged(busy_summary())

    assert list(summary_document(summary, None, 2))[-1] == "top"
    assert list(verdict_document(verdict, 2))[-1] == "top"


def test_the_verdict_keeps_the_first_n_of_each_kind_and_counts_the_rest() -> None:
    _summary, verdict = judged(busy_summary(failing=9))
    kept = len(verdict.recognized_failing)
    assert kept > 2 and len(verdict.unrecognized_failing) > 2

    document = verdict_document(verdict, 2)

    assert len(document["recognized_failing"]) == 2  # type: ignore[arg-type]  # same
    assert len(document["unrecognized_failing"]) == 2  # type: ignore[arg-type]  # same
    assert document["top"] == {
        "limit": 2,
        "left_out": {
            "recognized_failing": kept - 2,
            "unrecognized_failing": len(verdict.unrecognized_failing) - 2,
        },
    }


def test_a_list_shorter_than_n_is_whole_and_counts_zero_left_out() -> None:
    summary, verdict = judged(busy_summary(senders=2, failing=2))

    assert summary_document(summary, None, 50)["top"] == {
        "limit": 50,
        "left_out": {"senders": 0, "failing": 0},
    }
    assert verdict_document(verdict, 50)["top"]["left_out"] == {  # type: ignore[index]  # a document value is typed as object
        "recognized_failing": 0,
        "unrecognized_failing": 0,
    }


def test_trimming_changes_no_number_outside_the_lists() -> None:
    """Only the lists shrink: totals, rules, answer, notes and left-out stay as they were."""
    summary, verdict = judged(busy_summary())

    whole = summary_document(summary, None)
    cut = summary_document(summary, None, 1)
    for key in whole:
        if key not in {"senders", "failing"}:
            assert cut[key] == whole[key]

    whole_verdict = verdict_document(verdict)
    cut_verdict = verdict_document(verdict, 1)
    for key in ("answer", "deciding", "rules", "notes", "left_out"):
        assert cut_verdict[key] == whole_verdict[key]


def test_a_trimmed_document_is_still_one_ascii_json_document() -> None:
    summary, _verdict = judged(busy_summary())

    text = dumps(summary_document(summary, None, 2))

    assert text.isascii()
    assert json.loads(text)["top"]["limit"] == 2
