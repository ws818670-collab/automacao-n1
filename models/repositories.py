from datetime import datetime

import numpy as np
from sqlalchemy import Select, delete, select
from sqlalchemy.orm import Session, joinedload

from models.entities import Analise, Embedding, Ticket


def upsert_ticket(
    db: Session,
    *,
    chave_jira: str,
    resumo: str,
    descricao: str,
    comentarios: str,
    produto: str,
    status: str,
    data_criacao: datetime | None,
    data_fechamento: datetime | None,
) -> Ticket:
    ticket = db.scalar(select(Ticket).where(Ticket.chave_jira == chave_jira))
    if ticket is None:
        ticket = Ticket(
            chave_jira=chave_jira,
            resumo=resumo,
            descricao=descricao,
            comentarios=comentarios,
            produto=produto,
            status=status,
            data_criacao=data_criacao or datetime.utcnow(),
            data_fechamento=data_fechamento,
        )
        db.add(ticket)
    else:
        ticket.resumo = resumo
        ticket.descricao = descricao
        ticket.comentarios = comentarios
        ticket.produto = produto
        ticket.status = status
        ticket.data_criacao = data_criacao or ticket.data_criacao
        ticket.data_fechamento = data_fechamento

    db.flush()
    return ticket


def upsert_embedding(db: Session, *, ticket_id: int, vector: list[float]) -> Embedding:
    embedding = db.get(Embedding, ticket_id)
    if embedding is None:
        embedding = Embedding(ticket_id=ticket_id, embedding_vector=vector)
        db.add(embedding)
    else:
        embedding.embedding_vector = vector

    db.flush()
    return embedding


def upsert_analise(
    db: Session,
    *,
    ticket_id: int,
    problema: str,
    solucao: str,
    categoria: str,
    confianca: float,
) -> Analise:
    analise = db.get(Analise, ticket_id)
    if analise is None:
        analise = Analise(
            ticket_id=ticket_id,
            problema=problema,
            solucao=solucao,
            categoria=categoria,
            confianca=confianca,
        )
        db.add(analise)
    else:
        analise.problema = problema
        analise.solucao = solucao
        analise.categoria = categoria
        analise.confianca = confianca

    db.flush()
    return analise


def get_ticket_by_key(db: Session, key: str) -> Ticket | None:
    stmt: Select[tuple[Ticket]] = select(Ticket).where(Ticket.chave_jira == key)
    return db.scalar(stmt)


def get_recent_tickets(db: Session, limit: int = 200) -> list[Ticket]:
    from sqlalchemy import desc

    stmt = (
        select(Ticket)
        .options(joinedload(Ticket.analise), joinedload(Ticket.embedding))
        .order_by(desc(Ticket.data_criacao))
        .limit(limit)
    )
    return list(db.scalars(stmt).unique().all())


def search_similar_tickets(
    db: Session,
    vector: list[float],
    top_k: int = 5,
    exclude_ticket_key: str | None = None,
    allowed_statuses: list[str] | None = None,
) -> list[tuple[Ticket, float]]:
    """
    Busca os tickets mais similares usando distância coseno calculada em Python.
    Funciona com SQLite e PostgreSQL sem extensões de servidor.
    """
    stmt = (
        select(Ticket)
        .join(Embedding, Embedding.ticket_id == Ticket.id)
        .options(joinedload(Ticket.analise))
    )
    if exclude_ticket_key:
        stmt = stmt.where(Ticket.chave_jira != exclude_ticket_key)
    if allowed_statuses:
        stmt = stmt.where(Ticket.status.in_(allowed_statuses))

    tickets = list(db.scalars(stmt).unique().all())
    if not tickets:
        return []

    ticket_ids = [t.id for t in tickets]
    emb_rows = db.execute(
        select(Embedding.ticket_id, Embedding.embedding_vector).where(
            Embedding.ticket_id.in_(ticket_ids)
        )
    ).all()
    emb_map: dict[int, list[float]] = {
        row.ticket_id: row.embedding_vector
        for row in emb_rows
        if row.embedding_vector is not None
    }

    query_vec = np.array(vector, dtype=np.float32)
    query_norm = float(np.linalg.norm(query_vec))

    scored: list[tuple[Ticket, float]] = []
    for ticket in tickets:
        emb_vector = emb_map.get(ticket.id)
        if emb_vector is None:
            continue
        distance = _cosine_distance(query_vec, query_norm, emb_vector)
        scored.append((ticket, distance))

    scored.sort(key=lambda pair: pair[1])
    return scored[:top_k]


def _cosine_distance(
    query_vec: np.ndarray,
    query_norm: float,
    candidate: list[float],
) -> float:
    cand_vec = np.array(candidate, dtype=np.float32)
    cand_norm = float(np.linalg.norm(cand_vec))
    if query_norm == 0.0 or cand_norm == 0.0:
        return 1.0
    similarity = float(np.dot(query_vec, cand_vec)) / (query_norm * cand_norm)
    return float(1.0 - similarity)


def sync_ticket_scope(db: Session, allowed_keys: set[str]) -> None:
    if not allowed_keys:
        db.execute(delete(Analise))
        db.execute(delete(Embedding))
        db.execute(delete(Ticket))
        db.flush()
        return

    stale_ids = list(
        db.scalars(select(Ticket.id).where(Ticket.chave_jira.not_in(allowed_keys))).all()
    )
    if not stale_ids:
        return

    db.execute(delete(Analise).where(Analise.ticket_id.in_(stale_ids)))
    db.execute(delete(Embedding).where(Embedding.ticket_id.in_(stale_ids)))
    db.execute(delete(Ticket).where(Ticket.id.in_(stale_ids)))
    db.flush()
