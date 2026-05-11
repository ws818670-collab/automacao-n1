from types import SimpleNamespace

from retrieval.service import RetrievalService


def test_find_similar_returns_ranked_candidates(monkeypatch) -> None:
    ticket = SimpleNamespace(
        id=1,
        chave_jira="JDMSN1-1",
        resumo="Relatorio travado",
        descricao="Relatorio fiscal nao processa",
        comentarios="",
        produto="Tax Compliance",
        status="Concluido",
        analise=SimpleNamespace(problema="Relatorio nao gera", solucao="Ajustar filtro", categoria="Tax Compliance|Relatorios e extracao"),
    )

    monkeypatch.setattr("retrieval.service.search_similar_tickets", lambda *args, **kwargs: [(ticket, 0.1)])
    monkeypatch.setattr("retrieval.service.get_recent_tickets", lambda *args, **kwargs: [ticket])

    service = RetrievalService()
    result = service.find_similar(None, [0.1, 0.2], query_text="relatorio tax compliance", query_produto="Tax Compliance")
    assert result
    assert result[0]["chave_jira"] == "JDMSN1-1"


def test_find_similar_ignores_low_context_taxonomy_only_candidate(monkeypatch) -> None:
    semantic_match = SimpleNamespace(
        id=1,
        chave_jira="JDMSN1-SEM",
        resumo="Erro ao gerar relatorio de rendimentos",
        descricao="Cliente nao consegue extrair relatorio no tax compliance",
        comentarios="",
        produto="Tax Compliance",
        status="Concluido",
        analise=SimpleNamespace(
            problema="Falha na extracao do relatorio",
            solucao="Ajustar parametro de periodo",
            categoria="Tax Compliance|Relatorios e extracao",
        ),
    )
    taxonomy_only = SimpleNamespace(
        id=2,
        chave_jira="JDMSN1-TAX",
        resumo="Ajuste de rotina sem contexto da abertura",
        descricao="Caso sem relacao com relatorio atual",
        comentarios="",
        produto="Tax Compliance",
        status="Concluido",
        analise=SimpleNamespace(
            problema="Rotina geral",
            solucao="Atualizacao de ambiente",
            categoria="Tax Compliance|Relatorios e extracao",
        ),
    )

    monkeypatch.setattr(
        "retrieval.service.search_similar_tickets",
        lambda *args, **kwargs: [(semantic_match, 0.05)],
    )
    monkeypatch.setattr(
        "retrieval.service.get_recent_tickets",
        lambda *args, **kwargs: [semantic_match, taxonomy_only],
    )

    service = RetrievalService()
    result = service.find_similar(
        None,
        [0.1, 0.2],
        query_text="erro para gerar relatorio de rendimentos no tax compliance",
        query_produto="Tax Compliance",
    )

    keys = [item["chave_jira"] for item in result]
    assert "JDMSN1-SEM" in keys
    assert "JDMSN1-TAX" not in keys