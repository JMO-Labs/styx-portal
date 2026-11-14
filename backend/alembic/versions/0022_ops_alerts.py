"""ops_alert + ops_state: Alertmanager webhook storage (dev #157, synced via styx-portal#343)

Revision ID: 0022_ops_alerts
Revises: 0021_card_review_queue
Create Date: 2026-11-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

revision: str = '0022_ops_alerts'
down_revision: Union[str, Sequence[str], None] = '0021_card_review_queue'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if 'ops_alert' not in existing:
        op.create_table(
            'ops_alert',
            sa.Column('fingerprint', sqlmodel.AutoString(), nullable=False),
            sa.Column('status', sqlmodel.AutoString(), nullable=False),
            sa.Column('labels', sa.JSON(), nullable=True),
            sa.Column('annotations', sa.JSON(), nullable=True),
            sa.Column('starts_at', sa.DateTime(), nullable=True),
            sa.Column('ends_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint('fingerprint', name=op.f('pk_ops_alert')),
        )
        op.create_index(op.f('ix_ops_alert_status'), 'ops_alert', ['status'])
    if 'ops_state' not in existing:
        op.create_table(
            'ops_state',
            sa.Column('id', sa.Integer(), autoincrement=False, nullable=False),
            sa.Column('last_watchdog_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id', name=op.f('pk_ops_state')),
        )


def downgrade() -> None:
    op.drop_table('ops_state')
    op.drop_index(op.f('ix_ops_alert_status'), table_name='ops_alert')
    op.drop_table('ops_alert')
