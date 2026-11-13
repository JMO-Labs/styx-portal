"""users.staff_role: ADR-0026 support role synced from the IdP (styx-portal#239)

Revision ID: 0015_user_staff_role
Revises: 0014_access_review
Create Date: 2026-11-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0015_user_staff_role'
down_revision: Union[str, Sequence[str], None] = '0014_access_review'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    cols = [c['name'] for c in sa.inspect(op.get_bind()).get_columns('users')]
    if 'staff_role' not in cols:
        op.add_column('users', sa.Column('staff_role', sa.String(), nullable=False,
                                         server_default=''))


def downgrade() -> None:
    op.drop_column('users', 'staff_role')
