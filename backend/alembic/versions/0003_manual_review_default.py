"""default repository updates to manual review

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "repositories",
        "auto_create_pr",
        existing_type=sa.Boolean(),
        server_default=sa.false(),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "repositories",
        "auto_create_pr",
        existing_type=sa.Boolean(),
        server_default=sa.true(),
        existing_nullable=False,
    )
