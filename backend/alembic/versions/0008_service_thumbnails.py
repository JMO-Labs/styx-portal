"""service_thumbnails: shared thumbnail storage, bytea on PG / BLOB on SQLite (styx-portal#99)

Revision ID: 0008_service_thumbnails
Revises: 0007_group_tier
Create Date: 2026-11-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0008_service_thumbnails'
down_revision: Union[str, Sequence[str], None] = '0007_group_tier'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if 'service_thumbnails' in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        'service_thumbnails',
        sa.Column('service_id', sa.String(), sa.ForeignKey('proxied_services.id', ondelete='CASCADE'),
                  primary_key=True),
        sa.Column('data', sa.LargeBinary(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('service_thumbnails')
