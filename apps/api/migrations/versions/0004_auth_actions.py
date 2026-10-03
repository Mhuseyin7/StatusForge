"""add email and password recovery tokens

Revision ID: 0004_auth_actions
Revises: 0003_notification_deliveries
Create Date: 2026-10-04
"""

from alembic import op

import app.models  # noqa: F401
from app.database import Base

revision = "0004_auth_actions"
down_revision = "0003_notification_deliveries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(op.get_bind())


def downgrade() -> None:
    op.drop_table("auth_action_tokens")
