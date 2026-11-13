"""notices table + user_profiles.last_used_at (styx-portal#266)

Revision ID: 0013_notices_profile_last_used
Revises: 0012_instance_recycle_deadline
Create Date: 2026-11-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0013_notices_profile_last_used'
down_revision: Union[str, Sequence[str], None] = '0012_instance_recycle_deadline'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if 'notices' not in insp.get_table_names():
        op.create_table(
            'notices',
            sa.Column('id', sa.String(), nullable=False),
            sa.Column('user_id', sa.String(), nullable=False),
            sa.Column('kind', sa.String(), nullable=False),
            sa.Column('key', sa.String(), nullable=False),
            sa.Column('message', sa.String(), nullable=False),
            sa.Column('due_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('dismissed_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_notices_user_id_users')),
            sa.PrimaryKeyConstraint('id', name=op.f('pk_notices')),
            sa.UniqueConstraint('user_id', 'kind', 'key', name='uq_notice_user_kind_key'),
        )
        op.create_index(op.f('ix_notices_user_id'), 'notices', ['user_id'])
    cols = [c['name'] for c in insp.get_columns('user_profiles')]
    if 'last_used_at' not in cols:
        op.add_column('user_profiles', sa.Column('last_used_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('user_profiles', 'last_used_at')
    op.drop_index(op.f('ix_notices_user_id'), table_name='notices')
    op.drop_table('notices')
