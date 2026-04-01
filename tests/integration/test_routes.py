def test_health_endpoint_returns_status(test_client) -> None:
    response = test_client.get("/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert "timestamp" in body
    assert response.headers.get("X-Correlation-ID")


def test_chat_query_returns_fallback_flag(test_client, monkeypatch) -> None:
    import api.routes as routes

    monkeypatch.setattr(
        routes.llm_service,
        "chat_query",
        lambda *args, **kwargs: ("Resposta sintetizada", ["JDMSN1-1"], True),
    )

    response = test_client.post("/v1/chat/query", json={"pergunta": "Como resolver relatorio travado?"})
    assert response.status_code == 200
    body = response.json()
    assert body["fallback"] is True
    assert body["tickets_relacionados"] == ["JDMSN1-1"]


def test_chat_query_rejects_blank_question(test_client) -> None:
    response = test_client.post("/v1/chat/query", json={"pergunta": "  "})
    assert response.status_code == 422


def test_analyze_preview_returns_comment(test_client, monkeypatch) -> None:
    import api.routes as routes

    monkeypatch.setattr(routes.jira_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        routes.llm_service,
        "generate_triage_comment",
        lambda *args, **kwargs: ("Comentario sugerido", ["JDMSN1-2"], False),
    )

    response = test_client.get("/v1/jira/analyze-preview", params={"chave_jira": "JDMSN1-123"})
    assert response.status_code == 200
    body = response.json()
    assert body["comentario"] == "Comentario sugerido"
    assert body["tickets_relacionados"] == ["JDMSN1-2"]


def test_analyze_preview_returns_404_when_issue_missing(test_client, monkeypatch) -> None:
    import api.routes as routes
    from exceptions import JiraIssueNotFoundError

    monkeypatch.setattr(routes.jira_client, "is_configured", lambda: True)

    def raise_not_found(*args, **kwargs):
        raise JiraIssueNotFoundError("Ticket JDMSN1-999 nao encontrado no Jira")

    monkeypatch.setattr(routes.llm_service, "generate_triage_comment", raise_not_found)

    response = test_client.get("/v1/jira/analyze-preview", params={"chave_jira": "JDMSN1-999"})
    assert response.status_code == 404