from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Repository(Base):
    __tablename__ = "repositories"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(120))
    name: Mapped[str] = mapped_column(String(120))
    portfolio_project_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_create_pr: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_merge: Mapped[bool] = mapped_column(Boolean, default=False)
    is_portfolio: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    __table_args__ = (Index("ix_repo_owner_name", "owner", "name", unique=True),)


class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    delivery_id: Mapped[str] = mapped_column(String(128), unique=True)
    event_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    status: Mapped[str] = mapped_column(String(32), default="queued")


class Commit(Base):
    __tablename__ = "commits"
    id: Mapped[int] = mapped_column(primary_key=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"))
    sha: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    repository: Mapped[Repository] = relationship()
    __table_args__ = (Index("ix_commit_repo_sha", "repository_id", "sha", unique=True),)


class Analysis(Base):
    __tablename__ = "analyses"
    id: Mapped[int] = mapped_column(primary_key=True)
    commit_id: Mapped[int] = mapped_column(ForeignKey("commits.id"), unique=True)
    portfolio_worthy: Mapped[bool] = mapped_column(Boolean)
    confidence: Mapped[float] = mapped_column(Float)
    significance: Mapped[str] = mapped_column(String(20))
    reasoning_summary: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(120))
    prompt_version: Mapped[str] = mapped_column(String(64))
    raw_result: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class PortfolioUpdate(Base):
    __tablename__ = "portfolio_updates"
    id: Mapped[int] = mapped_column(primary_key=True)
    commit_id: Mapped[int] = mapped_column(ForeignKey("commits.id"), unique=True)
    operations: Mapped[dict] = mapped_column(JSON)
    diff: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    validation_result: Mapped[dict] = mapped_column(JSON, default=dict)
    branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pr_number: Mapped[int | None] = mapped_column(nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class WorkflowEvent(Base):
    __tablename__ = "workflow_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    repository_id: Mapped[int | None] = mapped_column(ForeignKey("repositories.id"), nullable=True)
    commit_id: Mapped[int | None] = mapped_column(ForeignKey("commits.id"), nullable=True)
    update_id: Mapped[int | None] = mapped_column(ForeignKey("portfolio_updates.id"), nullable=True)
    stage: Mapped[str] = mapped_column(String(64))
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
