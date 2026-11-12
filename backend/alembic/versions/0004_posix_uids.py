"""immutable POSIX UID allocations (styx-portal#117)

Revision ID: 0004_posix_uids
Revises: 0003_user_lifecycle
Create Date: 2026-11-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0004_posix_uids'
down_revision: Union[str, Sequence[str], None] = '0003_user_lifecycle'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if 'posix_uids' in sa.inspect(op.get_bind()).get_table_names():
        return  # legacy SQLite create_all already built it
    op.create_table(
        'posix_uids',
        sa.Column('uid', sa.Integer(), autoincrement=False, nullable=False),
        sa.Column('user_key', sa.String(), nullable=False),
        sa.Column('allocated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('uid', name=op.f('pk_posix_uids')),
        sa.UniqueConstraint('user_key', name=op.f('uq_posix_uids_user_key')),
    )


def downgrade() -> None:
    op.drop_table('posix_uids')
