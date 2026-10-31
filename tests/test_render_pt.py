"""
Tests of the Portuguese text of both commands, rendered through the catalog (spec 006, RF-06,
RF-07).

Isolation: nothing touches the disk and no command runs. The summaries and the verdicts are built
with the builders of ``test_render.py`` and ``test_render_verdict.py``, the same inputs the English
tests use, so the two languages are compared on equal ground: the same numbers, the same order of
sections, every line within 80 columns and ASCII. The text here is the folded catalog
(``PORTUGUESE_ASCII``), the one a pipe on Windows gets; ``test_render_accents.py`` proves the
accented catalog renders the same lines. Domains, services and addresses are invented
(``example.com``, ``example.net``; ``192.0.2.0/24``, ``198.51.100.0/24``, ``2001:db8::/32``;
RNF-06).
"""

from __future__ import annotations

import dataclasses
import re
from typing import Any

import pytest
from tests.test_render import (
    extreme_summary,
    failing_source,
    make_summary,
    section,
    skipped,
)
from tests.test_render import known as summary_known
from tests.test_render import other as summary_other
from tests.test_render_verdict import known, make_verdict, other, verdicts_of

from mailvigil.messages import ENGLISH, PORTUGUESE_ASCII
from mailvigil.render import no_reports_message, render_summary
from mailvigil.render_verdict import render_tally, render_verdict
from mailvigil.reports import IngestionResult, PolicyPublished, Reason
from mailvigil.senders import Outcome
from mailvigil.summary import FailingSource, Summary
from mailvigil.verdict import MIN_MESSAGES, Answer, LeftOut, Note, NoteKind, RuleId, Verdict

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LONG_NAME = "N" * 100
_V6 = "2001:db8:85a3:8d3:1319:8a2e:370:7344"


def summary_pt(summary: Summary, source: str | None = "mailvigil.toml") -> str:
    """Render a summary in Portuguese."""
    return render_summary(summary, source, PORTUGUESE_ASCII)


def verdict_pt(verdict: Verdict) -> str:
    """Render a verdict in Portuguese."""
    return render_verdict(verdict, PORTUGUESE_ASCII)


def cells(line: str) -> list[str]:
    """Split a line of a table or of key and value into its cells: two spaces or more end one."""
    return re.split(r"\s{2,}", line.strip())


def numbers(text: str) -> list[str]:
    """List the digit runs of a text, sorted, so two languages can be compared on their figures."""
    return sorted(re.findall(r"\d+", text))


def flat(text: str) -> str:
    """Join the wrapped lines of a text, so a sentence can be searched whatever its line breaks."""
    return " ".join(text.split())


def notes_of(verdict: Verdict) -> list[str]:
    """Read the notes of a Portuguese verdict back, one sentence each."""
    text = verdict_pt(verdict)
    if "\nNotas\n" not in text:
        return []
    block = text.split("\nNotas\n")[1].split("\n\n")[0]
    return [flat(note) for note in re.split(r"(?m)^  - ", block)[1:]]


def next_step(verdict: Verdict) -> str:
    """Read the next step of a Portuguese verdict back; empty when there is none."""
    for paragraph in verdict_pt(verdict).split("\n\n"):
        if paragraph.startswith("Proximo:"):
            return flat(paragraph)
    return ""


# ---------------------------------------------------------------------------
# The summary: header, situations, senders
# ---------------------------------------------------------------------------


def test_the_summary_sections_come_in_the_english_order() -> None:
    summary = make_summary(failing=(failing_source(),))
    text = summary_pt(summary)
    titles = [block.split("\n")[0] for block in text.split("\n\n")]
    assert titles[0] == "Resumo do MailVigil para example.com"
    assert titles[1:3] == ["Situacoes", "Remetentes"]
    assert titles[3].startswith("! FALHA")
    assert titles[4] == "Fora destes numeros"
    assert len(titles) == len(render_summary(summary, "mailvigil.toml").split("\n\n")) == 5


def test_the_header_shows_config_period_reports_policy_and_messages() -> None:
    header = section(summary_pt(make_summary()), "Resumo")
    assert header[0] == "Resumo do MailVigil para example.com"
    assert [cells(line) for line in header[1:]] == [
        ["config", "mailvigil.toml (2 seletores)"],
        ["periodo", "2026-10-01 a 2026-10-28 (27 de 28 dias com relatorio)"],
        ["relatorios", "54 de 4 provedores"],
        ["politica", "p=none, pct=100"],
        ["mensagens", "12480 (12300 de remetentes reconhecidos, 98.6%)"],
    ]


def test_the_singular_forms() -> None:
    period = dataclasses.replace(make_summary().period, days_spanned=1, days_with_reports=1)
    summary = make_summary(period=period, selectors_configured=1, reports=1, reporters=1)
    header = section(summary_pt(summary), "Resumo")
    assert cells(header[1])[1] == "mailvigil.toml (1 seletor)"
    assert cells(header[2])[1].endswith("(1 de 1 dia com relatorio)")
    assert cells(header[3])[1] == "1 de 1 provedor"


def test_the_policy_shows_sp_and_np_and_the_earlier_values() -> None:
    policy = PolicyPublished(domain="example.com", p="reject", sp="quarantine", np="reject", pct=50)
    header = section(summary_pt(make_summary(policy=policy, earlier_p=("none",))), "Resumo")
    assert cells(header[4])[1] == "p=reject, sp=quarantine, np=reject, pct=50"
    assert header[5].strip() == "mudou durante o periodo, p anterior: none"


def test_an_empty_selector_map_adds_the_note_and_points_at_the_readme() -> None:
    header = section(summary_pt(make_summary(selectors_configured=0)), "Resumo")
    assert header[2].strip() == "nenhum remetente mapeado: todo remetente fica nao reconhecido"
    assert header[3].strip() == "(veja a secao Configuration do README)"


def test_a_summary_without_reports_still_renders() -> None:
    header = section(summary_pt(make_summary(period=None, policy=None), None), "Resumo")
    assert [cells(line)[1] for line in header[1:4]] == [
        "nenhum",
        "sem relatorios",
        "54 de 4 provedores",
    ]
    assert cells(header[4])[1] == "nenhuma"


def test_the_situations_name_ok_fragile_and_failing() -> None:
    lines = section(summary_pt(make_summary()), "Situacoes")
    assert [cells(line)[0] for line in lines] == ["Situacoes", "ok", "fragil", "falha"]
    assert cells(lines[3]) == ["falha", "40", "0.3%"]


def test_the_senders_table_labels_each_kind_and_marks_failing_rows() -> None:
    senders = (
        summary_known("Example Mailer", ok=500, failing=2),
        summary_other("192.0.2.10", Outcome.UNKNOWN, ok=3),
        summary_other("192.0.2.11", Outcome.FOREIGN_DOMAIN, failing=4),
        summary_other("192.0.2.12", Outcome.FAILING_SIGNATURE, ok=1),
        summary_other("", Outcome.UNKNOWN, ok=1),
    )
    lines = section(summary_pt(make_summary(senders=senders)), "Remetentes")
    assert cells(lines[1]) == ["remetente", "ok", "fragil", "falha", "total"]
    assert cells(lines[2])[:2] == ["! Example Mailer", "500"]
    assert cells(lines[3])[0] == "192.0.2.10 (nao reconhecido)"
    assert cells(lines[4])[0] == "! 192.0.2.11 (dominio externo)"
    assert cells(lines[5])[0] == "192.0.2.12 (assinatura com falha)"
    assert cells(lines[6])[0] == "sem endereco (nao reconhecido)"


def test_a_summary_with_no_rows_says_so() -> None:
    assert section(summary_pt(make_summary()), "Remetentes") == [
        "Remetentes",
        "  nenhuma mensagem contada",
    ]


def test_twelve_other_rows_print_ten_and_a_remainder() -> None:
    rows = tuple(summary_other(f"198.51.100.{i}", ok=1, failing=1) for i in range(1, 13))
    lines = section(summary_pt(make_summary(senders=rows)), "Remetentes")
    assert lines[-1] == "  ... e 2 outras origens: 4 mensagens, 2 com falha"
    one = section(summary_pt(make_summary(senders=rows[:11])), "Remetentes")
    assert one[-1] == "  ... e 1 outra origem: 2 mensagens, 1 com falha"


# ---------------------------------------------------------------------------
# The summary: failures and what was left out
# ---------------------------------------------------------------------------


def test_no_failing_message_says_so_in_one_line() -> None:
    assert "Nenhuma mensagem com falha." in summary_pt(make_summary()).split("\n\n")


def test_the_failures_title_counts_messages_and_sources_in_the_singular() -> None:
    one = make_summary(failing=(failing_source(messages=1),))
    assert "! FALHA: 1 mensagem em 1 origem" in summary_pt(one)
    many = make_summary(failing=(failing_source(messages=12), failing_source("192.0.2.11", 3)))
    assert "! FALHA: 15 mensagens em 2 origens" in summary_pt(many)


def test_recognized_sources_come_before_unrecognized_ones_and_take_two_lines_each() -> None:
    sources = (
        failing_source("192.0.2.10", 12, Outcome.UNKNOWN),
        failing_source(
            "192.0.2.20", 7, Outcome.KNOWN, "Example Mailer", override_reasons=("forwarded",)
        ),
    )
    lines = summary_pt(make_summary(failing=sources)).split("\n\n")[3].split("\n")
    assert lines[1:] == [
        "  Remetentes reconhecidos que falham",
        "  ! Example Mailer",
        "      192.0.2.20  7 mensagens  dkim: fail, spf: fail; forwarded",
        "  Origens nao reconhecidas que falham",
        "  ! 192.0.2.10",
        "      12 mensagens  dkim: fail, spf: fail",
    ]


def test_a_failing_signature_names_its_selectors_in_the_singular_and_the_plural() -> None:
    one = failing_source(outcome=Outcome.FAILING_SIGNATURE, selectors=("s1",))
    two = failing_source(outcome=Outcome.FOREIGN_DOMAIN, selectors=("s1", "s2"))
    text = summary_pt(make_summary(failing=(one, two)))
    assert "  ! nao reconhecido, assinatura com falha (seletor s1)" in text
    assert "  ! nao reconhecido, dominio externo (seletores s1, s2)" in text


def test_a_mechanism_with_no_result_reads_none_and_no_address_reads_so() -> None:
    source = failing_source("", 5, dkim=(), spf=())
    text = summary_pt(make_summary(failing=(source,)))
    assert "  ! sem endereco" in text
    assert "      5 mensagens  dkim: nenhum, spf: nenhum" in text


def test_twelve_sources_in_a_group_print_ten_and_a_remainder() -> None:
    sources = tuple(failing_source(f"198.51.100.{i}", 12) for i in range(1, 13))
    lines = summary_pt(make_summary(failing=sources)).split("\n")
    assert "  ... e 2 outras origens: 24 mensagens com falha" in lines
    assert sum(1 for line in lines if line.startswith("  ! 198.51.100.")) == 10


def test_left_out_prints_zero_counts() -> None:
    lines = section(summary_pt(make_summary()), "Fora")
    assert lines[0] == "Fora destes numeros"
    assert [cells(line) for line in lines[1:]] == [
        ["arquivos ignorados", "0"],
        ["duplicados", "0"],
        ["outros dominios", "0"],
    ]


def test_skipped_files_show_the_counts_per_reason_and_each_file() -> None:
    summary = make_summary(
        skipped=(skipped("a.xml", Reason.FILE_TOO_LARGE), skipped("b.txt")),
        skipped_by_reason=((Reason.FILE_TOO_LARGE, 1), (Reason.NOT_A_REPORT, 1)),
        duplicates=3,
        other_domain=2,
    )
    lines = section(summary_pt(summary), "Fora")
    assert cells(lines[1]) == [
        "arquivos ignorados",
        "2 (1 grande demais, 1 nao e um relatorio DMARC)",
    ]
    assert lines[2:4] == ["    a.xml: grande demais", "    b.txt: nao e um relatorio DMARC"]
    assert [cells(line) for line in lines[4:]] == [["duplicados", "3"], ["outros dominios", "2"]]


def test_twelve_skipped_files_print_ten_and_a_remainder() -> None:
    files = tuple(skipped(f"f{i:02d}.xml") for i in range(12))
    summary = make_summary(skipped=files, skipped_by_reason=((Reason.NOT_A_REPORT, 12),))
    lines = section(summary_pt(summary), "Fora")
    assert sum(1 for line in lines if line.startswith("    f")) == 10
    assert "    ... e mais 2" in lines


@pytest.mark.parametrize("reason", list(Reason))
def test_every_reason_prints_as_a_portuguese_phrase_never_as_its_key(reason: Reason) -> None:
    summary = make_summary(skipped=(skipped("x.xml", reason),), skipped_by_reason=((reason, 1),))
    text = summary_pt(summary)
    phrase = PORTUGUESE_ASCII.summary.reasons[reason]
    assert f"    x.xml: {phrase}" in text.split("\n")
    assert f": {reason.value}" not in text
    assert phrase != ENGLISH.summary.reasons[reason]


# ---------------------------------------------------------------------------
# The no-reports message
# ---------------------------------------------------------------------------


def test_no_reports_message_names_the_domain_and_what_was_left_out() -> None:
    result = IngestionResult(
        skipped=(skipped("b.txt"), skipped("a.xml", Reason.FILE_TOO_LARGE)),
        duplicates=2,
        other_domain=3,
    )
    lines = no_reports_message(result, ["example.com"], PORTUGUESE_ASCII).split("\n")
    assert lines[0] == "Nenhum relatorio DMARC de example.com foi mantido."
    assert lines[2:4] == ["    a.xml: grande demais", "    b.txt: nao e um relatorio DMARC"]
    assert [cells(line) for line in (lines[1], lines[4], lines[5])] == [
        ["arquivos ignorados", "2 (1 grande demais, 1 nao e um relatorio DMARC)"],
        ["duplicados", "2"],
        ["outros dominios", "3"],
    ]


def test_no_reports_message_for_nothing_found_says_where_to_look() -> None:
    lines = no_reports_message(IngestionResult(), ["example.com"], PORTUGUESE_ASCII).split("\n")
    assert lines[0] == "Nenhum relatorio DMARC de example.com foi mantido."
    assert lines[1].startswith("Nenhum arquivo de relatorio foi")
    assert "provider!domain!begin!end.zip" in lines[2]
    assert [cells(line)[0] for line in lines[3:]] == [
        "arquivos ignorados",
        "duplicados",
        "outros dominios",
    ]
    assert max(len(line) for line in lines) <= 80


def test_no_reports_message_is_short_enough_and_ends_without_a_newline() -> None:
    result = IngestionResult(skipped=(skipped("n" * 100 + ".xml"),))
    message = no_reports_message(result, ["d" * 80 + ".example.com"], PORTUGUESE_ASCII)
    assert not message.endswith("\n")
    assert max(len(line) for line in message.split("\n")) <= 80
    assert message.isascii()


# ---------------------------------------------------------------------------
# The verdict: title and reason
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "phrase"),
    [
        ({}, "PRONTO para p=reject"),
        ({"sources": (known(3),)}, "NAO PRONTO para p=reject"),
        ({"days": 10}, "CEDO DEMAIS para dizer"),
        ({"days": 0}, "CEDO DEMAIS para dizer"),
        ({"p": "quarantine"}, "PRONTO para p=reject"),
        ({"p": "reject"}, "ja em p=reject: NENHUM PROBLEMA VISTO"),
        ({"p": "reject", "sources": (known(3),)}, "ja em p=reject: BLOQUEANDO EMAIL REAL"),
        ({"p": "reject", "days": 10}, "ja em p=reject: CEDO DEMAIS para dizer"),
    ],
)
def test_the_title_names_the_answer(kwargs: dict[str, Any], phrase: str) -> None:
    first = verdict_pt(make_verdict(**kwargs)).split("\n")[0]
    assert first == f"Veredito do MailVigil para example.com: {phrase}"


def test_every_answer_has_its_own_word_in_both_forms() -> None:
    for words in (PORTUGUESE_ASCII.verdict.words, PORTUGUESE_ASCII.verdict.words_enforcing):
        assert set(words) == set(Answer)
    assert len(set(PORTUGUESE_ASCII.verdict.words.values())) == 3


def test_a_title_too_wide_for_one_line_goes_on_two() -> None:
    verdict = make_verdict(p="reject", domain="a" * 60 + ".example.com", sources=(known(3),))
    lines = verdict_pt(verdict).split("\n")
    assert lines[0].startswith("Veredito do MailVigil para aaaa")
    assert lines[1] == "Ja em p=reject: BLOQUEANDO EMAIL REAL"


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"days": 10},
        {"days": 0},
        {"sources": (known(3),)},
        {"sources": (other(40),)},
        {"p": "reject"},
        {"p": "reject", "sources": (known(3),)},
        {"p": "quarantine", "dkim_only": 10, "spf_only": 5, "pct": 50, "sp": "reject"},
    ],
)
def test_the_verdict_never_promises_safety_or_calls_a_source_an_attack(
    kwargs: dict[str, Any],
) -> None:
    text = verdict_pt(make_verdict(**kwargs)).lower()
    assert "seguro" not in text
    assert "ataque" not in text


def test_ready_says_that_every_rule_passes() -> None:
    lines = verdict_pt(make_verdict()).split("\n")
    assert "Motivo: todas as regras passam." in lines
    assert not any(line.startswith("Ainda falham") for line in lines)


def test_ready_still_lists_the_unrecognized_sources_under_the_limit() -> None:
    sources = tuple(other(1, number=i + 1) for i in range(7))
    lines = verdict_pt(make_verdict(sources=sources)).split("\n")
    assert "Ainda falham, de origens nao reconhecidas e abaixo do limite:" in lines
    assert "  198.51.100.5  nao reconhecido: 1 mensagem com falha" in lines
    assert "  ... e 2 outras origens: 2 mensagens com falha" in lines


def test_rule_four_names_each_recognized_source() -> None:
    verdict = make_verdict(sources=(known(3, override_reasons=("forwarded",)), known(1, ip="")))
    lines = verdict_pt(verdict).split("\n")
    assert "Motivo: um remetente reconhecido falha no DMARC." in lines
    assert "  Example Mailer: 3 mensagens com falha de 192.0.2.10 (forwarded)" in lines
    assert "  Example Mailer: 1 mensagem com falha de sem endereco" in lines


def test_rule_five_prints_the_share_the_limit_and_the_sources() -> None:
    verdict = make_verdict(
        sources=(other(40, selectors=("s1", "s2"), outcome=Outcome.FAILING_SIGNATURE),)
    )
    text = verdict_pt(verdict)
    assert (
        "Motivo: as falhas de origens nao reconhecidas sao 2.0% das mensagens (40 de 2040); o "
        "limite e 0.5%."
    ) in flat(text)
    assert "  198.51.100.1  assinatura com falha (seletores s1, s2): 40 mensagens com falha" in text


def test_too_early_says_how_much_each_failed_data_rule_lacks() -> None:
    lines = verdict_pt(make_verdict(days=10)).split("\n")
    assert lines[2:4] == [
        "Motivo: ainda nao ha relatorios suficientes para dizer.",
        "  periodo coberto: faltam 18 dias",
    ]
    assert "  periodo coberto: falta 1 dia" in verdict_pt(make_verdict(days=27)).split("\n")


def test_too_early_asks_for_the_messages_still_missing() -> None:
    lines = verdict_pt(make_verdict(ok=MIN_MESSAGES - 1)).split("\n")
    assert "  mensagens vistas: falta 1 mensagem" in lines
    assert f"  mensagens vistas: faltam {MIN_MESSAGES} mensagens" in verdict_pt(make_verdict(ok=0))


def test_too_early_with_no_reports_says_that_none_was_kept() -> None:
    lines = verdict_pt(make_verdict(days=0)).split("\n")
    assert "  nenhum relatorio foi mantido para este dominio" in lines


# ---------------------------------------------------------------------------
# The verdict: the table, the notes, the next step, the left-out line
# ---------------------------------------------------------------------------


def test_the_table_has_the_five_rules_with_what_was_measured_and_needed() -> None:
    verdict = make_verdict(days=28, with_reports=27, ok=12468, sources=(known(12),))
    lines = verdict_pt(verdict).split("\n")
    start = lines.index("Regras") + 1
    assert [cells(line) for line in lines[start : start + 6]] == [
        ["regra", "medido", "necessario", "resultado"],
        ["1", "periodo coberto", "28 dias", ">= 28", "passa"],
        ["2", "dias com relatorio", "27 de 28 (96.4%)", ">= 80%", "passa"],
        ["3", "mensagens vistas", "12480", ">= 100", "passa"],
        ["4", "falhas reconhecidas", "12", "<= 0", "FALHA"],
        ["5", "falhas nao reconhecidas", "0 (0%)", "<= 0.5%", "passa"],
    ]


def test_a_failed_data_rule_reads_fail_too_early() -> None:
    assert "falha (cedo demais)" in verdict_pt(make_verdict(days=10))


def test_every_rule_has_a_name_in_the_table() -> None:
    text = verdict_pt(make_verdict())
    for rule in RuleId:
        assert PORTUGUESE_ASCII.verdict.rule_names[rule] in text


def test_no_notes_prints_no_section() -> None:
    assert notes_of(make_verdict()) == []
    assert "Notas" not in verdict_pt(make_verdict())


def test_each_note_says_its_one_thing() -> None:
    assert notes_of(make_verdict(ok=1900, dkim_only=60, spf_only=40)) == [
        "Trafego fragil: 100 de 2000 mensagens (5.0%) passam por apenas um entre DKIM e SPF; "
        "40 delas so por SPF, que o encaminhamento quebra."
    ]
    assert notes_of(make_verdict(pct=50)) == ["A politica vale para apenas 50% do email (pct=50)."]
    assert notes_of(make_verdict(earlier_p=("none", "quarantine"))) == [
        "A politica mudou durante o periodo (p anterior: none, quarantine), entao os numeros "
        "misturam politicas."
    ]
    assert notes_of(make_verdict(sp="reject", np="quarantine")) == [
        "Os subdominios tem politica propria (sp=reject, np=quarantine): mudar o p nao a altera."
    ]
    assert notes_of(make_verdict(p="quarantine")) == [
        "A politica atual e p=quarantine; este veredito trata da mudanca para p=reject."
    ]


def test_several_notes_come_in_the_order_of_their_kinds() -> None:
    verdict = make_verdict(p="quarantine", dkim_only=10, pct=50, earlier_p=("none",))
    sentences = notes_of(verdict)
    assert len(sentences) == len(verdict.notes) == 4
    assert sentences[0].startswith("Trafego fragil")
    assert sentences[-1].startswith("A politica atual e p=quarantine")


def test_every_kind_of_note_has_a_portuguese_text() -> None:
    base = make_verdict()
    for kind in NoteKind:
        note = Note(kind, numbers=(1, 2, 3), texts=("a", "b"))
        text = verdict_pt(dataclasses.replace(base, notes=(note,)))
        assert len(re.findall(r"(?m)^  - ", text)) == 1


def test_the_next_step_for_a_recognized_sender_names_the_service() -> None:
    assert next_step(make_verdict(sources=(known(3),))) == (
        "Proximo: faca Example Mailer assinar com o seu dominio (DKIM) ou acrescente os "
        "servidores ao SPF, e depois colete outro periodo."
    )


def test_the_next_step_for_several_recognized_services_does_not_pick_one() -> None:
    two = (known(3), known(2, service="Example Billing", ip="192.0.2.20"))
    assert "faca cada servico listado acima assinar" in next_step(make_verdict(sources=two))
    same = (known(3), known(2, ip="192.0.2.20"))
    assert "faca Example Mailer assinar" in next_step(make_verdict(sources=same))


def test_the_next_step_for_unrecognized_sources_points_at_the_configuration() -> None:
    assert next_step(make_verdict(sources=(other(40),))) == (
        "Proximo: olhe as origens acima e acrescente as que forem suas a [senders] (seletor DKIM), "
        "[spf] (dominio SPF) ou [ips] (faixa de IP) na configuracao."
    )


def test_the_next_step_for_a_data_rule_is_to_collect_more() -> None:
    assert next_step(make_verdict(days=10)) == (
        "Proximo: continue coletando relatorios ate que as regras marcadas 'falha (cedo demais)' "
        "passem."
    )


def test_a_ready_verdict_has_no_next_step() -> None:
    assert next_step(make_verdict()) == ""
    assert "Proximo:" not in verdict_pt(make_verdict())


@pytest.mark.parametrize(
    ("left_out", "expected"),
    [
        (LeftOut(skipped=1), "1 arquivo ignorado"),
        (LeftOut(skipped=2), "2 arquivos ignorados"),
        (LeftOut(duplicates=1), "1 duplicado"),
        (LeftOut(other_domain=1), "1 relatorio de outro dominio"),
        (LeftOut(other_domain=3), "3 relatorios de outros dominios"),
        (LeftOut(passed_over=1), "1 arquivo ignorado pelo nome"),
        (LeftOut(passed_over=4), "4 arquivos ignorados pelo nome"),
        (
            LeftOut(skipped=2, duplicates=1, other_domain=3),
            "2 arquivos ignorados, 1 duplicado, 3 relatorios de outros dominios",
        ),
    ],
)
def test_the_left_out_line_counts_what_the_summary_did_not(
    left_out: LeftOut, expected: str
) -> None:
    verdict = dataclasses.replace(make_verdict(), left_out=left_out)
    paragraphs = [flat(p) for p in verdict_pt(verdict).split("\n\n") if p.startswith("Fora")]
    assert paragraphs == [
        f"Fora deste veredito: {expected}. O comando mailvigil summary mostra o motivo."
    ]


def test_nothing_left_out_prints_no_line() -> None:
    assert "Fora deste veredito" not in verdict_pt(make_verdict())


@pytest.mark.parametrize(
    "kwargs",
    [{}, {"days": 10}, {"days": 0}, {"sources": (known(3),)}, {"sources": (other(40),)}],
)
def test_the_caveat_closes_every_verdict(kwargs: dict[str, Any]) -> None:
    last = verdict_pt(make_verdict(**kwargs)).split("\n\n")[-1]
    assert flat(last) == (
        "Isto le apenas os relatorios que voce deu: email que nenhum receptor reporta, e "
        "remetentes que ficaram quietos neste periodo, nao sao cobertos."
    )


def test_the_verdict_sections_come_in_order_with_one_blank_line_between() -> None:
    verdict = make_verdict(sources=(known(3),), pct=50)
    text = verdict_pt(verdict)
    starts = [paragraph.split("\n")[0].split(" ")[0] for paragraph in text.split("\n\n")]
    assert starts == ["Veredito", "Motivo:", "Regras", "Notas", "Proximo:", "Isto"]
    assert not text.endswith("\n")
    assert "\n\n\n" not in text


# ---------------------------------------------------------------------------
# Both languages say the same things (RF-06)
# ---------------------------------------------------------------------------

_VERDICT_CASES: list[dict[str, Any]] = [
    {},
    {"days": 10},
    {"days": 0},
    {"sources": (known(3),)},
    {"sources": (other(40),)},
    {"p": "reject", "sources": (known(3),)},
    {"p": "quarantine", "dkim_only": 10, "spf_only": 5, "pct": 50, "sp": "reject"},
    {"earlier_p": ("none", "quarantine")},
]


@pytest.mark.parametrize("kwargs", _VERDICT_CASES)
def test_the_verdict_has_the_same_numbers_and_sections_in_both_languages(
    kwargs: dict[str, Any],
) -> None:
    verdict = make_verdict(**kwargs)
    english = render_verdict(verdict)
    portuguese = verdict_pt(verdict)
    assert numbers(portuguese) == numbers(english)
    assert len(portuguese.split("\n\n")) == len(english.split("\n\n"))


@pytest.mark.parametrize(
    "summary",
    [
        make_summary(),
        make_summary(
            failing=(failing_source(), failing_source("192.0.2.11", 3, Outcome.KNOWN, "X"))
        ),
        make_summary(senders=(summary_known("Example Mailer", ok=5, failing=1),)),
        make_summary(period=None, policy=None),
        make_summary(skipped=(skipped("a.xml"),), skipped_by_reason=((Reason.NOT_A_REPORT, 1),)),
    ],
)
def test_the_summary_has_the_same_numbers_and_sections_in_both_languages(summary: Summary) -> None:
    english = render_summary(summary, "mailvigil.toml")
    portuguese = summary_pt(summary)
    assert numbers(portuguese) == numbers(english)
    assert len(portuguese.split("\n\n")) == len(english.split("\n\n"))


def test_a_value_that_comes_from_the_data_is_printed_unchanged() -> None:
    senders = (summary_known("Cafe Mailer", ok=1),)
    assert "Cafe Mailer" in summary_pt(make_summary(senders=senders))
    verdict = make_verdict(domain="example.net", sources=(known(3, service="Example Billing"),))
    assert verdict_pt(verdict).startswith("Veredito do MailVigil para example.net: ")
    assert "Example Billing" in verdict_pt(verdict)


# ---------------------------------------------------------------------------
# The layout (004 RF-09): 80 columns, ASCII, no trailing space
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sources": (known(12, service=_LONG_NAME),)},
        {"sources": (known(12, service=_LONG_NAME, ip=_V6, override_reasons=("forwarded",)),)},
        {"sources": (known(12, ip=_V6, override_reasons=("forwarded", "mailing_list", "other")),)},
        {"sources": (other(40, selectors=("s" * 60,), outcome=Outcome.FAILING_SIGNATURE),)},
        {"sources": (FailingSource(Outcome.UNKNOWN, _V6, 40, override_reasons=("forwarded",)),)},
        {"ok": 10**12, "sources": (known(10**12, service=_LONG_NAME, ip=_V6),)},
        {"ok": 10**12, "sources": (FailingSource(Outcome.UNKNOWN, _V6, 10**12),)},
        {"ok": 10**30, "sources": (FailingSource(Outcome.UNKNOWN, _V6, 10**29),)},
        {"days": 0, "domain": "a" * 200 + ".example.com"},
        {"p": "reject", "domain": "a" * 60 + ".example.com", "sources": (known(3),)},
        {"earlier_p": ("n" * 90,), "sp": "s" * 90, "np": "n" * 90, "dkim_only": 5, "pct": 50},
        {"days": 10, "p": "quarantine"},
        {"sources": tuple(other(1, number=i + 1) for i in range(30)), "days": 10},
    ],
)
def test_no_verdict_line_is_wider_than_eighty_columns(kwargs: dict[str, Any]) -> None:
    text = verdict_pt(make_verdict(**kwargs))
    assert max(len(line) for line in text.split("\n")) <= 80
    assert text.isascii()


def test_no_summary_line_is_over_eighty_columns_with_extreme_values() -> None:
    text = summary_pt(extreme_summary(), "p" * 100 + ".toml")
    assert max(len(line) for line in text.split("\n")) <= 80
    assert text.isascii()
    assert not text.endswith("\n")
    assert all(line == line.rstrip() for line in text.split("\n"))


def test_the_summary_header_fits_with_no_selectors_and_a_very_long_domain() -> None:
    summary = make_summary(domain="d" * 200 + ".example.com", selectors_configured=0)
    text = summary_pt(summary, None)
    assert max(len(line) for line in text.split("\n")) <= 80


def test_the_same_input_rendered_twice_is_the_same_text() -> None:
    summary = extreme_summary()
    assert summary_pt(summary) == summary_pt(summary)
    verdict = make_verdict(sources=(known(3), other(40)), pct=50)
    assert verdict_pt(verdict) == verdict_pt(verdict)


@pytest.mark.parametrize(
    ("counts", "line"),
    [
        ((1, 0, 0), "1 dominio: 1 pronto"),
        ((3, 0, 0), "3 dominios: 3 prontos"),
        ((0, 2, 0), "2 dominios: 2 cedo demais"),
        ((0, 0, 1), "1 dominio: 1 nao pronto"),
        ((2, 1, 2), "5 dominios: 2 prontos, 1 cedo demais, 2 nao prontos"),
    ],
)
def test_the_tally_is_in_portuguese(counts: tuple[int, int, int], line: str) -> None:
    assert render_tally(verdicts_of(*counts), PORTUGUESE_ASCII) == line


def test_the_no_reports_message_counts_several_domains_in_portuguese() -> None:
    result = IngestionResult(duplicates=2, other_domain=3)
    domains = ["example.com", "example.net", "example.org"]
    first, *rest = no_reports_message(result, domains, PORTUGUESE_ASCII).split("\n")
    assert first == "Nenhum relatorio DMARC dos 3 dominios foi mantido."
    assert [cells(line)[0] for line in rest] == [
        "arquivos ignorados",
        "duplicados",
        "outros dominios",
    ]
