from ingestion.service import IngestionResult, IngestionService


class DummyJiraClient:
    def __init__(self, issues):
        self.issues = issues

    def search_issues(self, _jql, max_results=0):
        if max_results > 0:
            return self.issues[:max_results]
        return self.issues


class DummyEmbeddingService:
    def embed(self, _text):
        return [0.0, 0.0]


class DummySession:
    def begin_nested(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def commit(self):
        return None


def test_ingest_historical_continues_on_individual_failure(monkeypatch) -> None:
    issues = [{"key": "JDMSN1-1"}, {"key": "JDMSN1-2"}]
    service = IngestionService(DummyJiraClient(issues), DummyEmbeddingService())
    db = DummySession()

    monkeypatch.setattr("ingestion.service.normalize_issue", lambda issue: {"chave_jira": issue["key"]})
    monkeypatch.setattr("ingestion.service.sync_ticket_scope", lambda *args, **kwargs: None)

    calls = {"count": 0}

    def fake_process(_db, ticket):
        calls["count"] += 1
        if ticket["chave_jira"] == "JDMSN1-2":
            raise Exception("falhou")
        return 1

    monkeypatch.setattr(service, "process_ticket_data", fake_process)

    result = service.ingest_historical(db, "project = JDMSN1")

    assert isinstance(result, IngestionResult)
    assert result.processed == 1
    assert result.failed == 1
    assert result.ignored == 0