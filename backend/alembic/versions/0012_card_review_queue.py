"""card_review_queue table (styx-portal#122)

Revision ID: 0012_card_review_queue
Revises: 0011_setup_tokens
Create Date: 2026-11-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0012_card_review_queue'
down_revision: Union[str, Sequence[str], None] = '0011_setup_tokens'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if 'card_review_queue' in sa.inspect(op.get_bind()).get_table_names():
        return  # legacy create_all may already have it
    op.create_table(
        'card_review_queue',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('kc_user_id', sa.String(), nullable=False),
        sa.Column('card_type', sa.String(), nullable=False),
        sa.Column('claims', sa.JSON(), nullable=True),
        sa.Column('reason', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('resolved_by', sa.String(), nullable=True),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_card_review_queue')),
    )
    op.create_index(op.f('ix_card_review_queue_kc_user_id'), 'card_review_queue',
                    ['kc_user_id'])


def downgrade() -> None:
    op.drop_table('card_review_queue')
