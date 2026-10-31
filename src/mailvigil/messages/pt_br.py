"""
The Brazilian Portuguese text of MailVigil.

The same structure as ``en.py``, sentence by sentence, so the two outputs have the same sections in
the same order and the same numbers. Written with accents, in NFC, with the letters of Portuguese
only (``á à â ã é ê í ó ô õ ú ü ç`` and their capitals; no typographic quote, dash or ellipsis).
``fold.py`` derives the ASCII catalog from this one, one character for one, for a stream that cannot
be trusted with accents (spec 006 ADR-9, which supersedes Resolved decision 4). Plain, short
sentences. The words "seguro" and "ataque" are not used: the verdict reads reports, it does not
certify a domain. A phrase whose other words agree with the count is a ``Plural`` of the whole
phrase, not of the noun. Every number inside a sentence is a placeholder filled from the constants
the rules use (RNF-05).
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
    no_address="sem endereço",
    kinds=MappingProxyType(
        {
            Outcome.UNKNOWN: "não reconhecido",
            Outcome.FOREIGN_DOMAIN: "domínio externo",
            Outcome.FAILING_SIGNATURE: "assinatura com falha",
        }
    ),
    selectors_named=Plural("seletor {names}", "seletores {names}"),
    spf_domains_named=Plural("domínio SPF {names}", "domínios SPF {names}"),
    more_failing="... e {sources}: {messages}",
)

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

# O que o ``summary`` diz, no mesmo molde de ``en.py``; o bloco "fora" e comum a mensagem de
# nenhum relatório.
_SUMMARY = SummaryMessages(
    title="Resumo do MailVigil para {domain}",
    key_config="config",
    key_period="período",
    key_reports="relatórios",
    key_policy="política",
    key_messages="mensagens",
    config_none="nenhum",
    selector=Plural("{n} seletor", "{n} seletores"),
    spf_domain=Plural("{n} domínio SPF", "{n} domínios SPF"),
    ip_range=Plural("{n} faixa de IP", "{n} faixas de IP"),
    no_selectors="nenhum remetente mapeado: todo remetente fica não reconhecido",
    no_selectors_hint="(veja a seção Configuration do README)",
    no_period="sem relatórios",
    # The two forms are alike: "com relatório" does not agree with the count.
    period=Plural(
        "{first} a {last} ({n} de {days} com relatório)",
        "{first} a {last} ({n} de {days} com relatório)",
    ),
    reporter=Plural("{n} provedor", "{n} provedores"),
    reports_line="{reports} de {reporters}",
    policy_none="nenhuma",
    policy_changed="mudou durante o período, p anterior: {earlier}",
    messages_line="{total} ({recognized} de remetentes reconhecidos, {share})",
    situations_title="Situações",
    col_ok="ok",
    col_fragile="frágil",
    col_failing="falha",
    col_total="total",
    senders_title="Remetentes",
    col_sender="remetente",
    no_messages="nenhuma mensagem contada",
    senders_more="... e {sources}: {messages}, {failing} com falha",
    unrecognized_who="não reconhecido, {kind}",
    mechanism_none="nenhum",
    source_detail="{messages}  dkim: {dkim}, spf: {spf}",
    source=Plural("{n} origem", "{n} origens"),
    no_failures="Nenhuma mensagem com falha.",
    failing_title="! FALHA: {messages} em {sources}",
    failing_recognized="Remetentes reconhecidos que falham",
    failing_unrecognized="Origens não reconhecidas que falham",
    left_out_title="Fora destes números",
    key_skipped="arquivos ignorados",
    key_duplicates="duplicados",
    key_other_domains="outros domínios",
    key_passed_over="ignorados pelo nome",
    reasons=MappingProxyType(
        {
            Reason.UNSUPPORTED_EXTENSION: "tipo de arquivo não suportado",
            Reason.UNREADABLE: "não foi possível ler",
            Reason.FILE_TOO_LARGE: "grande demais",
            Reason.DECOMPRESSED_TOO_LARGE: "grande demais depois de descompactado",
            Reason.NOT_AN_ARCHIVE: "arquivo compactado inválido",
            Reason.NO_XML_MEMBER: "nenhum XML dentro",
            Reason.MULTIPLE_XML_MEMBERS: "mais de um XML dentro",
            Reason.FORBIDDEN_DECLARATION: "XML com declaração proibida (DOCTYPE ou ENTITY)",
            Reason.MALFORMED_XML: "XML mal formado",
            Reason.NOT_A_REPORT: "não é um relatório DMARC",
            Reason.UNSUPPORTED_VERSION: "versão de relatório não suportada",
            Reason.INVALID_FIELD: "valor inválido no relatório",
            Reason.MESSAGE_TOO_LARGE: "mensagem grande demais",
            Reason.MESSAGE_TOO_COMPLEX: "mensagem complexa demais",
            Reason.NO_REPORT_ATTACHMENT: "nenhum relatório anexado",
            Reason.MALFORMED_MESSAGE: "mensagem malformada",
            Reason.XML_TOO_COMPLEX: "XML complexo demais",
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
    enforcing="já em p=reject: {words}",
    words=MappingProxyType(
        {
            Answer.READY: "PRONTO para p=reject",
            Answer.TOO_EARLY: "CEDO DEMAIS para dizer",
            Answer.NOT_READY: "NÃO PRONTO para p=reject",
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
            RuleId.PERIOD: "período coberto",
            RuleId.COVERAGE: "dias com relatório",
            RuleId.VOLUME: "mensagens vistas",
            RuleId.RECOGNIZED_FAILURES: "falhas reconhecidas",
            RuleId.UNRECOGNIZED_FAILURES: "falhas não reconhecidas",
        }
    ),
    why_label="Motivo:",
    why_ready="todas as regras passam.",
    still_failing="Ainda falham, de origens não reconhecidas e abaixo do limite:",
    why_too_early="ainda não há relatórios suficientes para dizer.",
    no_report_kept="nenhum relatório foi mantido para este domínio",
    need_days=Plural("falta {n} dia", "faltam {n} dias"),
    need_messages=Plural("falta {n} mensagem", "faltam {n} mensagens"),
    why_recognized="um remetente reconhecido falha no DMARC.",
    why_unrecognized=(
        "as falhas de origens não reconhecidas são {share} das mensagens ({measured} de "
        "{whole}); o limite é {limit}."
    ),
    recognized_tail=": {messages} de {where}",
    other_tail="  {kind}: {messages}",
    rules_title="Regras",
    col_rule="regra",
    col_measured="medido",
    col_needed="necessário",
    col_result="resultado",
    measured_coverage="{measured} de {whole} ({share})",
    result_pass="passa",
    result_fail="FALHA",
    result_too_early="falha (cedo demais)",
    notes_title="Notas",
    notes=MappingProxyType(
        {
            NoteKind.FRAGILE: (
                "Tráfego frágil: {fragile} de {total} mensagens ({share}) passam por apenas um "
                "entre DKIM e SPF; {spf_only} delas só por SPF, que o encaminhamento quebra."
            ),
            NoteKind.PARTIAL_POLICY: "A política vale para apenas {pct}% do email (pct={pct}).",
            NoteKind.POLICY_CHANGED: (
                "A política mudou durante o período (p anterior: {earlier}), então os números "
                "misturam políticas."
            ),
            NoteKind.SUBDOMAIN_POLICY: (
                "Os subdomínios têm política própria ({shown}): mudar o p não a altera."
            ),
            NoteKind.CURRENTLY_QUARANTINE: (
                "A política atual é p=quarantine; este veredito trata da mudança para p=reject."
            ),
            NoteKind.SILENT_REPORTER: (
                "{name} enviou {share} das mensagens mas nada nos últimos {days} dias; os dias "
                "que faltaram podem parecer cobertos por outros relatórios."
            ),
            NoteKind.STALE: (
                "O último relatório terminou há {days} dias; os números podem não descrever o "
                "e-mail que você envia hoje."
            ),
        }
    ),
    next_label="Próximo:",
    next_each_service="cada serviço listado acima",
    next_recognized=(
        "faça {who} assinar com o seu domínio (DKIM) ou acrescente os servidores ao SPF, e "
        "depois colete outro período."
    ),
    next_unrecognized=(
        "olhe as origens acima e acrescente as que forem suas a [senders] (seletor DKIM), "
        "[spf] (domínio SPF) ou [ips] (faixa de IP) na configuração."
    ),
    next_data="continue coletando relatórios até que as regras marcadas '{marker}' passem.",
    skipped_file=Plural("{n} arquivo ignorado", "{n} arquivos ignorados"),
    duplicate=Plural("{n} duplicado", "{n} duplicados"),
    other_domain=Plural("{n} relatório de outro domínio", "{n} relatórios de outros domínios"),
    passed_over=Plural("{n} arquivo ignorado pelo nome", "{n} arquivos ignorados pelo nome"),
    left_out="Fora deste veredito: {parts}. O comando mailvigil summary mostra o motivo.",
    caveat=(
        "Isto lê apenas os relatórios que você deu: email que nenhum receptor reporta, e "
        "remetentes que ficaram quietos neste período, não são cobertos."
    ),
    tally=Plural("{n} domínio: {parts}", "{n} domínios: {parts}"),
    tally_ready=Plural("{n} pronto", "{n} prontos"),
    tally_early=Plural("{n} cedo demais", "{n} cedo demais"),
    tally_not_ready=Plural("{n} não pronto", "{n} não prontos"),
)

# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------

_REFUSALS = RefusalMessages(
    no_domain="informe --domain ou --config (ou coloque um {default} nesta pasta)",
    domain_mismatch="--domain {wanted} não corresponde ao domínio {domain} de {path}",
    # A phrase per reason; the English detail of ``config.py`` is kept only where a reader cannot
    # act without it (ADR-5): the parser's own message and the suggested key.
    config_reasons=MappingProxyType(
        {
            ConfigReason.UNREADABLE: "não foi possível ler o arquivo",
            ConfigReason.FILE_TOO_LARGE: "arquivo grande demais",
            ConfigReason.NOT_UTF8: "o arquivo não está em UTF-8",
            ConfigReason.MALFORMED_TOML: "TOML mal formado",
            ConfigReason.UNKNOWN_KEY: "chave desconhecida",
            ConfigReason.MISSING_DOMAIN: "falta o domínio",
            ConfigReason.INVALID_DOMAIN: "domínio inválido",
            ConfigReason.NON_ASCII_DOMAIN: (
                "não foi possível converter o domínio como escrito (use a forma xn--)"
            ),
            ConfigReason.WRONG_TYPE: "tipo de valor errado",
            ConfigReason.INVALID_SELECTOR: "seletor inválido",
            ConfigReason.DUPLICATE_SELECTOR: "seletor repetido",
            ConfigReason.INVALID_SERVICE_NAME: "nome de serviço inválido",
            ConfigReason.FORBIDDEN_CHARACTER: "caractere proibido",
            ConfigReason.INVALID_FETCH_VALUE: "valor inválido em [fetch]",
            ConfigReason.PASSWORD_NOT_ALLOWED: (
                "a senha nunca fica no arquivo: use o prompt ou --password-file"
            ),
            ConfigReason.INVALID_SPF_DOMAIN: "domínio SPF inválido em [spf]",
            ConfigReason.FOREIGN_SPF_DOMAIN: "domínio SPF fora do seu domínio",
            ConfigReason.INVALID_IP_RANGE: (
                "faixa de IP inválida em [ips]: use um bloco CIDR sem bits além do prefixo, "
                "não mais largo que /16 (IPv4) ou /32 (IPv6)"
            ),
            ConfigReason.DUPLICATE_KEY: "chave repetida",
            ConfigReason.DOMAIN_CONFLICT: (
                "domains junto de domain, senders, spf ou ips: use uma forma só"
            ),
            ConfigReason.NO_DOMAINS: "domains está vazio",
            ConfigReason.TOO_MANY_DOMAINS: "domínios demais",
            ConfigReason.DUPLICATE_DOMAIN: "domínio repetido",
        }
    ),
    config_detail=frozenset({ConfigReason.MALFORMED_TOML, ConfigReason.UNKNOWN_KEY}),
    no_reports="Nenhum relatório DMARC de {domain} foi mantido.",
    no_file_found="Nenhum arquivo de relatório foi achado. Uma pasta só lê nomes como",
    # The pattern is the one the providers use (RFC 7489), so its words stay as they are.
    no_file_hint="provider!domain!begin!end.zip; use --recursive ou informe o próprio arquivo.",
    output_failed="não foi possível gravar {path}: {reason}",
    domain_not_listed="--domain {wanted} não está entre os domínios de {path}",
    no_reports_many="Nenhum relatório DMARC dos {count} domínios foi mantido.",
    html_needs_folder=(
        "--html de {count} domínios grava uma página por domínio: informe --output PASTA"
    ),
    output_not_folder="--output {path} não é uma pasta existente",
)

# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

# Muitos planos gratuitos de e-mail não têm IMAP, e um provedor que o desligou responde como uma
# senha errada ou como um servidor fora do ar; as duas frases que parecem isso dizem o que fazer.
_IMAP_HINT = "; seu provedor precisa liberar o IMAP, senão baixe os relatórios à mão e use summary"

# O que o fetch diz, no mesmo molde de en.py.
_FETCH = FetchMessages(
    title="Mensagens de relatório baixadas da caixa de e-mail.",
    key_matched="Encontradas:",
    key_saved="Salvas:",
    key_already="Já salvas:",
    key_too_large="Grandes demais:",
    key_skipped="Ignoradas:",
    key_left="Ficaram para depois:",
    key_directory="Salvas em:",
    saved_before_stop=Plural(
        "{n} mensagem foi salva antes de parar.",
        "{n} mensagens foram salvas antes de parar.",
    ),
    password_file_exposed="aviso: {path} pode ser lido por outros usuários; rode chmod 600 nele",
    reasons=MappingProxyType(
        {
            FetchReason.HOST_UNREACHABLE: f"não foi possível alcançar o servidor{_IMAP_HINT}",
            FetchReason.TIMEOUT: "o servidor demorou demais para responder",
            FetchReason.DEADLINE_EXCEEDED: "a execução demorou demais e foi interrompida",
            FetchReason.CERTIFICATE_INVALID: "o certificado do servidor não foi aceito",
            FetchReason.TLS_FAILED: "não foi possível abrir uma conexão segura",
            FetchReason.LOGIN_FAILED: f"o servidor recusou o usuário ou a senha{_IMAP_HINT}",
            FetchReason.PASSWORD_UNUSABLE: (
                "a senha está vazia, tem quebra de linha ou caractere de controle, ou o login tem "
                "caracteres fora do ASCII que o servidor não aceita"
            ),
            FetchReason.PASSWORD_FILE: "não foi possível ler a senha do arquivo",
            FetchReason.CAFILE_UNUSABLE: (
                "não foi possível ler uma autoridade certificadora do arquivo de --cafile"
            ),
            FetchReason.FOLDER_NOT_FOUND: "a pasta não foi encontrada",
            FetchReason.PROTOCOL_ERROR: "o servidor enviou uma resposta que não deu para usar",
            FetchReason.TOO_MANY_MATCHES: "mensagens demais; restrinja com --since",
            FetchReason.WRITE_FAILED: "não foi possível gravar na pasta",
        }
    ),
)

# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

# O que so o relatório HTML diz; o resto da página le as areas acima.
_HTML = HtmlMessages(
    lang="pt-BR",
    page_title="Relatório DMARC de {domain}",
    eyebrow="Pronto para p=reject?",
    policy_label="Política publicada",
    rules_title="As cinco regras por trás da resposta",
    group_data="Há evidência suficiente?",
    group_problem="Algo está errado?",
    meter_legend="A marca escura é o limite de cada regra.",
    at_least="mínimo necessário: {value}",
    at_most="máximo permitido: {value}",
    none_allowed="nenhuma permitida",
    meter_label="{name}: {measured}, {needed}",
    of_messages=Plural("de {n} mensagem", "de {n} mensagens"),
    mix_title=Plural("O que aconteceu com {n} mensagem", "O que aconteceu com as {n} mensagens"),
    situation_ok="Passam nos dois",
    situation_dkim="Só DKIM",
    situation_spf="Só SPF",
    situation_failing="Falham",
    situation_label="{name}: {count} ({share})",
    days_title="Dia a dia",
    column_note=Plural(
        "Cada coluna é um dia, em UTC. Um relatório conta no dia em que começa.",
        "Cada coluna é de {n} dias, em UTC. Um relatório conta no dia em que começa.",
    ),
    legend_failing_day="Dia com mensagens que falharam",
    legend_no_report="Sem relatório",
    legend_covered="Coberto por um relatório que conta em outro dia",
    scale_note=(
        "Coluna mais alta, mais mensagens. A mais alta teve {tallest}. "
        "As mensagens que falharam ficam na base de cada coluna."
    ),
    timeline_label=Plural(
        "Mensagens por dia de {first} a {last}: {n} coluna, {failing} com mensagens que falharam.",
        "Mensagens por dia de {first} a {last}: {n} colunas, {failing} com mensagens que falharam.",
    ),
    show_numbers="Mostrar os números",
    numbers_region="Mensagens por dia",
    senders_region="Tabela de remetentes",
    other_sender=Plural("{n} outro remetente", "{n} outros remetentes"),
    senders_more=(
        "Fora desta lista: {senders} ({messages}). "
        "mailvigil summary --json lista todos os remetentes."
    ),
    failing_heading="Fontes que falham",
    next_each_service="cada serviço listado abaixo",
    next_unrecognized=(
        "olhe as origens abaixo e acrescente as que forem suas a [senders] (seletor DKIM), "
        "[spf] (domínio SPF) ou [ips] (faixa de IP) na configuração."
    ),
    col_day="Dia",
    range_label="{first} a {last}",
    footer=(
        "Gerado offline pelo MailVigil {version}. "
        "Este arquivo não tem scripts e não faz requisições de rede."
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
