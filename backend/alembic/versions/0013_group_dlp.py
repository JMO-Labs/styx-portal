"""groups DLP policy columns (styx-portal#226)

Revision ID: 0013_group_dlp
Revises: 0012_instance_recycle_deadline
Create Date: 2026-11-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0013_group_dlp'
down_revision: Union[str, Sequence[str], None] = '0012_instance_recycle_deadline'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_BOOLS = ['clipboard_in', 'clipboard_out', 'upload', 'download', 'printing', 'watermark']


def upgrade() -> None:
    cols = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('groups')}
    for b in _BOOLS:
        if f'dlp_{b}' not in cols:
            op.add_column('groups', sa.Column(f'dlp_{b}', sa.Boolean(), nullable=True))
    if 'dlp_approval_ref' not in cols:
        op.add_column('groups', sa.Column('dlp_approval_ref', sa.String(), nullable=True))
    if 'dlp_approved_at' not in cols:
        op.add_column('groups', sa.Column('dlp_approved_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    for c in ['dlp_approved_at', 'dlp_approval_ref'] + [f'dlp_{b}' for b in reversed(_BOOLS)]:
        op.drop_column('groups', c)
