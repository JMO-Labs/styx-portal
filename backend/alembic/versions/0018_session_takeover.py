"""session_takeovers: ADR-0060 staff takeover records (styx-portal#242)

Revision ID: 0018_session_takeover
Revises: 0017_announcements
Create Date: 2026-11-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0018_session_takeover'
down_revision: Union[str, Sequence[str], None] = '0017_announcements'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if 'session_takeovers' in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        'session_takeovers',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('instance_id', sa.String(), nullable=False),
        sa.Column('actor_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=True),
        sa.Column('mode', sa.String(), nullable=False),
        sa.Column('reason', sa.String(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('ended_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id', name='pk_session_takeovers'),
    )
    op.create_index('ix_session_takeovers_instance_id', 'session_takeovers', ['instance_id'])
    where = sa.text('ended_at IS NULL')
    op.create_index('uq_session_takeovers_active', 'session_takeovers', ['instance_id'],
                    unique=True, sqlite_where=where, postgresql_where=where)


def downgrade() -> None:
    op.drop_table('session_takeovers')
