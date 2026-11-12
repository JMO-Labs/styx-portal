"""approved_requests table for the provisioning webhook (styx-portal#120)

Revision ID: 0009_approved_requests
Revises: 0008_service_thumbnails
Create Date: 2026-11-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0009_approved_requests'
down_revision: Union[str, Sequence[str], None] = '0008_service_thumbnails'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if 'approved_requests' in sa.inspect(op.get_bind()).get_table_names():
        return  # legacy create_all may already have it
    op.create_table(
        'approved_requests',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('idempotency_key', sa.String(), nullable=False),
        sa.Column('body_hash', sa.String(), nullable=False),
        sa.Column('approval_id', sa.String(), nullable=False),
        sa.Column('external_id', sa.String(), nullable=False),
        sa.Column('approver_email', sa.String(), nullable=False),
        sa.Column('groups', sa.JSON(), nullable=True),
        sa.Column('card_type', sa.String(), nullable=False),
        sa.Column('person_type', sa.String(), nullable=False),
        sa.Column('end_date', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('subject', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_approved_requests')),
    )
    for col in ('idempotency_key', 'approval_id', 'external_id'):
        op.create_index(op.f(f'ix_approved_requests_{col}'), 'approved_requests', [col],
                        unique=True)


def downgrade() -> None:
    op.drop_table('approved_requests')
