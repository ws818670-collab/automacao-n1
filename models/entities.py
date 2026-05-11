from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.database import Base
from models.vector_type import VectorType
from utils.config import get_settings

settings = get_settings()


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    chave_jira: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    resumo: Mapped[str | None] = mapped_column(Text, nullable=True)
    descricao: Mapped[str | None] = mapped_column(Text, nullable=True)
    comentarios: Mapped[str | None] = mapped_column(Text, default="", nullable=True)
    produto: Mapped[str | None] = mapped_column(String(128), default="", nullable=True)
    status: Mapped[str | None] = mapped_column(String(64), default="", nullable=True)
    data_criacao: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.utcnow, nullable=True)
    data_fechamento: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    embedding: Mapped["Embedding"] = relationship("Embedding", back_populates="ticket", uselist=False)
    analise: Mapped["Analise"] = relationship("Analise", back_populates="ticket", uselist=False)


class Embedding(Base):
    __tablename__ = "embeddings"

    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), primary_key=True)
    embedding_vector: Mapped[list[float]] = mapped_column(VectorType(settings.embedding_dimension))

    ticket: Mapped[Ticket] = relationship("Ticket", back_populates="embedding")


class Analise(Base):
    __tablename__ = "analises"

    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), primary_key=True)
    problema: Mapped[str | None] = mapped_column(Text, nullable=True)
    solucao: Mapped[str | None] = mapped_column(Text, nullable=True)
    categoria: Mapped[str] = mapped_column(String(128), default="geral")
    confianca: Mapped[float | None] = mapped_column(Float, default=0.5, nullable=True)

    ticket: Mapped[Ticket] = relationship("Ticket", back_populates="analise")
