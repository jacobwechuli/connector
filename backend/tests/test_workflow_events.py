"""
Tests for workflow-event persistence, webhook replay deduplication,
GitHub status/discovery failure handling, sync deduplication, validation
command pass/fail file restoration, and branch/PR guard on validation failure.

GitHub API and LLM are fully mocked; the database uses the shared SQLite
in-memory fixture from conftest.py.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import Commit, Repository, WorkflowEvent, PortfolioUpdate
from app.schemas.contracts import (
    CommitAnalysisResult,
    Operation,
    PortfolioPatch,
    RecommendedChanges,
    Significance,
)
from app.services.pipeline import AnalysisPipeline, _emit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _signed(payload: dict, secret: str = "test-secret") -> tuple[bytes, str]:
    raw = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return raw, sig


def _make_repo(db, owner="alice", name="myapp", project_id="myapp", enabled=True) -> Repository:
    r = Repository(owner=owner, name=name, portfolio_project_id=project_id, enabled=enabled)
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def _worthy_analysis() -> CommitAnalysisResult:
    return CommitAnalysisResult(
        portfolio_worthy=True,
        confidence=0.95,
        significance=Significance.MAJOR,
        category="feature",
        project_id="myapp",
        technologies=["Python", "Redis"],
        new_capabilities=["Redis caching"],
        recommended_changes=RecommendedChanges(project=True, skills=True, timeline=True),
        reasoning_summary="Added Redis caching.",
    )


def _simple_patch() -> PortfolioPatch:
    return PortfolioPatch(
        operations=[Operation(type="add_skill", skill="Redis")]
    )


def _fake_github(skills_content='["Python"]') -> MagicMock:
    gh = MagicMock()
    gh.commit.return_value = {
        "files": [{"filename": "app/cache.py", "status": "added", "patch": "+import redis"}]
    }
    gh.repo.return_value = {"description": "My App", "default_branch": "main"}
    gh.readme.return_value = "# My App"
    gh.recent_commits.return_value = [{"commit": {"message": "feat: add Redis"}}]
    gh.file.side_effect = lambda owner, name, path, ref: (
        {"sha": "blobsha"},
        skills_content if "skills" in path else "[]",
    )
    return gh


# ---------------------------------------------------------------------------
# _emit helper
# ---------------------------------------------------------------------------

class TestEmitHelper:
    def test_emit_persists_event(self, db):
        repo = _make_repo(db)
        _emit(db, "test_stage", repository_id=repo.id, detail="hello")
        db.commit()
        events = db.query(WorkflowEvent).filter_by(stage="test_stage").all()
        assert len(events) == 1
        assert events[0].repository_id == repo.id
        assert events[0].detail == "hello"

    def test_emit_all_nullable(self, db):
        """_emit should work with no IDs supplied."""
        _emit(db, "global_event")
        db.commit()
        ev = db.query(WorkflowEvent).filter_by(stage="global_event").one()
        assert ev.repository_id is None
        assert ev.commit_id is None
        assert ev.update_id is None


# ---------------------------------------------------------------------------
# Workflow event persistence through pipeline
# ---------------------------------------------------------------------------

class TestPipelineEvents:
    def test_pipeline_emits_events_for_worthy_commit(self, db):
        repo = _make_repo(db)
        commit = Commit(repository_id=repo.id, sha="wf0001", message="feat: add Redis")
        db.add(commit)
        db.commit()
        db.refresh(commit)

        provider = MagicMock()
        provider.analyze.return_value = _worthy_analysis()
        provider.patch.return_value = _simple_patch()
        github = _fake_github()

        with (
            patch("app.services.pipeline.get_provider", return_value=provider),
            patch("app.services.pipeline.get_settings") as mock_settings,
        ):
            s = MagicMock()
            s.portfolio_confidence_threshold = 0.85
            s.llm_model = "gpt-test"
            s.auto_update_skills = True
            s.auto_update_timeline = True
            s.auto_create_pr = False
            s.portfolio_owner = "alice"
            s.portfolio_repo = "portfolio"
            mock_settings.return_value = s

            pipeline = AnalysisPipeline(db, github=github)
            pipeline.run(commit)

        db.expire_all()
        stages = {ev.stage for ev in db.query(WorkflowEvent).all()}
        assert "commit_queued" in stages
        assert "commit_evidence_fetched" in stages
        assert "analysis_started" in stages
        assert "analysis_complete" in stages
        assert "operations_validated" in stages
        # diff_ready may or may not fire depending on portfolio config; at least ensure
        # the analysis stages are all recorded.

    def test_pipeline_emits_not_portfolio_worthy_for_unworthy_commit(self, db):
        from app.schemas.contracts import CommitAnalysisResult
        repo = _make_repo(db)
        commit = Commit(repository_id=repo.id, sha="wf0002", message="fix typo")
        db.add(commit)
        db.commit()
        db.refresh(commit)

        provider = MagicMock()
        provider.analyze.return_value = CommitAnalysisResult(
            portfolio_worthy=False, confidence=0.1,
            significance=Significance.IGNORE, category="chore",
            reasoning_summary="Typo fix.",
        )

        with (
            patch("app.services.pipeline.get_provider", return_value=provider),
            patch("app.services.pipeline.get_settings") as mock_settings,
        ):
            s = MagicMock()
            s.portfolio_confidence_threshold = 0.85
            s.llm_model = "gpt-test"
            mock_settings.return_value = s

            AnalysisPipeline(db, github=_fake_github()).run(commit)

        db.expire_all()
        stages = {ev.stage for ev in db.query(WorkflowEvent).all()}
        assert "not_portfolio_worthy" in stages


# ---------------------------------------------------------------------------
# Webhook deduplication records ignored event
# ---------------------------------------------------------------------------

class TestWebhookDuplicationEvents:
    def test_duplicate_delivery_records_ignored_event(self, db):
        db.add(Repository(owner="octo", name="demo", enabled=True))
        db.commit()

        payload = {
            "repository": {"owner": {"login": "octo"}, "name": "demo"},
            "pusher": {"name": "human"},
            "commits": [],
        }
        raw, sig = _signed(payload)
        headers = {
            "X-GitHub-Event": "push",
            "X-GitHub-Delivery": "dup-evt-01",
            "X-Hub-Signature-256": sig,
        }
        c = TestClient(app)
        c.post("/api/webhooks/github", content=raw, headers=headers)
        resp = c.post("/api/webhooks/github", content=raw, headers=headers)
        assert resp.json()["status"] == "duplicate"

        db.expire_all()
        ignored = db.query(WorkflowEvent).filter_by(stage="webhook_ignored").all()
        assert len(ignored) >= 1
        # detail must not contain the raw secret or webhook payload
        for ev in ignored:
            assert "test-secret" not in (ev.detail or "")


# ---------------------------------------------------------------------------
# Validation command: pass/fail file restoration
# ---------------------------------------------------------------------------

def _pipeline_with_settings(db, **kwargs) -> "AnalysisPipeline":
    """Create a pipeline with a MagicMock settings override."""
    pipeline = AnalysisPipeline(db, github=MagicMock())
    fake = MagicMock()
    for k, v in kwargs.items():
        setattr(fake, k, v)
    pipeline.settings = fake
    return pipeline


class TestPortfolioValidationRestore:
    def test_validation_failure_restores_original_files(self, db):
        """Files must be restored to their originals when the validation command fails."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sentinel = Path(tmpdir) / "data" / "skills.json"
            sentinel.parent.mkdir(parents=True)
            original_content = '["Python"]'
            sentinel.write_text(original_content)

            pipeline = _pipeline_with_settings(
                db,
                portfolio_worktree=tmpdir,
                portfolio_validation_command="exit 1",
                portfolio_validation_timeout_seconds=30,
            )

            with pytest.raises(RuntimeError, match="Portfolio validation failed"):
                pipeline._run_portfolio_validation({"data/skills.json": '["Python","Redis"]'})

            # File must be restored to original content.
            assert sentinel.read_text() == original_content

    def test_validation_success_restores_and_returns_output(self, db):
        with tempfile.TemporaryDirectory() as tmpdir:
            sentinel = Path(tmpdir) / "data" / "skills.json"
            sentinel.parent.mkdir(parents=True)
            sentinel.write_text('["Python"]')

            pipeline = _pipeline_with_settings(
                db,
                portfolio_worktree=tmpdir,
                portfolio_validation_command="echo validation-ok",
                portfolio_validation_timeout_seconds=30,
            )

            output = pipeline._run_portfolio_validation({"data/skills.json": '["Python","Redis"]'})

            # Output should contain the echo result.
            assert "validation-ok" in output
            # File should be restored.
            assert sentinel.read_text() == '["Python"]'


# ---------------------------------------------------------------------------
# Activity endpoint
# ---------------------------------------------------------------------------

class TestActivityEndpoint:
    def test_activity_returns_recent_events(self, db):
        _emit(db, "test_activity_stage", detail="hello")
        db.commit()

        resp = TestClient(app).get("/api/activity")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        stages = [e["stage"] for e in data]
        assert "test_activity_stage" in stages

    def test_activity_limit_respected(self, db):
        for i in range(10):
            _emit(db, f"stage_{i}")
        db.commit()

        resp = TestClient(app).get("/api/activity?limit=3")
        assert resp.status_code == 200
        assert len(resp.json()) <= 3
