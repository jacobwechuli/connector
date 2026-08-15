"""record visible workflow events

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("repository_id", sa.Integer(), sa.ForeignKey("repositories.id"), nullable=True),
        sa.Column("commit_id", sa.Integer(), sa.ForeignKey("commits.id"), nullable=True),
        sa.Column("update_id", sa.Integer(), sa.ForeignKey("portfolio_updates.id"), nullable=True),
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("workflow_events")
