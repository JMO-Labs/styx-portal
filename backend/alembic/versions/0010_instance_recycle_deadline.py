"""instances.recycle_deadline: critical-CVE stop deadline (styx-portal#148)

Revision ID: 0010_instance_recycle_deadline
Revises: 0009_approved_requests
Create Date: 2026-11-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0010_instance_recycle_deadline'
down_revision: Union[str, Sequence[str], None] = '0009_approved_requests'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    cols = [c['name'] for c in sa.inspect(op.get_bind()).get_columns('instances')]
    if 'recycle_deadline' not in cols:
        op.add_column('instances', sa.Column('recycle_deadline', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('instances', 'recycle_deadline')
