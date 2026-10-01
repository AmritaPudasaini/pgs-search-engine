"""team fit: embedding models (LaBSE default), crawl run config, media context

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-09-30 09:00:00

What the other groups' current branches need:

- ETL (`etl/workflow_saurav`) embeds with LaBSE (768 dimensions); the search branches
  used MiniLM (384). `page_embeddings` stops being fixed at 384: `embedding_models`
  registers each model and its size, a generated `dimensions` column plus a composite
  foreign key keep every vector consistent with its model, and each model gets its
  own partial HNSW index.
- The Temporal scraper records `seed_count`, `max_depth`, `max_pages`,
  `domain_capped` and a run `error`, and writes lower-case statuses.
- The image indexer (`feat/image-ingestion`) keeps each image's surrounding text.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from pgs_db import grants

# revision identifiers, used by Alembic.
revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, Sequence[str], None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MODELS = (
    ('sentence-transformers/LaBSE', 768, True,
     'Multilingual (109 languages incl. Nepali); the ETL default.'),
    ('sentence-transformers/all-MiniLM-L6-v2', 384, False,
     'English-only; what the search branches started with.'),
    ('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2', 384, False,
     'Multilingual, smaller and faster than LaBSE.'),
)


def _hnsw_name(model_name: str) -> str:
    # Frozen copy of pgs_db.repositories.silver.hnsw_index_name.
    import re
    slug = re.sub(r'[^a-z0-9]+', '_', model_name.lower()).strip('_')
    return f'ix_page_embeddings_hnsw_{slug}'[:63]


def upgrade() -> None:
    """Upgrade schema."""
    # --- embedding models ---------------------------------------------------
    op.create_table(
        'embedding_models',
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('dimensions', sa.SmallInteger(), nullable=False),
        sa.Column('is_default', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('dimensions BETWEEN 1 AND 2000', name=op.f('ck_embedding_models_dimensions_range')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_embedding_models')),
        sa.UniqueConstraint('name', name=op.f('uq_embedding_models_name')),
        sa.UniqueConstraint('name', 'dimensions', name='uq_embedding_models_name_dimensions'),
    )
    op.create_index(
        'uq_embedding_models_one_default', 'embedding_models', ['is_default'],
        unique=True, postgresql_where=sa.text('is_default'),
    )
    op.execute(
        'CREATE TRIGGER trg_embedding_models_updated_at BEFORE UPDATE ON embedding_models '
        'FOR EACH ROW EXECUTE FUNCTION pgs_set_updated_at()'
    )
    models = sa.table(
        'embedding_models',
        sa.column('name', sa.String), sa.column('dimensions', sa.SmallInteger),
        sa.column('is_default', sa.Boolean), sa.column('description', sa.Text),
    )
    op.bulk_insert(models, [
        {'name': n, 'dimensions': d, 'is_default': default, 'description': desc}
        for n, d, default, desc in _MODELS
    ])
    # Vectors already stored under other names keep working: register them as-is.
    op.execute(
        "INSERT INTO embedding_models (name, dimensions, description) "
        "SELECT DISTINCT model_name, vector_dims(embedding), 'registered by migration f6a7b8c9d0e1' "
        "FROM page_embeddings ON CONFLICT (name) DO NOTHING"
    )

    # --- page_embeddings: any registered size -------------------------------
    op.drop_index('ix_page_embeddings_embedding_hnsw', table_name='page_embeddings')
    op.alter_column('page_embeddings', 'embedding', type_=Vector(), existing_nullable=False)
    op.add_column(
        'page_embeddings',
        sa.Column('dimensions', sa.SmallInteger(),
                  sa.Computed('vector_dims(embedding)', persisted=True), nullable=False),
    )
    op.create_foreign_key(
        'fk_page_embeddings_model_name_embedding_models', 'page_embeddings', 'embedding_models',
        ['model_name', 'dimensions'], ['name', 'dimensions'],
    )
    op.create_index(
        'ix_page_embeddings_model_name_dimensions', 'page_embeddings', ['model_name', 'dimensions'],
    )
    for name, dims, _, _ in _MODELS:
        op.execute(
            f'CREATE INDEX {_hnsw_name(name)} ON page_embeddings '
            f'USING hnsw ((embedding::vector({dims})) vector_cosine_ops) '
            f"WHERE model_name = '{name}'"
        )

    # --- crawl_runs: the Temporal scraper's run record ----------------------
    op.add_column('crawl_runs', sa.Column('seed_count', sa.Integer(), nullable=True))
    op.add_column('crawl_runs', sa.Column('max_depth', sa.Integer(), nullable=True))
    op.add_column('crawl_runs', sa.Column('max_pages', sa.Integer(), nullable=True))
    op.add_column('crawl_runs', sa.Column('domain_capped_count', sa.Integer(), server_default='0', nullable=False))
    op.add_column('crawl_runs', sa.Column('error', sa.Text(), nullable=True))
    op.execute(
        """
        CREATE FUNCTION pgs_upper_crawl_run_status() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            NEW.status := upper(NEW.status);
            RETURN NEW;
        END
        $$
        """
    )
    # BEFORE triggers run before CHECK constraints, so "running" passes as RUNNING.
    op.execute(
        'CREATE TRIGGER trg_crawl_runs_upper_status BEFORE INSERT OR UPDATE OF status '
        'ON crawl_runs FOR EACH ROW EXECUTE FUNCTION pgs_upper_crawl_run_status()'
    )

    # --- page_media: surrounding text ---------------------------------------
    op.add_column('page_media', sa.Column('context_text', sa.Text(), nullable=True))

    grants.apply(op.execute)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('page_media', 'context_text')

    op.execute('DROP TRIGGER trg_crawl_runs_upper_status ON crawl_runs')
    op.execute('DROP FUNCTION pgs_upper_crawl_run_status()')
    for column in ('error', 'domain_capped_count', 'max_pages', 'max_depth', 'seed_count'):
        op.drop_column('crawl_runs', column)

    for name, _, _, _ in _MODELS:
        op.execute(f'DROP INDEX IF EXISTS {_hnsw_name(name)}')
    op.drop_index('ix_page_embeddings_model_name_dimensions', table_name='page_embeddings')
    op.drop_constraint('fk_page_embeddings_model_name_embedding_models', 'page_embeddings', type_='foreignkey')
    op.drop_column('page_embeddings', 'dimensions')
    # The old column held 384 numbers only: other sizes cannot survive the downgrade.
    op.execute('DELETE FROM page_embeddings WHERE vector_dims(embedding) <> 384')
    op.alter_column('page_embeddings', 'embedding', type_=Vector(384), existing_nullable=False)
    op.create_index(
        'ix_page_embeddings_embedding_hnsw', 'page_embeddings', ['embedding'],
        postgresql_using='hnsw', postgresql_ops={'embedding': 'vector_cosine_ops'},
    )
    op.execute('DROP TABLE embedding_models')
