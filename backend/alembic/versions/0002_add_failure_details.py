"""add failure details for commits and updates

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "error_message" not in {column["name"] for column in inspector.get_columns("commits")}:
        op.add_column("commits", sa.Column("error_message", sa.Text(), nullable=True))
    if "error_message" not in {
        column["name"] for column in inspector.get_columns("portfolio_updates")
    }:
        op.add_column("portfolio_updates", sa.Column("error_message", sa.Text(), nullable=True))


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if "error_message" in {column["name"] for column in inspector.get_columns("portfolio_updates")}:
        op.drop_column("portfolio_updates", "error_message")
    if "error_message" in {column["name"] for column in inspector.get_columns("commits")}:
        op.drop_column("commits", "error_message")
