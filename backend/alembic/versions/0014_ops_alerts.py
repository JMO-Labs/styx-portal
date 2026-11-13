"""ops_alert and ops_state tables (Alertmanager webhook)

Revision ID: 0014_ops_alerts
Revises: 0013_group_dlp
Create Date: 2026-11-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0014_ops_alerts'
down_revision: Union[str, Sequence[str], None] = '0013_group_dlp'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if 'ops_alert' not in tables:
        op.create_table(
            'ops_alert',
            sa.Column('fingerprint', sa.String(), nullable=False),
            sa.Column('status', sa.String(), nullable=False),
            sa.Column('labels', sa.JSON(), nullable=True),
            sa.Column('annotations', sa.JSON(), nullable=True),
            sa.Column('starts_at', sa.DateTime(), nullable=True),
            sa.Column('ends_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint('fingerprint', name=op.f('pk_ops_alert')),
        )
        op.create_index(op.f('ix_ops_alert_status'), 'ops_alert', ['status'])
    if 'ops_state' not in tables:
        op.create_table(
            'ops_state',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('last_watchdog_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id', name=op.f('pk_ops_state')),
        )


def downgrade() -> None:
    op.drop_table('ops_state')
    op.drop_index(op.f('ix_ops_alert_status'), table_name='ops_alert')
    op.drop_table('ops_alert')
