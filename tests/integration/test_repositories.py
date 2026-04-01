from datetime import datetime, timezone

from models.repositories import upsert_ticket


class FakeSession:
    def __init__(self) -> None:
        self.ticket = None

    def scalar(self, *_args, **_kwargs):
        return self.ticket

    def add(self, ticket) -> None:
        self.ticket = ticket

    def flush(self) -> None:
        return None


def test_upsert_ticket_creates_new_ticket() -> None:
    db = FakeSession()
    ticket = upsert_ticket(
        db,
        chave_jira="JDMSN1-10",
        resumo="Resumo",
        descricao="Descricao",
        comentarios="Comentarios",
        produto="Tax Compliance",
        status="Concluido",
        data_criacao=datetime.now(timezone.utc),
        data_fechamento=None,
    )
    assert ticket.chave_jira == "JDMSN1-10"