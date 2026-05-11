from datetime import datetime, timezone

from models.repositories import (
    get_recent_tickets,
    get_ticket_by_key,
    search_similar_tickets,
    sync_ticket_scope,
    upsert_analise,
    upsert_embedding,
    upsert_ticket,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ticket(db, key: str = "JDMSN1-10", status: str = "Concluido"):
    return upsert_ticket(
        db,
        chave_jira=key,
        resumo="Resumo",
        descricao="Descricao",
        comentarios="Comentarios",
        produto="Tax Compliance",
        status=status,
        data_criacao=datetime.now(timezone.utc),
        data_fechamento=None,
    )


def _unit_vector(dim: int, hot_index: int = 0) -> list[float]:
    v = [0.0] * dim
    v[hot_index] = 1.0
    return v


# ---------------------------------------------------------------------------
# upsert_ticket
# ---------------------------------------------------------------------------

def test_upsert_ticket_creates_new(sqlite_session) -> None:
    ticket = _make_ticket(sqlite_session)
    sqlite_session.commit()
    assert ticket.chave_jira == "JDMSN1-10"
    assert ticket.id is not None


def test_upsert_ticket_updates_existing(sqlite_session) -> None:
    _make_ticket(sqlite_session)
    sqlite_session.commit()

    updated = upsert_ticket(
        sqlite_session,
        chave_jira="JDMSN1-10",
        resumo="Novo resumo",
        descricao="Nova desc",
        comentarios="",
        produto="AvataxBR",
        status="Aberto",
        data_criacao=None,
        data_fechamento=None,
    )
    sqlite_session.commit()

    assert updated.resumo == "Novo resumo"
    assert updated.produto == "AvataxBR"


# ---------------------------------------------------------------------------
# upsert_embedding / upsert_analise
# ---------------------------------------------------------------------------

def test_upsert_embedding_creates_and_updates(sqlite_session) -> None:
    ticket = _make_ticket(sqlite_session)
    sqlite_session.commit()

    dim = 8
    emb = upsert_embedding(sqlite_session, ticket_id=ticket.id, vector=_unit_vector(dim, 0))
    sqlite_session.commit()
    assert emb.embedding_vector[0] == 1.0

    upsert_embedding(sqlite_session, ticket_id=ticket.id, vector=_unit_vector(dim, 3))
    sqlite_session.commit()

    from models.entities import Embedding
    from sqlalchemy import select

    stored = sqlite_session.scalar(select(Embedding).where(Embedding.ticket_id == ticket.id))
    assert stored.embedding_vector[3] == 1.0


def test_upsert_analise_creates_and_updates(sqlite_session) -> None:
    ticket = _make_ticket(sqlite_session)
    sqlite_session.commit()

    upsert_analise(
        sqlite_session,
        ticket_id=ticket.id,
        problema="Erro X",
        solucao="Reiniciar",
        categoria="Tax Compliance|Relatorios e extracao",
        confianca=0.9,
    )
    sqlite_session.commit()

    upsert_analise(
        sqlite_session,
        ticket_id=ticket.id,
        problema="Erro Y",
        solucao="Atualizar",
        categoria="Tax Compliance|Relatorios e extracao",
        confianca=0.7,
    )
    sqlite_session.commit()

    from models.entities import Analise
    from sqlalchemy import select

    stored = sqlite_session.scalar(select(Analise).where(Analise.ticket_id == ticket.id))
    assert stored.problema == "Erro Y"
    assert stored.confianca == 0.7


# ---------------------------------------------------------------------------
# get_ticket_by_key / get_recent_tickets
# ---------------------------------------------------------------------------

def test_get_ticket_by_key(sqlite_session) -> None:
    _make_ticket(sqlite_session)
    sqlite_session.commit()

    found = get_ticket_by_key(sqlite_session, "JDMSN1-10")
    assert found is not None
    assert found.chave_jira == "JDMSN1-10"

    assert get_ticket_by_key(sqlite_session, "INEXISTENTE") is None


def test_get_recent_tickets_returns_ordered(sqlite_session) -> None:
    _make_ticket(sqlite_session, key="JDMSN1-1")
    _make_ticket(sqlite_session, key="JDMSN1-2")
    sqlite_session.commit()

    tickets = get_recent_tickets(sqlite_session, limit=10)
    assert len(tickets) == 2


# ---------------------------------------------------------------------------
# search_similar_tickets (distância coseno em Python)
# ---------------------------------------------------------------------------

def test_search_similar_returns_closest(sqlite_session) -> None:
    dim = 8

    t1 = _make_ticket(sqlite_session, key="JDMSN1-A")
    t2 = _make_ticket(sqlite_session, key="JDMSN1-B")
    sqlite_session.commit()

    # t1: vetor aponta para dimensão 0; t2: aponta para dimensão 4
    upsert_embedding(sqlite_session, ticket_id=t1.id, vector=_unit_vector(dim, 0))
    upsert_embedding(sqlite_session, ticket_id=t2.id, vector=_unit_vector(dim, 4))
    sqlite_session.commit()

    # Query similar a t1
    results = search_similar_tickets(sqlite_session, vector=_unit_vector(dim, 0), top_k=2)

    assert results, "Deve retornar ao menos um resultado"
    top_ticket, top_distance = results[0]
    assert top_ticket.chave_jira == "JDMSN1-A"
    assert top_distance < 0.01  # distância coseno quase zero = idêntico


def test_search_similar_excludes_key(sqlite_session) -> None:
    dim = 8
    t1 = _make_ticket(sqlite_session, key="JDMSN1-X")
    sqlite_session.commit()
    upsert_embedding(sqlite_session, ticket_id=t1.id, vector=_unit_vector(dim, 0))
    sqlite_session.commit()

    results = search_similar_tickets(
        sqlite_session,
        vector=_unit_vector(dim, 0),
        exclude_ticket_key="JDMSN1-X",
    )
    assert results == []


def test_search_similar_filters_by_status(sqlite_session) -> None:
    dim = 8
    t_open = _make_ticket(sqlite_session, key="JDMSN1-O", status="Aberto")
    t_closed = _make_ticket(sqlite_session, key="JDMSN1-C", status="Concluido")
    sqlite_session.commit()

    upsert_embedding(sqlite_session, ticket_id=t_open.id, vector=_unit_vector(dim, 0))
    upsert_embedding(sqlite_session, ticket_id=t_closed.id, vector=_unit_vector(dim, 0))
    sqlite_session.commit()

    results = search_similar_tickets(
        sqlite_session,
        vector=_unit_vector(dim, 0),
        allowed_statuses=["Concluido"],
    )
    assert len(results) == 1
    assert results[0][0].chave_jira == "JDMSN1-C"


# ---------------------------------------------------------------------------
# sync_ticket_scope
# ---------------------------------------------------------------------------

def test_sync_ticket_scope_removes_stale(sqlite_session) -> None:
    dim = 8
    t1 = _make_ticket(sqlite_session, key="JDMSN1-KEEP")
    t2 = _make_ticket(sqlite_session, key="JDMSN1-STALE")
    sqlite_session.commit()

    upsert_embedding(sqlite_session, ticket_id=t1.id, vector=_unit_vector(dim, 0))
    upsert_embedding(sqlite_session, ticket_id=t2.id, vector=_unit_vector(dim, 1))
    sqlite_session.commit()

    sync_ticket_scope(sqlite_session, allowed_keys={"JDMSN1-KEEP"})
    sqlite_session.commit()

    assert get_ticket_by_key(sqlite_session, "JDMSN1-KEEP") is not None
    assert get_ticket_by_key(sqlite_session, "JDMSN1-STALE") is None


def test_sync_ticket_scope_empty_set_clears_all(sqlite_session) -> None:
    _make_ticket(sqlite_session, key="JDMSN1-ANY")
    sqlite_session.commit()

    sync_ticket_scope(sqlite_session, allowed_keys=set())
    sqlite_session.commit()

    assert get_recent_tickets(sqlite_session) == []
