"""user lifecycle columns: end_date, disabled_at, disabled_reason, reviewed_at (styx-portal#115)

Revision ID: 0003_user_lifecycle
Revises: 0002_abuse_tables
Create Date: 2026-11-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0003_user_lifecycle'
down_revision: Union[str, Sequence[str], None] = '0002_abuse_tables'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TS = sa.DateTime(timezone=True)
_COLS = [('end_date', _TS), ('disabled_at', _TS),
         ('disabled_reason', sa.String()), ('reviewed_at', _TS)]


def upgrade() -> None:
    have = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('users')}
    for name, typ in _COLS:
        if name not in have:  # legacy create_all may already have them
            op.add_column('users', sa.Column(name, typ, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('users') as b:
        for name, _ in _COLS:
            b.drop_column(name)
