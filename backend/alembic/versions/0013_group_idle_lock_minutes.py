"""groups.idle_lock_minutes: per-group idle-lock timeout (styx-portal#244)

Revision ID: 0013_group_idle_lock_minutes
Revises: 0012_instance_recycle_deadline
Create Date: 2026-11-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0013_group_idle_lock_minutes'
down_revision: Union[str, Sequence[str], None] = '0012_instance_recycle_deadline'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    cols = [c['name'] for c in sa.inspect(op.get_bind()).get_columns('groups')]
    if 'idle_lock_minutes' not in cols:
        op.add_column('groups', sa.Column('idle_lock_minutes', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('groups', 'idle_lock_minutes')
