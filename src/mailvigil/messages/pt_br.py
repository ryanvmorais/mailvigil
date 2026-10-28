"""
The Brazilian Portuguese text of MailVigil.

The same structure as ``en.py``, sentence by sentence, so the two outputs have the same sections in
the same order and the same numbers. ASCII only (``nao``, not ``não``): no console encoding can
break the layout (spec 006 Resolved decision 4). Plain, short sentences. The words "seguro" and
"ataque" are not used: the verdict reads reports, it does not certify a domain. A phrase whose other
words agree with the count is a ``Plural`` of the whole phrase, not of the noun. Every number inside
a sentence is a placeholder filled from the constants the rules use (RNF-05).
"""

from __future__ import annotations

from types import MappingProxyType

from mailvigil.config import ConfigReason
from mailvigil.fetch.errors import FetchReason
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
from mailvigil.reports import Reason
from mailvigil.senders import Outcome
from mailvigil.verdict import Answer, NoteKind, RuleId

# ---------------------------------------------------------------------------
# Common
# ---------------------------------------------------------------------------

# What both commands say. "Origem" is the source of a failing message; "remetente" is a sender that
# the configuration recognized.
_COMMON = CommonMessages(
    day=Plural("{n} dia", "{n} dias"),
    message=Plural("{n} mensagem", "{n} mensagens"),
    failing_message=Plural("{n} mensagem com falha", "{n} mensagens com falha"),
    other_source=Plural("{n} outra origem", "{n} outras origens"),
    no_address="sem endereco",
    kinds=MappingProxyType(
        {
            Outcome.UNKNOWN: "nao reconhecido",
            Outcome.FOREIGN_DOMAIN: "dominio externo",
            Outcome.FAILING_SIGNATURE: "assinatura com falha",
        }
    ),
    selectors_named=Plural("seletor {names}", "seletores {names}"),
    more_failing="... e {sources}: {messages}",
)

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

# O que o ``summary`` diz, no mesmo molde de ``en.py``; o bloco "fora" e comum a mensagem de
# nenhum relatorio.
_SUMMARY = SummaryMessages(
    title="Resumo do MailVigil para {domain}",
    key_config="config",
    key_period="periodo",
    key_reports="relatorios",
    key_policy="politica",
    key_messages="mensagens",
    config_none="nenhum",
    selector=Plural("{n} seletor", "{n} seletores"),
    no_selectors="sem seletores configurados: todo remetente fica nao reconhecido",
    no_selectors_hint="(veja a secao Configuration do README)",
    no_period="sem relatorios",
    # The two forms are alike: "com relatorio" does not agree with the count.
    period=Plural(
        "{first} a {last} ({n} de {days} com relatorio)",
        "{first} a {last} ({n} de {days} com relatorio)",
    ),
    reporter=Plural("{n} provedor", "{n} provedores"),
    reports_line="{reports} de {reporters}",
    policy_none="nenhuma",
    policy_changed="mudou durante o periodo, p anterior: {earlier}",
    messages_line="{total} ({recognized} de remetentes reconhecidos, {share})",
    situations_title="Situacoes",
    col_ok="ok",
    col_fragile="fragil",
    col_failing="falha",
    col_total="total",
    senders_title="Remetentes",
    col_sender="remetente",
    no_messages="nenhuma mensagem contada",
    senders_more="... e {sources}: {messages}, {failing} com falha",
    unrecognized_who="nao reconhecido, {kind}",
    mechanism_none="nenhum",
    source_detail="{messages}  dkim: {dkim}, spf: {spf}",
    source=Plural("{n} origem", "{n} origens"),
    no_failures="Nenhuma mensagem com falha.",
    failing_title="! FALHA: {messages} em {sources}",
    failing_recognized="Remetentes reconhecidos que falham",
    failing_unrecognized="Origens nao reconhecidas que falham",
    left_out_title="Fora destes numeros",
    key_skipped="arquivos ignorados",
    key_duplicates="duplicados",
    key_other_domains="outros dominios",
    reasons=MappingProxyType(
        {
            Reason.UNSUPPORTED_EXTENSION: "tipo de arquivo nao suportado",
            Reason.UNREADABLE: "nao foi possivel ler",
            Reason.FILE_TOO_LARGE: "grande demais",
            Reason.DECOMPRESSED_TOO_LARGE: "grande demais depois de descompactado",
            Reason.NOT_AN_ARCHIVE: "arquivo compactado invalido",
            Reason.NO_XML_MEMBER: "nenhum XML dentro",
            Reason.MULTIPLE_XML_MEMBERS: "mais de um XML dentro",
            Reason.FORBIDDEN_DECLARATION: "XML com declaracao proibida (DOCTYPE ou ENTITY)",
            Reason.MALFORMED_XML: "XML mal formado",
            Reason.NOT_A_REPORT: "nao e um relatorio DMARC",
            Reason.UNSUPPORTED_VERSION: "versao de relatorio nao suportada",
            Reason.INVALID_FIELD: "valor invalido no relatorio",
            Reason.MESSAGE_TOO_LARGE: "mensagem grande demais",
            Reason.MESSAGE_TOO_COMPLEX: "mensagem complexa demais",
            Reason.NO_REPORT_ATTACHMENT: "nenhum relatorio anexado",
            Reason.MALFORMED_MESSAGE: "mensagem malformada",
        }
    ),
    skipped_more="... e mais {n}",
)

# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

# O que o ``verdict`` diz, no mesmo molde de ``en.py``.
_VERDICT = VerdictMessages(
    title="Veredito do MailVigil para {domain}",
    enforcing="ja em p=reject: {words}",
    words=MappingProxyType(
        {
            Answer.READY: "PRONTO para p=reject",
            Answer.TOO_EARLY: "CEDO DEMAIS para dizer",
            Answer.NOT_READY: "NAO PRONTO para p=reject",
        }
    ),
    words_enforcing=MappingProxyType(
        {
            Answer.READY: "NENHUM PROBLEMA VISTO",
            Answer.TOO_EARLY: "CEDO DEMAIS para dizer",
            Answer.NOT_READY: "BLOQUEANDO EMAIL REAL",
        }
    ),
    rule_names=MappingProxyType(
        {
            RuleId.PERIOD: "periodo coberto",
            RuleId.COVERAGE: "dias com relatorio",
            RuleId.VOLUME: "mensagens vistas",
            RuleId.RECOGNIZED_FAILURES: "falhas reconhecidas",
            RuleId.UNRECOGNIZED_FAILURES: "falhas nao reconhecidas",
        }
    ),
    why_label="Motivo:",
    why_ready="todas as regras passam.",
    still_failing="Ainda falham, de origens nao reconhecidas e abaixo do limite:",
    why_too_early="ainda nao ha relatorios suficientes para dizer.",
    no_report_kept="nenhum relatorio foi mantido para este dominio",
    need_days=Plural("falta {n} dia", "faltam {n} dias"),
    need_messages=Plural("falta {n} mensagem", "faltam {n} mensagens"),
    why_recognized="um remetente reconhecido falha no DMARC.",
    why_unrecognized=(
        "as falhas de origens nao reconhecidas sao {share} das mensagens ({measured} de "
        "{whole}); o limite e {limit}."
    ),
    recognized_tail=": {messages} de {where}",
    other_tail="  {kind}: {messages}",
    rules_title="Regras",
    col_rule="regra",
    col_measured="medido",
    col_needed="necessario",
    col_result="resultado",
    measured_coverage="{measured} de {whole} ({share})",
    result_pass="passa",
    result_fail="FALHA",
    result_too_early="falha (cedo demais)",
    notes_title="Notas",
    notes=MappingProxyType(
        {
            NoteKind.FRAGILE: (
                "Trafego fragil: {fragile} de {total} mensagens ({share}) passam por apenas um "
                "entre DKIM e SPF; {spf_only} delas so por SPF, que o encaminhamento quebra."
            ),
            NoteKind.PARTIAL_POLICY: "A politica vale para apenas {pct}% do email (pct={pct}).",
            NoteKind.POLICY_CHANGED: (
                "A politica mudou durante o periodo (p anterior: {earlier}), entao os numeros "
                "misturam politicas."
            ),
            NoteKind.SUBDOMAIN_POLICY: (
                "Os subdominios tem politica propria ({shown}): mudar o p nao a altera."
            ),
            NoteKind.CURRENTLY_QUARANTINE: (
                "A politica atual e p=quarantine; este veredito trata da mudanca para p=reject."
            ),
        }
    ),
    next_label="Proximo:",
    next_each_service="cada servico listado acima",
    next_recognized=(
        "faca {who} assinar com o seu dominio (DKIM) ou acrescente os servidores ao SPF, e "
        "depois colete outro periodo."
    ),
    next_unrecognized=(
        "olhe as origens acima e acrescente os seletores das que forem suas a [senders] na "
        "configuracao."
    ),
    next_data="continue coletando relatorios ate que as regras marcadas '{marker}' passem.",
    skipped_file=Plural("{n} arquivo ignorado", "{n} arquivos ignorados"),
    duplicate=Plural("{n} duplicado", "{n} duplicados"),
    other_domain=Plural("{n} relatorio de outro dominio", "{n} relatorios de outros dominios"),
    left_out="Fora deste veredito: {parts}. O comando mailvigil summary mostra o motivo.",
    caveat=(
        "Isto le apenas os relatorios que voce deu: email que nenhum receptor reporta, e "
        "remetentes que ficaram quietos neste periodo, nao sao cobertos."
    ),
)

# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------

_REFUSALS = RefusalMessages(
    no_domain="informe --domain ou --config (ou coloque um {default} nesta pasta)",
    domain_mismatch="--domain {wanted} nao corresponde ao dominio {domain} de {path}",
    # A phrase per reason; the English detail of ``config.py`` is kept only where a reader cannot
    # act without it (ADR-5): the parser's own message and the suggested key.
    config_reasons=MappingProxyType(
        {
            ConfigReason.UNREADABLE: "nao foi possivel ler o arquivo",
            ConfigReason.FILE_TOO_LARGE: "arquivo grande demais",
            ConfigReason.NOT_UTF8: "o arquivo nao esta em UTF-8",
            ConfigReason.MALFORMED_TOML: "TOML mal formado",
            ConfigReason.UNKNOWN_KEY: "chave desconhecida",
            ConfigReason.MISSING_DOMAIN: "falta o dominio",
            ConfigReason.INVALID_DOMAIN: "dominio invalido",
            ConfigReason.NON_ASCII_DOMAIN: "dominio com letras fora do ASCII (use a forma xn--)",
            ConfigReason.WRONG_TYPE: "tipo de valor errado",
            ConfigReason.INVALID_SELECTOR: "seletor invalido",
            ConfigReason.DUPLICATE_SELECTOR: "seletor repetido",
            ConfigReason.INVALID_SERVICE_NAME: "nome de servico invalido",
            ConfigReason.FORBIDDEN_CHARACTER: "caractere proibido",
        }
    ),
    config_detail=frozenset({ConfigReason.MALFORMED_TOML, ConfigReason.UNKNOWN_KEY}),
    no_reports="Nenhum relatorio DMARC de {domain} foi mantido.",
    no_file_found="Nenhum arquivo de relatorio foi achado. Uma pasta so le nomes como",
    # The pattern is the one the providers use (RFC 7489), so its words stay as they are.
    no_file_hint="provider!domain!begin!end.zip; ou informe o proprio arquivo para le-lo.",
)

# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

# O que o fetch diz, no mesmo molde de en.py.
_FETCH = FetchMessages(
    title="Mensagens de relatorio baixadas da caixa de e-mail.",
    key_matched="Encontradas:",
    key_saved="Salvas:",
    key_already="Ja salvas:",
    key_too_large="Grandes demais:",
    key_skipped="Ignoradas:",
    key_left="Ficaram para depois:",
    key_directory="Salvas em:",
    saved_before_stop=Plural(
        "{n} mensagem foi salva antes de parar.",
        "{n} mensagens foram salvas antes de parar.",
    ),
    reasons=MappingProxyType(
        {
            FetchReason.HOST_UNREACHABLE: "nao foi possivel alcancar o servidor",
            FetchReason.TIMEOUT: "o servidor demorou demais para responder",
            FetchReason.DEADLINE_EXCEEDED: "a execucao demorou demais e foi interrompida",
            FetchReason.CERTIFICATE_INVALID: "o certificado do servidor nao foi aceito",
            FetchReason.TLS_FAILED: "nao foi possivel abrir uma conexao segura",
            FetchReason.LOGIN_FAILED: "o servidor recusou o usuario ou a senha",
            FetchReason.PASSWORD_UNUSABLE: (
                "a senha esta vazia, tem quebra de linha ou tem caracteres fora do ASCII"
            ),
            FetchReason.PASSWORD_FILE: "nao foi possivel ler a senha do arquivo",
            FetchReason.FOLDER_NOT_FOUND: "a pasta nao foi encontrada",
            FetchReason.PROTOCOL_ERROR: "o servidor enviou uma resposta que nao deu para usar",
            FetchReason.TOO_MANY_MATCHES: "mensagens demais; restrinja com --since",
            FetchReason.WRITE_FAILED: "nao foi possivel gravar na pasta",
        }
    ),
)

# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

# O que so o relatorio HTML diz; o resto da pagina le as areas acima.
_HTML = HtmlMessages(
    lang="pt-BR",
    page_title="Relatorio DMARC de {domain}",
    eyebrow="Pronto para p=reject?",
    policy_label="Politica publicada",
    rules_title="As cinco regras por tras da resposta",
    group_data="Ha evidencia suficiente?",
    group_problem="Algo esta errado?",
    meter_legend="A marca escura e o limite de cada regra.",
    at_least="minimo necessario: {value}",
    at_most="maximo permitido: {value}",
    none_allowed="nenhuma permitida",
    meter_label="{name}: {measured}, {needed}",
    of_messages=Plural("de {n} mensagem", "de {n} mensagens"),
    mix_title=Plural("O que aconteceu com {n} mensagem", "O que aconteceu com as {n} mensagens"),
    situation_ok="Passam nos dois",
    situation_dkim="So DKIM",
    situation_spf="So SPF",
    situation_failing="Falham",
    situation_label="{name}: {count} ({share})",
    days_title="Dia a dia",
    column_note=Plural(
        "Cada coluna e um dia, em UTC. Um relatorio conta no dia em que comeca.",
        "Cada coluna e de {n} dias, em UTC. Um relatorio conta no dia em que comeca.",
    ),
    legend_failing_day="Dia com mensagens que falharam",
    legend_no_report="Sem relatorio",
    legend_covered="Coberto por um relatorio que conta em outro dia",
    scale_note=(
        "Coluna mais alta, mais mensagens. A mais alta teve {tallest}. "
        "As mensagens que falharam ficam na base de cada coluna."
    ),
    timeline_label=Plural(
        "Mensagens por dia de {first} a {last}: {n} coluna, {failing} com mensagens que falharam.",
        "Mensagens por dia de {first} a {last}: {n} colunas, {failing} com mensagens que falharam.",
    ),
    show_numbers="Mostrar os numeros",
    numbers_region="Mensagens por dia",
    senders_region="Tabela de remetentes",
    failing_heading="Fontes que falham",
    next_each_service="cada servico listado abaixo",
    next_unrecognized=(
        "olhe as origens abaixo e acrescente os seletores das que forem suas a [senders] na "
        "configuracao."
    ),
    col_day="Dia",
    range_label="{first} a {last}",
    footer=(
        "Gerado offline pelo MailVigil {version}. "
        "Este arquivo nao tem scripts e nao faz requisicoes de rede."
    ),
)

# ---------------------------------------------------------------------------
# The catalog
# ---------------------------------------------------------------------------

PORTUGUESE = Messages(
    common=_COMMON,
    summary=_SUMMARY,
    verdict=_VERDICT,
    refusals=_REFUSALS,
    fetch=_FETCH,
    html=_HTML,
)
