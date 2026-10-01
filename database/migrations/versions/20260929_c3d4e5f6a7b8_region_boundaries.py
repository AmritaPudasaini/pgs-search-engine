"""region boundaries (PostGIS) and local body ward counts

Revision ID: c3d4e5f6a7b8
Revises: b7c1d2e3f4a5
Create Date: 2026-09-29 21:10:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geometry

# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b7c1d2e3f4a5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ('provinces', 'districts', 'local_bodies')


def upgrade() -> None:
    """Upgrade schema."""
    # The image (./Dockerfile) ships PostGIS; it only has to be enabled.
    op.execute('CREATE EXTENSION IF NOT EXISTS postgis')
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column(
                'boundary',
                Geometry('MULTIPOLYGON', srid=4326, spatial_index=False),
                nullable=True,
            ),
        )
        op.create_index(f'ix_{table}_boundary', table, ['boundary'], postgresql_using='gist')
    op.add_column('local_bodies', sa.Column('ward_count', sa.Integer(), nullable=True))
    op.create_check_constraint(
        op.f('ck_local_bodies_ward_count_positive'),
        'local_bodies',
        'ward_count IS NULL OR ward_count > 0',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f('ck_local_bodies_ward_count_positive'), 'local_bodies', type_='check')
    op.drop_column('local_bodies', 'ward_count')
    for table in reversed(_TABLES):
        op.drop_index(f'ix_{table}_boundary', table_name=table)
        op.drop_column(table, 'boundary')
    # PostGIS stays enabled: dropping an extension other objects may use is not ours to do.
