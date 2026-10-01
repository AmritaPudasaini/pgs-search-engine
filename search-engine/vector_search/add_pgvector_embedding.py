"""add pgvector embedding column and HNSW index

Place in database/migrations/versions/ and set down_revision to your current head.
"""
from alembic import op

revision = "add_pgvector_embedding"
# TODO: keep this unset while the file lives outside database/migrations/versions.
# Before installing as a production Alembic migration, set this to the current
# database migration head.
down_revision = None
branch_labels = None
depends_on = None

EMBEDDING_DIM = 384  # must match EMBEDDING_DIM in vector_search/config.py


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        "ALTER TABLE crawled_documents "
        f"ADD COLUMN IF NOT EXISTS embedding vector({EMBEDDING_DIM})"
    )
    # Build after the backfill for large tables if you want a faster initial load.
    op.execute(
        "CREATE INDEX IF NOT EXISTS crawled_documents_embedding_hnsw_idx "
        "ON crawled_documents USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS crawled_documents_embedding_hnsw_idx")
    op.execute("ALTER TABLE crawled_documents DROP COLUMN IF EXISTS embedding")
