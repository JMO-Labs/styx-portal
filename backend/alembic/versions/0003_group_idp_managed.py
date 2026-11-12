"""groups.idp_managed flag (styx-portal#133)

Revision ID: 0003_group_idp_managed
Revises: 0002_abuse_tables
Create Date: 2026-11-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0003_group_idp_managed'
down_revision: Union[str, Sequence[str], None] = '0002_abuse_tables'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    cols = [c['name'] for c in sa.inspect(op.get_bind()).get_columns('groups')]
    if 'idp_managed' in cols:  # legacy SQLite create_all already built it
        return
    op.add_column('groups', sa.Column('idp_managed', sa.Boolean(), nullable=False,
                                      server_default=sa.false()))


def downgrade() -> None:
    op.drop_column('groups', 'idp_managed')
