"""group CPU-tier overrides: tier_resolution/fps/hidpi/cpu/memory (styx-portal#151)

Revision ID: 0007_group_tier
Revises: 0006_group_egress_mode
Create Date: 2026-11-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0007_group_tier'
down_revision: Union[str, Sequence[str], None] = '0006_group_egress_mode'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLS = [('tier_resolution', sa.String()), ('tier_fps', sa.Integer()),
         ('tier_hidpi', sa.Boolean()), ('tier_cpu', sa.String()),
         ('tier_memory', sa.String())]


def upgrade() -> None:
    have = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('groups')}
    for name, typ in _COLS:
        if name not in have:
            op.add_column('groups', sa.Column(name, typ, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('groups') as b:
        for name, _ in _COLS:
            b.drop_column(name)
