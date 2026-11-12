"""instances.image_digest: digest pinned at launch (styx-portal#147)

Revision ID: 0005_instance_image_digest
Revises: 0004_posix_uids
Create Date: 2026-11-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0005_instance_image_digest'
down_revision: Union[str, Sequence[str], None] = '0004_posix_uids'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    cols = [c['name'] for c in sa.inspect(op.get_bind()).get_columns('instances')]
    if 'image_digest' not in cols:
        op.add_column('instances', sa.Column('image_digest', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('instances', 'image_digest')
