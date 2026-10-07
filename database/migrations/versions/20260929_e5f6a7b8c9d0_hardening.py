"""hardening: updated_at triggers, indexed foreign keys, service roles

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-09-29 22:00:00

"""
from typing import Sequence, Union

from alembic import op

from pgs_db import grants

# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Every table with an updated_at column, as of this migration. A later migration that
# adds a table must also add the trigger (tests/test_hardening.py checks).
_TABLES = (
    'crawl_runs', 'crawled_documents', 'stored_files',
    'provinces', 'districts', 'local_bodies', 'domains', 'region_links',
    'pages', 'page_geo_tags', 'page_contacts', 'page_sources', 'page_media',
    'entities', 'page_entities', 'page_embeddings', 'quarantined_files',
    'domain_stats', 'geo_content_stats', 'page_scores',
    'search_queries', 'search_clicks', 'relevance_judgments',
    'admin_users', 'error_logs',
)

# The Go scraper and Spark write with plain SQL, so the ORM's onupdate never runs for
# them. The trigger keeps updated_at honest for every writer, and leaves an explicit
# new value alone (the claim queues set it on purpose).
_FUNCTION = """
CREATE OR REPLACE FUNCTION pgs_set_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.updated_at IS NOT DISTINCT FROM OLD.updated_at THEN
        NEW.updated_at := now();
    END IF;
    RETURN NEW;
END
$$
"""

_FK_INDEXES = (
    ('ix_error_logs_crawl_run_id', 'crawl_run_id'),
    ('ix_error_logs_crawled_document_id', 'crawled_document_id'),
    ('ix_error_logs_page_id', 'page_id'),
)


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(_FUNCTION)
    for table in _TABLES:
        op.execute(
            f'CREATE TRIGGER trg_{table}_updated_at BEFORE UPDATE ON {table} '
            f'FOR EACH ROW EXECUTE FUNCTION pgs_set_updated_at()'
        )
    # SET NULL foreign keys: without an index, deleting a page scans all of error_logs.
    for name, column in _FK_INDEXES:
        op.create_index(name, 'error_logs', [column])
    grants.apply(op.execute)


def downgrade() -> None:
    """Downgrade schema."""
    grants.revoke_all(op.execute)
    for name, _ in _FK_INDEXES:
        op.drop_index(name, table_name='error_logs')
    for table in _TABLES:
        op.execute(f'DROP TRIGGER trg_{table}_updated_at ON {table}')
    op.execute('DROP FUNCTION pgs_set_updated_at()')
