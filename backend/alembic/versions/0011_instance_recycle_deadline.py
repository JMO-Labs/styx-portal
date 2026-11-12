"""instances.recycle_deadline: critical-CVE stop deadline (styx-portal#148)

Revision ID: 0011_instance_recycle_deadline
Revises: 0010_group_idp_managed
Create Date: 2026-11-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0011_instance_recycle_deadline'
down_revision: Union[str, Sequence[str], None] = '0010_group_idp_managed'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    cols = [c['name'] for c in sa.inspect(op.get_bind()).get_columns('instances')]
    if 'recycle_deadline' not in cols:
        op.add_column('instances', sa.Column('recycle_deadline', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('instances', 'recycle_deadline')
