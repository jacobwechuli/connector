"""Pydantic contracts for API boundaries and AI structured output."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class Significance(str, Enum):
    IGNORE = "IGNORE"
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    MAJOR = "MAJOR"
    MILESTONE = "MILESTONE"


# ---------------------------------------------------------------------------
# AI analysis output
# ---------------------------------------------------------------------------

class RecommendedChanges(BaseModel):
    project: bool = False
    skills: bool = False
    timeline: bool = False
    resume: bool = False
    blog: bool = False


class CommitAnalysisResult(BaseModel):
    portfolio_worthy: bool
    confidence: float = Field(ge=0, le=1)
    significance: Significance
    category: str
    project_id: str | None = None
    technologies: list[str] = Field(default_factory=list)
    new_capabilities: list[str] = Field(default_factory=list)
    recommended_changes: RecommendedChanges = Field(default_factory=RecommendedChanges)
    reasoning_summary: str = Field(max_length=1000)


# ---------------------------------------------------------------------------
# Portfolio patch operations
# ---------------------------------------------------------------------------

class Operation(BaseModel):
    type: str
    project_id: str | None = None
    changes: dict[str, Any] = Field(default_factory=dict)
    skill: str | None = None
    date: str | None = None
    title: str | None = None
    description: str | None = None

    @field_validator("type")
    @classmethod
    def constrained_type(cls, value: str) -> str:
        allowed = {
            "update_project",
            "add_skill",
            "add_timeline_entry",
            "suggest_resume",
            "suggest_blog",
            "suggest_new_project",
        }
        if value not in allowed:
            raise ValueError(f"unsupported portfolio operation: {value!r}")
        return value


class PortfolioPatch(BaseModel):
    operations: list[Operation] = Field(default_factory=list, max_length=10)


# ---------------------------------------------------------------------------
# Repository API schemas
# ---------------------------------------------------------------------------

class RepositoryCreate(BaseModel):
    owner: str
    name: str
    portfolio_project_id: str | None = None
    enabled: bool = True
    auto_create_pr: bool = True
    auto_merge: bool = False
    is_portfolio: bool = False


class RepositoryOut(RepositoryCreate):
    id: int
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Commit API schemas
# ---------------------------------------------------------------------------

class CommitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    repository_id: int
    sha: str
    message: str
    status: str
    error_message: str | None = None
    processed_at: datetime | None = None


# ---------------------------------------------------------------------------
# Analysis API schemas
# ---------------------------------------------------------------------------

class AnalysisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    commit_id: int
    portfolio_worthy: bool
    confidence: float
    significance: str
    reasoning_summary: str
    model: str
    prompt_version: str
    raw_result: dict
    created_at: datetime


# ---------------------------------------------------------------------------
# Portfolio update API schemas
# ---------------------------------------------------------------------------

class UpdateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    commit_id: int
    operations: dict
    diff: str | None = None
    status: str
    validation_result: dict = Field(default_factory=dict)
    branch: str | None = None
    pr_number: int | None = None
    error_message: str | None = None
    created_at: datetime | None = None
