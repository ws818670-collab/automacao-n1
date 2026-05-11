"""initial_schema

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-03-31 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))

    op.create_table(
        "tickets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chave_jira", sa.String(length=64), nullable=False),
        sa.Column("resumo", sa.Text(), nullable=True),
        sa.Column("descricao", sa.Text(), nullable=True),
        sa.Column("comentarios", sa.Text(), nullable=True),
        sa.Column("produto", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=True),
        sa.Column("data_criacao", sa.DateTime(), nullable=True),
        sa.Column("data_fechamento", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_tickets_id", "tickets", ["id"], unique=False)
    op.create_index("ix_tickets_chave_jira", "tickets", ["chave_jira"], unique=True)

    op.create_table(
        "embeddings",
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        # Vector stored as JSON text; compatible with SQLite and PostgreSQL.
        sa.Column("embedding_vector", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("ticket_id"),
    )

    op.create_table(
        "analises",
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("problema", sa.Text(), nullable=True),
        sa.Column("solucao", sa.Text(), nullable=True),
        sa.Column("categoria", sa.String(length=128), nullable=False),
        sa.Column("confianca", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("ticket_id"),
    )


def downgrade() -> None:
    op.drop_table("analises")
    op.drop_table("embeddings")
    op.drop_index("ix_tickets_chave_jira", table_name="tickets")
    op.drop_index("ix_tickets_id", table_name="tickets")
    op.drop_table("tickets")
