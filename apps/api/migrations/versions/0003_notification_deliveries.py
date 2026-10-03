"""add notification delivery logs

Revision ID: 0003_notification_deliveries
Revises: 0002_operations
Create Date: 2026-10-04
"""

from alembic import op

import app.models  # noqa: F401
from app.database import Base

revision = "0003_notification_deliveries"
down_revision = "0002_operations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(op.get_bind())


def downgrade() -> None:
    op.drop_table("notification_deliveries")
