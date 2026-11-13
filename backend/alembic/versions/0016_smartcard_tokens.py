"""smartcard_tokens: one-time relay tokens (styx-portal#219)

Revision ID: 0016_smartcard_tokens
Revises: 0015_group_idle_lock_minutes
Create Date: 2026-11-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0016_smartcard_tokens'
down_revision: Union[str, Sequence[str], None] = '0015_group_idle_lock_minutes'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if 'smartcard_tokens' in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        'smartcard_tokens',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('token_hash', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('instance_id', sa.String(), sa.ForeignKey('instances.id'), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('used_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_smartcard_tokens_token_hash', 'smartcard_tokens', ['token_hash'], unique=True)
    op.create_index('ix_smartcard_tokens_user_id', 'smartcard_tokens', ['user_id'])
    op.create_index('ix_smartcard_tokens_instance_id', 'smartcard_tokens', ['instance_id'])


def downgrade() -> None:
    op.drop_table('smartcard_tokens')
