import json
import logging
import re
from time import perf_counter
from typing import Any

import httpx
from openai import OpenAI
from sqlalchemy.orm import Session

from exceptions import JiraClientError, JiraIssueNotFoundError, LLMError
from llm.prompts import build_chat_prompt, build_jira_analysis_prompt
from jira.client import JiraClient, normalize_issue
from utils.retry import external_retry
from utils.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class LLMService:
    def __init__(self) -> None:
        self._llm_provider = settings.llm_provider.strip().lower() or "auto"
        self._openai_client = OpenAI(api_key=settings.openai_api_key_value()) if settings.openai_api_key_value() else None
        self._gemini_api_key = settings.gemini_api_key_value().strip()
        self._gemini_model = settings.gemini_model.strip() or "gemini-2.5-flash"

    def generate_jira_analysis_comment(
        self,
        resumo: str,
        descricao: str,
        similares: list[dict],
        produto: str = "",
    ) -> tuple[str, bool]:
        top = similares[:3]
        analysis = self._fallback_jira_analysis(resumo, descricao, top)
        fallback_used = True

        if self._llm_available():
            generated = self._generate_jira_analysis_llm(resumo, descricao, top, produto)
            if generated:
                analysis = generated
                fallback_used = False

        return _render_jira_comment(analysis, top), fallback_used

    def generate_chat_response(self, pergunta: str, similares: list[dict], produto: str = "") -> tuple[str, list[str], bool]:
        top = similares[:3]
        tickets = [s["chave_jira"] for s in top if s.get("chave_jira")]

        chat_payload = self._fallback_chat_payload(pergunta, top)
        fallback_used = True
        if self._llm_available():
            generated = self._generate_chat_payload_llm(pergunta, top, produto)
            if generated:
                chat_payload = generated
                fallback_used = False

        return _render_chat_response(chat_payload, tickets), tickets, fallback_used

    def chat_query(
        self,
        db: Session,
        pergunta: str,
        embedding_service,
        retrieval_service,
        allowed_statuses: list[str],
        produto: str = "",
    ) -> tuple[str, list[str], bool]:
        vector = embedding_service.embed(pergunta)
        similares = retrieval_service.find_similar(
            db,
            vector,
            top_k=settings.top_k_similar,
            allowed_statuses=allowed_statuses,
            query_text=pergunta,
            query_produto=produto,
        )
        return self.generate_chat_response(pergunta, similares, produto)

    def generate_triage_comment(
        self,
        db: Session,
        chave_jira: str,
        jira_client: JiraClient,
        embedding_service,
        retrieval_service,
        allowed_statuses: list[str],
        post: bool = False,
    ) -> tuple[str, list[str], bool]:
        if not jira_client.is_configured():
            raise JiraClientError("Jira client nao configurado")

        raw = jira_client.get_issue(chave_jira.strip())
        if raw is None:
            raise JiraIssueNotFoundError(f"Ticket {chave_jira} nao encontrado no Jira")

        issue = normalize_issue(raw)
        text = "\n\n".join(filter(None, [issue["resumo"], issue["descricao"], issue["comentarios"]]))
        query_vector = embedding_service.embed(text)
        similares = retrieval_service.find_similar(
            db,
            query_vector,
            top_k=settings.top_k_similar,
            exclude_ticket_key=chave_jira,
            allowed_statuses=allowed_statuses,
            query_text=f"{issue['resumo']} {issue['descricao']}",
            query_produto=issue.get("produto", ""),
        )
        comentario, fallback = self.generate_jira_analysis_comment(
            resumo=issue["resumo"],
            descricao=issue["descricao"],
            similares=similares,
            produto=issue.get("produto", ""),
        )

        if post:
            jira_client.post_comment_direct(chave_jira, comentario)

        tickets_ref = [s["chave_jira"] for s in similares[:3] if s.get("chave_jira")]
        return comentario, tickets_ref, fallback

    def _generate_jira_analysis_llm(
        self,
        resumo: str,
        descricao: str,
        similares: list[dict],
        produto: str = "",
    ) -> dict[str, Any] | None:
        role_ctx = settings.n1_role_description.strip()
        prompt = build_jira_analysis_prompt(role_ctx, produto)
        payload = {
            "produto": produto,
            "resumo": resumo,
            "descricao": descricao,
            "similares": similares,
        }
        raw = self._request_llm_json(prompt, payload)
        if not raw:
            return None
        try:
            data = _loads_json_loose(raw)
            return _normalize_jira_analysis(data)
        except Exception:
            logger.exception("Falha ao gerar analise Jira via LLM; aplicando fallback")
            return None

    def _generate_chat_payload_llm(self, pergunta: str, similares: list[dict], produto: str = "") -> dict[str, str] | None:
        role_ctx = settings.n1_role_description.strip()
        prompt = build_chat_prompt(role_ctx, produto)
        payload = {
            "pergunta": pergunta,
            "produto": produto,
            "tickets_contexto": similares,
        }
        raw = self._request_llm_json(prompt, payload)
        if not raw:
            return None
        try:
            data = _loads_json_loose(raw)
            return {
                "sintese": str(data.get("sintese", "")).strip(),
                "padrao_observado": str(data.get("padrao_observado", "")).strip(),
                "solucao_recorrente": str(data.get("solucao_recorrente", "")).strip(),
            }
        except Exception:
            logger.exception("Falha ao gerar resposta de chat via LLM; aplicando fallback")
            return None

    def _llm_available(self) -> bool:
        if self._llm_provider == "gemini":
            return bool(self._gemini_api_key)
        if self._llm_provider == "openai":
            return self._openai_client is not None
        if self._llm_provider == "auto":
            return bool(self._gemini_api_key) or self._openai_client is not None
        return bool(self._gemini_api_key)

    def _request_llm_json(self, prompt: str, payload: dict[str, Any]) -> str | None:
        providers: list[str]
        if self._llm_provider == "auto":
            providers = ["gemini", "openai"]
        elif self._llm_provider in {"gemini", "openai"}:
            providers = [self._llm_provider]
        else:
            providers = ["gemini"]

        for provider in providers:
            if provider == "gemini" and self._gemini_api_key:
                text = self._request_gemini(prompt, payload)
                if text:
                    return text
            if provider == "openai" and self._openai_client is not None:
                text = self._request_openai(prompt, payload)
                if text:
                    return text
        return None

    def _request_openai(self, prompt: str, payload: dict[str, Any]) -> str | None:
        started_at = perf_counter()
        try:
            response = self._request_openai_raw(prompt, payload)
            usage = getattr(response, "usage", None)
            logger.info(
                "llm_call_completed",
                extra={
                    "provider": "openai",
                    "duration_ms": round((perf_counter() - started_at) * 1000, 2),
                    "tokens_total": getattr(usage, "total_tokens", None),
                },
            )
            return response.output_text.strip()
        except Exception:
            logger.exception("Falha na chamada OpenAI")
            return None

    @external_retry()
    def _request_openai_raw(self, prompt: str, payload: dict[str, Any]):
        try:
            return self._openai_client.responses.create(
                model=settings.llm_model,
                input=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                temperature=0.2,
            )
        except Exception as exc:
            raise LLMError("Falha na chamada OpenAI") from exc

    def _request_gemini(self, prompt: str, payload: dict[str, Any]) -> str | None:
        started_at = perf_counter()
        model = self._gemini_model
        if model.startswith("models/"):
            model = model.split("models/", 1)[1]
        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        body = {
            "system_instruction": {
                "parts": [
                    {"text": prompt},
                ]
            },
            "contents": [
                {
                    "parts": [
                        {"text": json.dumps(payload, ensure_ascii=False)},
                    ]
                }
            ],
            "generationConfig": {"temperature": 0.2},
        }
        try:
            response = self._request_gemini_raw(endpoint, body)
            data = response.json()
            candidates = data.get("candidates", [])
            if not candidates:
                return None
            parts = candidates[0].get("content", {}).get("parts", [])
            text_parts = [str(part.get("text", "")).strip() for part in parts if part.get("text")]
            usage = data.get("usageMetadata", {})
            logger.info(
                "llm_call_completed",
                extra={
                    "provider": "gemini",
                    "duration_ms": round((perf_counter() - started_at) * 1000, 2),
                    "tokens_total": usage.get("totalTokenCount"),
                },
            )
            return "\n".join(text_parts).strip() or None
        except Exception:
            logger.exception("Falha na chamada Gemini")
            return None

    @external_retry()
    def _request_gemini_raw(self, endpoint: str, body: dict[str, Any]) -> httpx.Response:
        try:
            response = httpx.post(
                endpoint,
                params={"key": self._gemini_api_key},
                json=body,
                timeout=settings.external_timeout_seconds,
            )
            response.raise_for_status()
            return response
        except Exception as exc:
            raise LLMError("Falha na chamada Gemini") from exc

    def _fallback_jira_analysis(self, resumo: str, descricao: str, similares: list[dict]) -> dict[str, Any]:
        confianca_val = similares[0].get("confianca", 0.3) if similares else 0.3
        confianca = _confidence_label(confianca_val)

        if confianca_val >= 0.75 and similares:
            indicacao = "Resolver no N1"
        elif confianca_val >= 0.55:
            indicacao = "Avaliar com especialista"
        else:
            indicacao = "Encaminhar N2"

        cenario = _extract_cenario(resumo, descricao)
        causa = _extract_causa(similares)
        proposta = _build_solution_proposal(similares)
        passos = _build_passos_n1(resumo, descricao, similares)
        criterio = _build_criterio_escalonamento(similares)

        return {
            "cenario": cenario,
            "causa_provavel": causa,
            "proposta_solucao": proposta,
            "passos_n1": passos,
            "criterio_escalonamento": criterio,
            "indicacao": indicacao,
            "confianca": confianca,
        }

    def _fallback_chat_payload(self, pergunta: str, similares: list[dict]) -> dict[str, str]:
        solutions = [
            str(s["solucao"]).strip()
            for s in similares
            if s.get("solucao") and "sem solucao" not in str(s["solucao"]).lower()
        ]
        solution = solutions[0] if solutions else "Sem solucao documentada na base para este tema."

        if similares:
            temas = list({s.get("subtema") or s.get("tema") or "" for s in similares if s.get("tema")})
            temas_str = ", ".join(t for t in temas if t)
            pattern = (
                f"Encontrados {len(similares)} chamados relacionados"
                + (f" nos temas: {temas_str}" if temas_str else ".")
                + ". Padrão recorrente identificado na base."
            )
        else:
            pattern = "Base historica insuficiente para identificar padrao."

        return {
            "sintese": f"Consulta: {pergunta}",
            "padrao_observado": pattern,
            "solucao_recorrente": solution,
        }


def _jira_format_hint() -> str:
    return (
        "Triagem de conhecimento\\n"
        "Cenario identificado:\\n"
        "[descricao objetiva do problema]\\n"
        "Chamados relacionados:\\n"
        "- [ticket] - [descricao curta]\\n"
        "- [ticket] - [descricao curta]\\n"
        "Proposta de solucao:\\n"
        "[descricao clara da solucao]\\n"
        "Passos sugeridos para o N1:\\n"
        "1. ...\\n"
        "2. ...\\n"
        "3. ...\\n"
        "Indicacao: [Resolver no N1 / Avaliar / Encaminhar N2]\\n"
        "Confianca da recomendacao: [Baixa | Media | Alta]"
    )


def _chat_format_hint() -> str:
    return (
        "Sintese:\\n"
        "[descricao do problema encontrado]\\n"
        "Padrao observado:\\n"
        "[explicacao do comportamento recorrente]\\n"
        "Solucao mais recorrente:\\n"
        "[descricao da solucao]\\n"
        "Chamados de referencia:\\n"
        "- [ticket]\\n"
        "- [ticket]"
    )


def _confidence_label(value: float) -> str:
    if value >= 0.8:
        return "Alta"
    if value >= 0.55:
        return "Media"
    return "Baixa"


def _strip_json_fences(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        chunks = text.split("```")
        if len(chunks) >= 2:
            text = chunks[1]
            if text.startswith("json"):
                text = text[4:]
    return text.strip()


def _loads_json_loose(raw: str) -> dict[str, Any]:
    text = _strip_json_fences(raw)
    try:
        return json.loads(text)
    except Exception:
        pass

    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last != -1 and first < last:
        return json.loads(text[first : last + 1])

    raise ValueError("Resposta do LLM nao contem JSON valido")


def _normalize_jira_analysis(data: dict[str, Any]) -> dict[str, Any]:
    passos = data.get("passos_n1")
    if not isinstance(passos, list):
        passos = []
    passos_texto = [str(item).strip() for item in passos if str(item).strip()]
    while len(passos_texto) < 3:
        passos_texto.append(f"Passo sugerido {len(passos_texto) + 1}.")

    confianca = str(data.get("confianca", "Media")).strip().capitalize()
    if confianca not in {"Baixa", "Media", "Alta"}:
        confianca = "Media"

    indicacao_raw = str(data.get("indicacao", "Resolver no N1")).strip()
    indicacao_map = {
        "resolver": "Resolver no N1",
        "escalar": "Escalar para N2",
        "encaminhar": "Escalar para N2",
        "avaliar": "Escalar para N2",
        "n2": "Escalar para N2",
        "n1": "Resolver no N1",
    }
    indicacao = indicacao_raw
    for key, value in indicacao_map.items():
        if key in indicacao_raw.lower():
            indicacao = value
            break

    chamados_relacionados = data.get("chamados_relacionados")
    if not isinstance(chamados_relacionados, list):
        chamados_relacionados = []

    criterios = data.get("criterios_escalonamento_n2")
    if not isinstance(criterios, list):
        criterios = []
    criterios_texto = [str(item).strip() for item in criterios if str(item).strip()]

    acao_n1 = data.get("acao_recomendada_n1")
    if not isinstance(acao_n1, list):
        acao_n1 = []
    acao_n1_texto = [str(item).strip() for item in acao_n1 if str(item).strip()]

    return {
        "cenario": str(data.get("cenario", "")).strip() or "Ticket sem contexto suficiente.",
        "causa_provavel": str(data.get("causa_provavel", "")).strip() or "Nao identificada com base no historico.",
        "chamados_relacionados": chamados_relacionados,
        "analise_chamados": str(data.get("analise_chamados", "")).strip(),
        "acao_recomendada_n1": acao_n1_texto,
        "criterios_escalonamento_n2": criterios_texto,
        "passos_n1": passos_texto[:3],
        "indicacao": indicacao,
        "confianca": confianca,
    }


def _render_jira_comment(analysis: dict[str, Any], similares: list[dict]) -> str:
    llm_related = analysis.get("chamados_relacionados", [])
    chamados_linhas: list[str] = []
    resumo_por_chave = {
        str(ticket.get("chave_jira", "")).strip(): str(ticket.get("resumo", "")).strip()
        for ticket in similares
        if ticket.get("chave_jira")
    }
    if isinstance(llm_related, list):
        for item in llm_related[:4]:
            if not isinstance(item, dict):
                continue
            key = str(item.get("id", "")).strip()
            if key and _is_jira_issue_key(key):
                resumo = resumo_por_chave.get(key, "")
                if resumo:
                    chamados_linhas.append(f"- {key} – {resumo[:140]}")

    if not chamados_linhas:
        for t in similares[:4]:
            if not t.get("chave_jira"):
                continue
            resumo = str(t.get("resumo", "")).strip()
            if resumo:
                chamados_linhas.append(f"- {t['chave_jira']} – {resumo[:140]}")

    if len(chamados_linhas) < 2 and similares:
        for t in similares:
            linha = f"- {t['chave_jira']} – {str(t.get('resumo', 'Contexto similar')).strip()[:90]}"
            if linha not in chamados_linhas:
                chamados_linhas.append(linha)
            if len(chamados_linhas) >= 2:
                break

    if not chamados_linhas:
        chamados_linhas = ["- N/A – Sem chamados suficientes na base para referencia"]

    analise_chamados = analysis.get("analise_chamados", "").strip() or _build_analise_chamados(similares)

    acoes = analysis.get("acao_recomendada_n1", [])
    if not isinstance(acoes, list):
        acoes = []
    acoes = [str(item).strip() for item in acoes if str(item).strip()]
    if not acoes:
        acoes = analysis.get("passos_n1", [])
    while len(acoes) < 3:
        acoes.append(f"Passo operacional N1 {len(acoes) + 1}.")

    criterios = analysis.get("criterios_escalonamento_n2", [])
    if not isinstance(criterios, list):
        criterios = []
    criterios = [str(item).strip() for item in criterios if str(item).strip()]
    if not criterios:
        criterios = _build_criterios_escalonamento_lista(similares)

    indicacao = str(analysis.get("indicacao", "Resolver no N1")).strip()
    if indicacao not in {"Resolver no N1", "Escalar para N2"}:
        indicacao = "Escalar para N2" if "n2" in indicacao.lower() else "Resolver no N1"

    confianca_raw = str(analysis.get("confianca", "Media")).strip().lower()
    if confianca_raw.startswith("alt"):
        confianca = "Alta"
    elif confianca_raw.startswith("baix"):
        confianca = "Baixa"
    else:
        confianca = "Média"

    return (
        "Triagem de Conhecimento\n\n"
        "Cenário identificado:\n"
        f"{analysis['cenario']}\n\n"
        "Causa provável:\n"
        f"{analysis.get('causa_provavel', 'Não identificada com base no histórico.')}\n\n"
        "Chamados relacionados (referência):\n"
        + "\n".join(chamados_linhas[:4])
        + "\n\n"
        "Análise dos chamados:\n"
        f"{analise_chamados}\n\n"
        "Ação recomendada (N1):\n"
        f"1. {acoes[0]}\n"
        f"2. {acoes[1]}\n"
        f"3. {acoes[2]}\n\n"
        "Critério de escalonamento para N2:\n"
        + "\n".join(f"- {c}" for c in criterios)
        + "\n\n"
        "Indicação:\n"
        f"{indicacao}\n\n"
        "Confiança da recomendação:\n"
        f"{confianca}"
    )
def _is_jira_issue_key(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z][A-Za-z0-9_]*-\d+$", value.strip()))


def _build_analise_chamados(similares: list[dict]) -> str:
    if not similares:
        return (
            "Nao ha volume suficiente de chamados correlatos para definir um padrao robusto. "
            "A demanda atual parece operacional e requer validacao guiada no N1 antes de escalonamento."
        )

    temas = [str(s.get("subtema") or s.get("tema") or "").strip() for s in similares if s.get("tema") or s.get("subtema")]
    temas = [t for t in temas if t]
    if temas:
        top_temas = ", ".join(list(dict.fromkeys(temas))[:3])
        return (
            f"Os chamados relacionados convergem para {top_temas}. "
            "O padrao predominante indica duvidas operacionais/procedimentais no uso da funcionalidade, "
            "com necessidade de orientacao de fluxo e validacao de parametros antes de escalar."
        )

    return (
        "Os chamados apresentam comportamento semelhante ao cenario atual, com recorrencia de duvidas "
        "de operacao e necessidade de validacao orientada no primeiro nivel."
    )


def _build_criterios_escalonamento_lista(similares: list[dict]) -> list[str]:
    if not similares:
        return [
            "Ausencia de precedente suficiente na base para orientar acao segura no N1.",
            "Falha recorrente apos tentativa guiada de resolucao operacional.",
        ]
    return [
        "Escalar se houver erro sistemico ou indisponibilidade da funcionalidade.",
        "Escalar se o procedimento padrao for seguido e o resultado continuar incorreto.",
        "Escalar se houver dependencia de ajuste tecnico em integracoes (ex: NetSuite).",
    ]


def _render_chat_response(payload: dict[str, str], tickets: list[str]) -> str:
    refs = "\n".join(f"- {ticket}" for ticket in tickets) or "- N/A"
    return (
        "Sintese:\n"
        f"{payload.get('sintese', 'Sem sintese disponivel.')}\n"
        "Padrao observado:\n"
        f"{payload.get('padrao_observado', 'Sem padrao identificado.')}\n"
        "Solucao mais recorrente:\n"
        f"{payload.get('solucao_recorrente', 'Sem solucao recorrente identificada.')}\n"
        "Chamados de referencia:\n"
        f"{refs}"
    )


def _extract_cenario(resumo: str, descricao: str) -> str:
    """Extrai cenario objetivo a partir do resumo e descricao do ticket."""
    import re
    # Try to extract the first meaningful sentence from descricao
    desc_clean = re.sub(r"\s+", " ", (descricao or "").strip())
    if desc_clean:
        sentences = re.split(r"(?<=[.!?])\s+", desc_clean)
        first = next((s.strip() for s in sentences if len(s.strip()) > 20), "")
        if first:
            return first[:300]
    # Fallback to resumo if descricao is empty or too short
    resumo_clean = (resumo or "").strip()[:280]
    return resumo_clean or "Ticket sem contexto suficiente."


def _extract_causa(similares: list[dict]) -> str:
    """Infere causa provavel a partir dos tickets relacionados."""
    problemas = [
        str(s.get("problema") or s.get("resumo") or "").strip()
        for s in similares[:2]
        if (s.get("problema") or s.get("resumo"))
    ]
    problemas = [p[:200] for p in problemas if p]
    if not problemas:
        return "Nao identificada com base no historico disponivel."
    if len(problemas) == 1:
        return f"Com base no historico: {problemas[0]}"
    return f"Padrao recorrente nos chamados relacionados: {problemas[0]}"


def _build_passos_n1(resumo: str, descricao: str, similares: list[dict]) -> list[str]:
    """Gera passos N1 contextuais com base no tipo de chamado."""
    texto = (resumo + " " + descricao).lower()

    if any(t in texto for t in ["nao integra", "erro integr", "rejeic", "rejeit"]):
        return [
            "Verificar log de integracao e identificar o codigo de erro retornado.",
            "Confirmar se o documento apresenta os campos obrigatorios preenchidos corretamente.",
            "Reprocessar o documento apos correcao e validar o status na plataforma.",
        ]
    if any(t in texto for t in ["relatorio", "extrat", "report", "informe"]):
        return [
            "Confirmar o periodo e os filtros utilizados na geracao do relatorio.",
            "Verificar se ha atualizacao pendente de dados na base antes de gerar o relatorio.",
            "Reproduzir a geracao e capturar a tela ou arquivo de saida para evidencia.",
        ]
    if any(t in texto for t in ["lentidao", "lento", "timeout", "instabilidade", "demora"]):
        return [
            "Registrar horario e duracao do comportamento lento para correlacionar com janelas de manutencao.",
            "Verificar se o problema e isolado ao cliente ou sistemico (outros usuarios afetados).",
            "Acionar monitoramento e registrar evidencia antes de escalar para N2.",
        ]
    if any(t in texto for t in ["nota fiscal", "nfe", "nf-e", "emissao", "emissão"]):
        return [
            "Validar os dados do emitente, destinatario e itens da nota antes de reenviar.",
            "Verificar a mensagem de retorno da SEFAZ e identificar o codigo de rejeicao.",
            "Aplicar a correcao indicada pelo codigo de rejeicao e reprocessar a nota.",
        ]
    if any(t in texto for t in ["configur", "parametr", "setup"]):
        return [
            "Confirmar as configuracoes atuais do ambiente e comparar com o padrao esperado.",
            "Aplicar o ajuste de parametro identificado nos chamados relacionados.",
            "Validar o comportamento apos a alteracao e registrar as mudancas realizadas.",
        ]
    # Default generico mas mais acionavel
    top_resumo = str(similares[0].get("resumo", "")).strip()[:120] if similares else ""
    passo2 = (
        f"Aplicar procedimento documentado no chamado relacionado: {top_resumo}"
        if top_resumo
        else "Aplicar correcao identificada nos chamados similares da base de conhecimento."
    )
    return [
        "Reproduzir o problema no ambiente do cliente e coletar evidencias (logs, prints).",
        passo2,
        "Validar a resolucao com o cliente e registrar o procedimento aplicado no ticket.",
    ]


def _build_criterio_escalonamento(similares: list[dict]) -> str:
    """Define criterio de escalonamento N2 com base nos chamados relacionados."""
    if not similares:
        return "Escalar N2 imediatamente por ausencia de historico similar na base."
    top_confianca = similares[0].get("confianca", 0.0)
    if top_confianca < 0.55:
        return "Escalar N2 dado que nao ha precedente claro na base de conhecimento."
    return (
        "Escalar N2 se o problema persistir apos aplicar os passos sugeridos "
        "ou se houver impacto em multiplos usuarios/empresas."
    )


def _build_solution_proposal(similares: list[dict]) -> str:
    solutions: list[str] = [
        str(s.get("solucao", "")).strip()
        for s in similares
        if s.get("solucao") and "sem solucao" not in str(s.get("solucao", "")).lower()
    ]
    solutions = [s for s in solutions if s]

    if not solutions:
        top_problema = next(
            (str(s.get("problema") or s.get("resumo") or "").strip()[:180] for s in similares if s.get("problema") or s.get("resumo")),
            "",
        )
        if top_problema:
            return (
                f"Sem solucao explicita registrada na base. "
                f"Sugerido com base nos sintomas similares: validar o cenario '{top_problema}' "
                f"e aplicar o procedimento de correcao equivalente com registro de evidencias."
            )
        return "Sem solucao recorrente documentada. Realizar analise N1 e validar com especialista antes de atuar."

    if len(solutions) == 1:
        return f"Solucao documentada nos chamados relacionados: {solutions[0]}"

    return (
        f"Solucoes recorrentes nos chamados relacionados: "
        f"1) {solutions[0][:200]}  "
        f"2) {solutions[1][:200]}"
    )
