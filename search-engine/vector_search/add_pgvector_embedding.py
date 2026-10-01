"""add pgvector embedding column and HNSW index

Place in database/migrations/versions/ and set down_revision to your current head.
"""
from alembic import op

revision = "add_pgvector_embedding"
down_revision = None  # <-- TODO: set to your latest revision id
branch_labels = None
depends_on = None

EMBEDDING_DIM = 384  # must match EMBEDDING_DIM in vector_search/config.py


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(f"ALTER TABLE documents ADD COLUMN IF NOT EXISTS embedding vector({EMBEDDING_DIM})")
    # Build after the backfill for large tables if you want a faster initial load.
    op.execute(
        "CREATE INDEX IF NOT EXISTS documents_embedding_hnsw_idx "
        "ON documents USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS documents_embedding_hnsw_idx")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS embedding")