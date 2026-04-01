"""add_ivfflat_index

Revision ID: 002_add_ivfflat_index
Revises: 001_initial_schema
Create Date: 2026-03-31 00:10:00
"""

from __future__ import annotations

from alembic import op

revision = "002_add_ivfflat_index"
down_revision = "001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_embeddings_embedding_vector_ivfflat "
        "ON embeddings USING ivfflat (embedding_vector vector_cosine_ops) WITH (lists = 100)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("DROP INDEX IF EXISTS ix_embeddings_embedding_vector_ivfflat")