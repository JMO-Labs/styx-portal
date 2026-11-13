"""merge heads: ops_alerts (dev) + access_review (enterprise)

Revision ID: 0015_merge_ops_access_review
Revises: 0014_ops_alerts, 0014_access_review
Create Date: 2026-11-13

"""
from typing import Sequence, Union

revision: str = '0015_merge_ops_access_review'
down_revision: Union[str, Sequence[str], None] = ('0014_ops_alerts', '0014_access_review')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
