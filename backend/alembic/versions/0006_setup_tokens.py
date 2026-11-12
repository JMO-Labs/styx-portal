"""setup_tokens: DB-backed first-run setup code (styx-portal#86)

Revision ID: 0006_setup_tokens
Revises: 0005_instance_image_digest
Create Date: 2026-11-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0006_setup_tokens'
down_revision: Union[str, Sequence[str], None] = '0005_instance_image_digest'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Legacy SQLite startup may already have created it via metadata.create_all.
    if 'setup_tokens' in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        'setup_tokens',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('token', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_setup_tokens')),
    )


def downgrade() -> None:
    op.drop_table('setup_tokens')
