"""groups.egress_mode: category | allowlist (styx-portal#162)

Revision ID: 0003_group_egress_mode
Revises: 0002_abuse_tables
Create Date: 2026-11-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0003_group_egress_mode'
down_revision: Union[str, Sequence[str], None] = '0002_abuse_tables'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Legacy SQLite startup may already have added the column via db_migrate.
    cols = [c['name'] for c in sa.inspect(op.get_bind()).get_columns('groups')]
    if 'egress_mode' in cols:
        return
    op.add_column('groups', sa.Column('egress_mode', sa.String(), nullable=False,
                                      server_default='category'))


def downgrade() -> None:
    with op.batch_alter_table('groups') as b:
        b.drop_column('egress_mode')
