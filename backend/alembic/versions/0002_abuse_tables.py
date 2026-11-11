"""shared abuse state: auth_fail_events, auth_blocks, rate_counters (styx-portal#74)

Revision ID: 0002_abuse_tables
Revises: 0001_baseline
Create Date: 2026-11-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0002_abuse_tables'
down_revision: Union[str, Sequence[str], None] = '0001_baseline'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        'auth_fail_events',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'),
                  autoincrement=True, nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('key', sa.String(), nullable=False),
        sa.Column('username', sa.String(), nullable=True),
        sa.Column('at', _TS, nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_auth_fail_events')),
    )
    op.create_index('ix_auth_fail_events_kind_key_at', 'auth_fail_events',
                    ['kind', 'key', 'at'])
    op.create_index(op.f('ix_auth_fail_events_username'), 'auth_fail_events', ['username'])
    op.create_table(
        'auth_blocks',
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('key', sa.String(), nullable=False),
        sa.Column('username', sa.String(), nullable=True),
        sa.Column('until', _TS, nullable=False),
        sa.PrimaryKeyConstraint('kind', 'key', name=op.f('pk_auth_blocks')),
    )
    op.create_index(op.f('ix_auth_blocks_username'), 'auth_blocks', ['username'])
    op.create_index(op.f('ix_auth_blocks_until'), 'auth_blocks', ['until'])
    op.create_table(
        'rate_counters',
        sa.Column('key', sa.String(), nullable=False),
        sa.Column('window_start', _TS, nullable=False),
        sa.Column('count', sa.Integer(), nullable=False),
        sa.Column('expires_at', _TS, nullable=False),
        sa.PrimaryKeyConstraint('key', 'window_start', name=op.f('pk_rate_counters')),
        postgresql_with={'fillfactor': '70'},
    )
    op.create_index(op.f('ix_rate_counters_expires_at'), 'rate_counters', ['expires_at'])


def downgrade() -> None:
    op.drop_table('rate_counters')
    op.drop_table('auth_blocks')
    op.drop_table('auth_fail_events')
