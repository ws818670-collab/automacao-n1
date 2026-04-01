import re
import unicodedata


def consolidate_ticket_text(resumo: str, descricao: str, comentarios: str) -> str:
    blocks = [resumo or "", descricao or "", comentarios or ""]
    consolidated = "\n\n".join(b.strip() for b in blocks if b and b.strip())
    return clean_text(consolidated)


def clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\{[^{}]*\}", "", text)
    return text.strip()


def extract_problem_solution_context(consolidated_text: str) -> tuple[str, str, str]:
    text_lower = consolidated_text.lower()

    problem = consolidated_text[:350]
    if "erro" in text_lower:
        problem = _extract_sentence(consolidated_text, "erro")
    elif "falha" in text_lower:
        problem = _extract_sentence(consolidated_text, "falha")

    solution = "Sem solucao explicita no historico."
    for marker in ["resolvido", "solucao", "ajuste", "corrigido", "aplicar"]:
        if marker in text_lower:
            solution = _extract_sentence(consolidated_text, marker)
            break

    context = consolidated_text[:500]
    return problem, solution, context


def classify_ticket_theme(resumo: str, descricao: str, comentarios: str, produto: str = "") -> tuple[str, str]:
    text = _normalize_for_match(" ".join([resumo or "", descricao or "", comentarios or ""]))

    # Se o campo produto estiver preenchido, usa-o como sinal primario
    produto_norm = _normalize_for_match(produto)
    if _contains_any(produto_norm, ["taxdocs", "tax docs"]):
        if _contains_any(text, ["relatorio", "report", "extrair", "extracao"]):
            return ("TaxDocs", "Relatorios e extracao")
        return ("TaxDocs", "Captura e download de documentos")
    if _contains_any(produto_norm, ["tax compliance", "taxcompliance"]):
        if _contains_any(text, ["relatorio", "report", "extrair", "extracao", "informe", "rendimentos", "padrao 135"]):
            return ("Tax Compliance", "Relatorios e extracao")
        if _contains_any(text, ["obrigacao", "obrigacoes", "reinf", "sped", "dirb", "informes"]):
            return ("Tax Compliance", "Obrigacoes acessorias")
        if _contains_any(text, ["integracao", "integra", "documentos com erro", "rejeicao"]):
            return ("Tax Compliance", "Integracao de documentos")
        return ("Tax Compliance", "Operacao e consultas")
    if _contains_any(produto_norm, ["avatax", "avatx"]):
        return ("Mensageria e Avatax", "Emissoes e calculos fiscais")
    if _contains_any(produto_norm, ["tax central", "taxcentral"]):
        return ("Tax Central", "Calendario de obrigacoes")

    # Fallback: inferencia pelo texto
    if _contains_any(text, ["relatorio", "report", "extrair", "extracao", "informe", "rendimentos", "padrao 135"]):
        if _contains_any(text, ["tax compliance", "taxcompliance", "ibs", "cbs"]):
            return ("Tax Compliance", "Relatorios e extracao")
        return ("Consultas e Relatorios", "Extracao e conferencias")

    if _contains_any(text, ["tax docs", "taxdocs", "tax docs monitor", "download de documentos", "captura", "nfse"]):
        return ("TaxDocs", "Captura e download de documentos")

    if _contains_any(text, ["tax compliance", "taxcompliance"]):
        if _contains_any(text, ["obrigacao", "obrigacoes", "reinf", "sped", "dirb", "informes"]):
            return ("Tax Compliance", "Obrigacoes acessorias")
        if _contains_any(text, ["integracao", "integra", "documentos com erro", "rejeicao"]):
            return ("Tax Compliance", "Integracao de documentos")
        return ("Tax Compliance", "Operacao e consultas")

    if _contains_any(text, ["avatx", "avatax", "avalara", "mensagem sw fiscal", "cclasstrib", "ibs", "cbs", "beneficio fiscal"]):
        return ("Mensageria e Avatax", "Emissoes e calculos fiscais")

    if _contains_any(text, ["nota fiscal", "emissao", "nfe", "nf-e", "cte", "ct-e"]):
        return ("Mensageria e Avatax", "Emissoes e calculos fiscais")

    if _contains_any(text, ["integracao", "lote", "xml", "documento fiscal"]):
        return ("Integracao Fiscal", "Processamento e integracao")

    return ("Geral", "Analise funcional")


def infer_query_theme(query_text: str, produto: str = "") -> tuple[str, str]:
    return classify_ticket_theme(query_text, query_text, "", produto)


def _contains_any(text: str, terms: list[str]) -> bool:
    return any(term in text for term in terms)


def _normalize_for_match(text: str) -> str:
    cleaned = clean_text(text)
    ascii_text = unicodedata.normalize("NFKD", cleaned).encode("ascii", "ignore").decode("ascii")
    return ascii_text.lower()


def _extract_sentence(text: str, keyword: str) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    for sentence in sentences:
        if keyword.lower() in sentence.lower():
            return sentence.strip()
    return text[:300].strip()
