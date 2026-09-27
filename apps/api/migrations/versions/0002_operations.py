"""add operational product tables

Revision ID: 0002_operations
Revises: 0001_initial
Create Date: 2026-09-27
"""

from alembic import op

import app.models  # noqa: F401
from app.database import Base

revision = "0002_operations"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(op.get_bind())


def downgrade() -> None:
    for table in ("webhook_deliveries", "webhooks", "notification_rules", "notification_providers", "status_page_components", "status_pages", "maintenance_windows"):
        op.drop_table(table)
