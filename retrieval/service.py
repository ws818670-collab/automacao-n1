import re
import unicodedata

from sqlalchemy.orm import Session

from models.entities import Ticket
from models.repositories import get_recent_tickets, search_similar_tickets
from processing.text_processing import infer_query_theme
from utils.config import get_settings

settings = get_settings()


class RetrievalService:
    def __init__(self, top_k: int = 5, min_score: float = 0.75) -> None:
        self.top_k = top_k
        self.min_score = min_score

    def find_similar(
        self,
        db: Session,
        vector: list[float],
        top_k: int | None = None,
        min_score: float | None = None,
        exclude_ticket_key: str | None = None,
        allowed_statuses: list[str] | None = None,
        query_text: str = "",
        query_produto: str = "",
    ) -> list[dict]:
        requested_top_k = top_k or self.top_k
        candidate_top_k = max(requested_top_k * 8, 20)
        semantic_rows = search_similar_tickets(
            db,
            vector,
            top_k=candidate_top_k,
            exclude_ticket_key=exclude_ticket_key,
            allowed_statuses=allowed_statuses,
        )
        base_threshold = min_score if min_score is not None else self.min_score
        result: list[dict] = []
        query_terms = _tokenize_relevant_terms(query_text)
        query_theme, query_subtheme = infer_query_theme(query_text, query_produto)
        candidates: list[dict] = []
        tickets_by_id: dict[int, tuple[Ticket, float | None]] = {}

        for ticket, distance in semantic_rows:
            tickets_by_id[ticket.id] = (ticket, distance)

        for ticket in get_recent_tickets(db, limit=300):
            if exclude_ticket_key and ticket.chave_jira == exclude_ticket_key:
                continue
            if allowed_statuses and ticket.status not in allowed_statuses:
                continue
            tickets_by_id.setdefault(ticket.id, (ticket, None))

        for ticket, distance in tickets_by_id.values():
            if _is_noise_ticket(ticket):
                continue

            vector_score = max(0.0, 1.0 - distance) if distance is not None else 0.0
            keyword_score = _keyword_overlap_score(query_terms, ticket)
            taxonomy_score = _taxonomy_alignment_score(ticket, query_theme, query_subtheme)
            intent_score = _intent_alignment_score(ticket, query_terms, query_subtheme)
            title_score = _title_alignment_score(ticket, query_terms, query_subtheme)
            product_score = _product_alignment_score(ticket, query_produto, query_theme)
            hybrid_score = max(
                vector_score,
                (settings.retrieval_vector_weight * vector_score)
                + (settings.retrieval_lexical_weight * keyword_score)
                + (settings.retrieval_taxonomy_weight * taxonomy_score)
                + (settings.retrieval_intent_weight * intent_score)
                + (settings.retrieval_title_weight * title_score)
                + (settings.retrieval_product_weight * product_score),
            )

            payload = _ticket_to_payload(ticket, hybrid_score)
            payload["score_semantico"] = vector_score
            payload["score_lexico"] = keyword_score
            payload["score_taxonomia"] = taxonomy_score
            payload["score_intencao"] = intent_score
            payload["score_titulo"] = title_score
            payload["score_produto"] = product_score
            candidates.append(payload)

        threshold = _dynamic_threshold(base_threshold, query_terms, candidates)

        for payload in candidates:
            hybrid_score = float(payload.get("confianca", 0.0))
            vector_score = float(payload.get("score_semantico", 0.0))
            keyword_score = float(payload.get("score_lexico", 0.0))
            taxonomy_score = float(payload.get("score_taxonomia", 0.0))
            intent_score = float(payload.get("score_intencao", 0.0))
            title_score = float(payload.get("score_titulo", 0.0))
            product_score = float(payload.get("score_produto", 0.0))

            if query_subtheme == "Relatorios e extracao":
                is_exact_report_match = taxonomy_score >= 1.0
                has_report_evidence = intent_score >= 0.7 or title_score >= 0.25
                if not is_exact_report_match and not has_report_evidence:
                    continue

            # Taxonomy-only matches are often too broad and lead to repetitive references.
            # Require at least one contextual signal beyond taxonomy when score is below threshold.
            if hybrid_score < threshold and max(vector_score, keyword_score, intent_score, title_score, product_score) < 0.4:
                continue
            payload["threshold_aplicado"] = threshold
            result.append(payload)

        if result:
            import logging

            logging.getLogger(__name__).info(
                "retrieval_candidates_scored",
                extra={
                    "candidate_count": len(result),
                    "top_scores": [round(float(item.get("confianca", 0.0)), 4) for item in result[:5]],
                },
            )

        result = _prioritize_same_taxonomy(result, query_theme, query_subtheme)
        result.sort(key=_result_sort_key, reverse=True)
        return result[:requested_top_k]


def _ticket_to_payload(ticket: Ticket, score: float) -> dict:
    analise = getattr(ticket, "analise", None)
    categoria = analise.categoria if analise and getattr(analise, "categoria", "") else "Geral|Analise funcional"
    tema, subtema = _split_category(categoria)
    data_criacao_value = getattr(ticket, "data_criacao", None)
    data_criacao = data_criacao_value.strftime("%Y-%m-%d") if data_criacao_value else None
    return {
        "ticket_id": ticket.id,
        "chave_jira": ticket.chave_jira,
        "resumo": ticket.resumo,
        "descricao": ticket.descricao,
        "comentarios": ticket.comentarios,
        "produto": getattr(ticket, "produto", "") or "",
        "status": getattr(ticket, "status", "") or "",
        "data_criacao": data_criacao,
        "problema": analise.problema if analise else "",
        "solucao": analise.solucao if analise else "",
        "tema": tema,
        "subtema": subtema,
        "confianca": score,
    }


def _tokenize_relevant_terms(text: str) -> set[str]:
    if not text.strip():
        return set()

    stopwords = {
        "de",
        "da",
        "do",
        "das",
        "dos",
        "a",
        "o",
        "as",
        "os",
        "e",
        "em",
        "para",
        "por",
        "com",
        "sem",
        "no",
        "na",
        "nos",
        "nas",
        "um",
        "uma",
        "que",
    }
    normalized = _normalize_text(text)
    terms = {term for term in re.findall(r"[a-zA-Z0-9_]{3,}", normalized) if term not in stopwords}
    return _expand_domain_terms(terms)


def _keyword_overlap_score(query_terms: set[str], ticket: Ticket) -> float:
    if not query_terms:
        return 0.0

    corpus = _normalize_text(
        " ".join(
            [
                ticket.resumo or "",
                ticket.descricao or "",
                ticket.comentarios or "",
                ticket.analise.problema if ticket.analise else "",
                ticket.analise.solucao if ticket.analise else "",
            ]
        )
    )
    if not corpus.strip():
        return 0.0

    overlap = 0
    for term in query_terms:
        if term in corpus:
            overlap += 1

    base_score = overlap / max(len(query_terms), 1)
    phrase_boost = _phrase_boost(query_terms, corpus)
    return min(1.0, base_score + phrase_boost)


def _title_alignment_score(ticket: Ticket, query_terms: set[str], query_subtheme: str) -> float:
    if not query_terms:
        return 0.0

    title = _normalize_text(ticket.resumo or "")
    overlap = sum(1 for term in query_terms if term in title)
    score = overlap / max(len(query_terms), 1)

    if query_subtheme == "Relatorios e extracao":
        if any(term in title for term in ["relatorio", "report", "informe", "extracao", "consulta"]):
            score += 0.5
        if any(term in title for term in ["tax compliance", "taxcompliance", "ibs", "cbs"]):
            score += 0.2

    return min(1.0, score)


def _normalize_text(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return ascii_text.lower()


def _expand_domain_terms(terms: set[str]) -> set[str]:
    expanded = set(terms)
    domain_map = {
        "tax": {"tax", "taxdocs", "imposto", "fiscal", "tributario", "tributaria"},
        "compliance": {"compliance", "fiscal", "regra", "validacao", "conformidade"},
        "relatorio": {"relatorio", "report", "extrato", "consulta"},
        "nota": {"nota", "nf", "nfe", "danfe", "fiscal"},
        "integracao": {"integracao", "integrar", "interface", "processamento"},
    }

    for trigger, related in domain_map.items():
        if trigger in terms:
            expanded.update(related)

    if "tax" in expanded and "compliance" in expanded:
        expanded.update({"taxcompliance", "taxdocs", "fiscal"})

    return expanded


def _phrase_boost(query_terms: set[str], corpus: str) -> float:
    boosts = 0.0
    if {"tax", "compliance"}.issubset(query_terms):
        if "tax compliance" in corpus or "taxcompliance" in corpus:
            boosts += 0.25
    if "relatorio" in query_terms and "relatorio" in corpus:
        boosts += 0.1
    if "fiscal" in query_terms and "fiscal" in corpus:
        boosts += 0.05
    return boosts


def _dynamic_threshold(base_threshold: float, query_terms: set[str], candidates: list[dict]) -> float:
    threshold = base_threshold

    # Queries with very few terms are ambiguous: be stricter.
    if len(query_terms) <= 2:
        threshold += 0.05

    # Known domain pair "tax compliance" should tolerate slightly lower score.
    if {"tax", "compliance"}.issubset(query_terms):
        threshold -= 0.1

    if candidates:
        best = max(float(item.get("confianca", 0.0)) for item in candidates)
        avg = sum(float(item.get("confianca", 0.0)) for item in candidates) / max(len(candidates), 1)

        # If all scores are globally low but close, avoid over-pruning potentially relevant cases.
        if best < 0.72 and avg > 0.5:
            threshold -= 0.06

    return max(0.58, min(0.9, threshold))


def _taxonomy_alignment_score(ticket: Ticket, query_theme: str, query_subtheme: str) -> float:
    categoria = ticket.analise.categoria if ticket.analise else ""
    tema, subtema = _split_category(categoria)
    score = 0.0
    if tema == query_theme:
        score += 0.7
    if subtema == query_subtheme:
        score += 0.3
    return score


def _intent_alignment_score(ticket: Ticket, query_terms: set[str], query_subtheme: str) -> float:
    text = _normalize_text(
        " ".join(
            [
                ticket.resumo or "",
                ticket.descricao or "",
                ticket.comentarios or "",
            ]
        )
    )

    score = 0.0
    if query_subtheme == "Relatorios e extracao":
        if any(term in text for term in ["relatorio", "report", "extrair", "extracao", "consulta", "download", "informe", "padrao 135"]):
            score += 0.7
        if "tax compliance" in text or "taxcompliance" in text:
            score += 0.2
        if any(term in query_terms for term in {"tax", "compliance"}) and "fiscal" in text:
            score += 0.1

    if query_subtheme == "Captura e download de documentos":
        if any(term in text for term in ["download", "captura", "nfse", "monitor", "documentos"]):
            score += 0.8

    return min(1.0, score)


def _product_alignment_score(ticket: Ticket, query_produto: str, query_theme: str) -> float:
    """Boost para tickets do mesmo produto do chamado em analise.

    Se o produto do ticket bater exatamente com o da query: score 1.0.
    Se o tema da taxonomia bater: score 0.5.
    Produto diferente e conhecido: penalidade -0.2 (retorna 0.0 apos clamp).
    """
    ticket_produto = _normalize_text(getattr(ticket, "produto", "") or "")
    qp = _normalize_text(query_produto or "")

    if not qp and not ticket_produto:
        return 0.0

    # Match exato de produto
    if qp and ticket_produto and (qp in ticket_produto or ticket_produto in qp):
        return 1.0

    # Match pelo tema derivado do produto na query
    categoria = ticket.analise.categoria if ticket.analise else ""
    tema_ticket, _ = _split_category(categoria)
    if query_theme and tema_ticket == query_theme:
        return 0.5

    # Produto preenchido e diferente = penalidade leve
    if qp and ticket_produto and qp not in ticket_produto and ticket_produto not in qp:
        return 0.0  # Nao penaliza negativamente no hybrid_score (max(vector_score, ...))

    return 0.0


def _split_category(categoria: str) -> tuple[str, str]:
    if "|" not in categoria:
        return (categoria or "Geral", "Analise funcional")
    tema, subtema = categoria.split("|", 1)
    return (tema.strip() or "Geral", subtema.strip() or "Analise funcional")


def _prioritize_same_taxonomy(items: list[dict], query_theme: str, query_subtheme: str) -> list[dict]:
    if not items:
        return items

    exact = [
        item
        for item in items
        if item.get("tema") == query_theme and item.get("subtema") == query_subtheme
    ]
    theme_only = [
        item
        for item in items
        if item.get("tema") == query_theme and item.get("subtema") != query_subtheme
    ]
    others = [item for item in items if item.get("tema") != query_theme]

    if exact:
        return exact + theme_only + others

    if theme_only:
        return theme_only + others

    return items


def _is_noise_ticket(ticket: Ticket) -> bool:
    text = _normalize_text(" ".join([ticket.resumo or "", ticket.descricao or ""]))
    noise_markers = [
        "teste de automacao",
        "teste automacao",
        "automacao n1",
        "validacao da nota interna",
        "api property",
        "webhook",
    ]
    return any(marker in text for marker in noise_markers)


def _result_sort_key(item: dict) -> tuple[float, float, float, float, float, float]:
    return (
        float(item.get("confianca", 0.0)),
        float(item.get("score_semantico", 0.0)),
        float(item.get("score_lexico", 0.0)),
        float(item.get("score_taxonomia", 0.0)),
        float(item.get("score_intencao", 0.0)),
        float(item.get("score_titulo", 0.0)),
    )
