"""access review: group manager/kc ids + decisions table (styx-portal#137)

Revision ID: 0003_access_review
Revises: 0002_abuse_tables
Create Date: 2026-11-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0003_access_review'
down_revision: Union[str, Sequence[str], None] = '0002_abuse_tables'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    # Legacy SQLite startup may have created these via metadata.create_all already.
    cols = {c['name'] for c in insp.get_columns('groups')}
    with op.batch_alter_table('groups') as b:
        if 'manager_user_id' not in cols:
            b.add_column(sa.Column('manager_user_id', sa.String(), nullable=True))
            b.create_foreign_key('fk_groups_manager_user_id_users', 'users',
                                 ['manager_user_id'], ['id'])
        if 'kc_group_id' not in cols:
            b.add_column(sa.Column('kc_group_id', sa.String(), nullable=True))
    if 'access_review_decisions' in insp.get_table_names():
        return
    op.create_table(
        'access_review_decisions',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('group_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('quarter', sa.String(), nullable=False),
        sa.Column('decision', sa.String(), nullable=False),
        sa.Column('actor_id', sa.String(), nullable=False),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['group_id'], ['groups.id'],
                                name=op.f('fk_access_review_decisions_group_id_groups')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_access_review_decisions')),
    )
    for c in ('group_id', 'user_id', 'quarter'):
        op.create_index(op.f(f'ix_access_review_decisions_{c}'), 'access_review_decisions', [c])
