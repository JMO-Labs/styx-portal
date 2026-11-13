"""merge heads: ops_alerts (dev) + staff_role (enterprise)

Revision ID: 0017_merge_ops_enterprise
Revises: 0014_ops_alerts, 0016_user_staff_role
Create Date: 2026-11-13

"""
from typing import Sequence, Union

revision: str = '0017_merge_ops_enterprise'
down_revision: Union[str, Sequence[str], None] = ('0014_ops_alerts', '0016_user_staff_role')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
