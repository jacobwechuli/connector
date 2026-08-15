"""initial schema – explicit DDL

Revision ID: 0001
Revises:
Create Date: 2026-08-14
"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "repositories",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("owner", sa.String(120), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("portfolio_project_id", sa.String(160), nullable=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("auto_create_pr", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("auto_merge", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("is_portfolio", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_repo_owner_name", "repositories", ["owner", "name"], unique=True)

    op.create_table(
        "webhook_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("delivery_id", sa.String(128), nullable=False, unique=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("received_at", sa.DateTime, nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
    )

    op.create_table(
        "commits",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("repository_id", sa.Integer, sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column("sha", sa.String(64), nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("processed_at", sa.DateTime, nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("error_message", sa.Text, nullable=True),
    )
    op.create_index("ix_commit_repo_sha", "commits", ["repository_id", "sha"], unique=True)

    op.create_table(
        "analyses",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("commit_id", sa.Integer, sa.ForeignKey("commits.id"), nullable=False, unique=True),
        sa.Column("portfolio_worthy", sa.Boolean, nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("significance", sa.String(20), nullable=False),
        sa.Column("reasoning_summary", sa.Text, nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("raw_result", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "portfolio_updates",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("commit_id", sa.Integer, sa.ForeignKey("commits.id"), nullable=False, unique=True),
        sa.Column("operations", sa.JSON, nullable=False),
        sa.Column("diff", sa.Text, nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("validation_result", sa.JSON, nullable=False),
        sa.Column("branch", sa.String(255), nullable=True),
        sa.Column("pr_number", sa.Integer, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("portfolio_updates")
    op.drop_table("analyses")
    op.drop_index("ix_commit_repo_sha", "commits")
    op.drop_table("commits")
    op.drop_table("webhook_events")
    op.drop_index("ix_repo_owner_name", "repositories")
    op.drop_table("repositories")
