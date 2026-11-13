"""announcements table (styx-portal#299)

Revision ID: 0017_announcements
Revises: 0016_user_staff_role
Create Date: 2026-11-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0017_announcements'
down_revision: Union[str, Sequence[str], None] = '0016_user_staff_role'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if 'announcements' in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        'announcements',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('title', sa.String(120), nullable=False),
        sa.Column('body', sa.String(2000), nullable=False),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('starts_at', sa.DateTime(), nullable=False),
        sa.Column('ends_at', sa.DateTime(), nullable=True),
        sa.Column('created_by', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'],
                                name=op.f('fk_announcements_created_by_users')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_announcements')),
    )


def downgrade() -> None:
    op.drop_table('announcements')
