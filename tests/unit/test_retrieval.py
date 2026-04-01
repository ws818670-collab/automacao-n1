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