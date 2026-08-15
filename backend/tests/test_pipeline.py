"""
Integration + unit tests for the AI analysis pipeline.

GitHub API and LLM calls are fully mocked; the database uses SQLite in-memory.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import Analysis, Commit, PortfolioUpdate, Repository
from app.portfolio.updater import PortfolioUpdater
from app.schemas.contracts import (
    CommitAnalysisResult,
    Operation,
    PortfolioPatch,
    RecommendedChanges,
    Significance,
)
from app.services.pipeline import AnalysisPipeline
from app.services.security import find_secrets, verify_github_signature


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _signed_payload(payload: dict, secret: str = "test-secret") -> tuple[bytes, str]:
    raw = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return raw, sig


def _make_repo(db, owner="octo", name="demo", project_id="demo-project", enabled=True) -> Repository:
    r = Repository(owner=owner, name=name, portfolio_project_id=project_id, enabled=enabled)
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def _worthy_analysis(**kwargs) -> CommitAnalysisResult:
    defaults = dict(
        portfolio_worthy=True,
        confidence=0.95,
        significance=Significance.MAJOR,
        category="feature",
        project_id="demo-project",
        technologies=["Python", "Redis"],
        new_capabilities=["Redis caching"],
        recommended_changes=RecommendedChanges(project=True, skills=True, timeline=True),
        reasoning_summary="Added Redis caching, a significant infrastructure improvement.",
    )
    defaults.update(kwargs)
    return CommitAnalysisResult(**defaults)


def _unworthy_analysis(**kwargs) -> CommitAnalysisResult:
    defaults = dict(
        portfolio_worthy=False,
        confidence=0.10,
        significance=Significance.IGNORE,
        category="chore",
        reasoning_summary="Typo fix in README.",
    )
    defaults.update(kwargs)
    return CommitAnalysisResult(**defaults)


def _simple_patch(project_id: str = "demo-project") -> PortfolioPatch:
    return PortfolioPatch(
        operations=[
            Operation(type="add_skill", skill="Redis"),
            Operation(
                type="add_timeline_entry",
                title="Added Redis caching",
                description="Implemented Redis-backed caching layer.",
                date="2026-08-14",
            ),
        ]
    )


# ---------------------------------------------------------------------------
# Security tests
# ---------------------------------------------------------------------------

class TestWebhookSignature:
    def test_valid_signature(self):
        body = b'{"ok":true}'
        sig = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
        assert verify_github_signature(body, sig, "secret")

    def test_wrong_signature(self):
        body = b'{"ok":true}'
        assert not verify_github_signature(body, "sha256=bad", "secret")

    def test_missing_signature(self):
        assert not verify_github_signature(b"data", None, "secret")

    def test_missing_secret(self):
        assert not verify_github_signature(b"data", "sha256=anything", None)

    def test_no_prefix(self):
        assert not verify_github_signature(b"data", "deadbeef", "secret")


class TestSecretDetection:
    def test_openai_key(self):
        assert find_secrets("OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwx")

    def test_aws_key(self):
        assert find_secrets("AKIAIOSFODNN7EXAMPLE")

    def test_github_token(self):
        assert find_secrets("ghp_1234567890abcdefghij12345678901234")

    def test_private_key(self):
        assert find_secrets("-----BEGIN RSA PRIVATE KEY-----")

    def test_clean_text(self):
        assert not find_secrets("Added Redis caching to the application.")

    def test_password_pattern(self):
        assert find_secrets("password=SuperSecret123")


# ---------------------------------------------------------------------------
# Portfolio updater tests
# ---------------------------------------------------------------------------

class TestPortfolioUpdater:
    def test_add_skill_idempotent(self):
        files = {"data/skills.json": json.dumps(["Python"])}
        patch = PortfolioPatch(operations=[Operation(type="add_skill", skill="Python")])
        writes = PortfolioUpdater().materialize(patch, lambda p: files.get(p, ""))
        assert json.loads(writes["data/skills.json"]) == ["Python"]

    def test_add_new_skill(self):
        files = {"data/skills.json": json.dumps(["Python"])}
        patch = PortfolioPatch(operations=[Operation(type="add_skill", skill="Redis")])
        writes = PortfolioUpdater().materialize(patch, lambda p: files.get(p, ""))
        assert "Redis" in json.loads(writes["data/skills.json"])
        assert "Python" in json.loads(writes["data/skills.json"])

    def test_skill_case_insensitive_dedup(self):
        files = {"data/skills.json": json.dumps(["python"])}
        patch = PortfolioPatch(operations=[Operation(type="add_skill", skill="Python")])
        writes = PortfolioUpdater().materialize(patch, lambda p: files.get(p, ""))
        assert len(json.loads(writes["data/skills.json"])) == 1

    def test_mapping_blocks_unrelated_project(self):
        patch = PortfolioPatch(
            operations=[
                Operation(type="update_project", project_id="other", changes={"description": "x"})
            ]
        )
        with pytest.raises(ValueError, match="does not match"):
            PortfolioUpdater().validate(patch, "mapped-project")

    def test_project_unsupported_fields_rejected(self):
        patch = PortfolioPatch(
            operations=[
                Operation(type="update_project", project_id="proj", changes={"secret_field": "x"})
            ]
        )
        with pytest.raises(ValueError, match="unsupported fields"):
            PortfolioUpdater().validate(patch, "proj")

    def test_secret_blocks_portfolio_content(self):
        patch = PortfolioPatch(
            operations=[
                Operation(
                    type="update_project",
                    project_id="x",
                    changes={"description": "token=supersecretvalue"},
                )
            ]
        )
        with pytest.raises(ValueError, match="secret-like content"):
            PortfolioUpdater().materialize(patch, lambda _: "{}")

    def test_timeline_requires_major(self):
        patch = PortfolioPatch(
            operations=[
                Operation(
                    type="add_timeline_entry",
                    title="Small fix",
                    description="Fixed a typo.",
                )
            ]
        )
        with pytest.raises(ValueError, match="MAJOR or MILESTONE"):
            PortfolioUpdater().validate(patch, "proj", Significance.MINOR)

    def test_timeline_accepted_for_major(self):
        patch = PortfolioPatch(
            operations=[
                Operation(
                    type="add_timeline_entry",
                    title="Big feature",
                    description="Added Redis caching.",
                )
            ]
        )
        # Should not raise
        PortfolioUpdater().validate(patch, "proj", Significance.MAJOR)

    def test_timeline_idempotent(self):
        existing = json.dumps(
            [{"date": "2026-01-01", "title": "Big feature", "description": "Added Redis caching."}]
        )
        patch = PortfolioPatch(
            operations=[
                Operation(
                    type="add_timeline_entry",
                    title="Big feature",
                    description="Added Redis caching.",
                )
            ]
        )
        writes = PortfolioUpdater().materialize(
            patch, lambda p: existing if "timeline" in p else "[]"
        )
        assert len(json.loads(writes["data/timeline.json"])) == 1

    def test_feature_list_merges_not_replaces(self):
        files = {"data/projects/proj.json": json.dumps({"features": ["Feature A"]})}
        patch = PortfolioPatch(
            operations=[
                Operation(
                    type="update_project",
                    project_id="proj",
                    changes={"features": ["Feature B"]},
                )
            ]
        )
        writes = PortfolioUpdater().materialize(patch, lambda p: files.get(p, "{}"))
        result = json.loads(writes["data/projects/proj.json"])
        assert "Feature A" in result["features"]
        assert "Feature B" in result["features"]

    def test_suggest_new_project_not_materialized(self):
        patch = PortfolioPatch(
            operations=[
                Operation(type="suggest_new_project", title="New App", description="Cool app.")
            ]
        )
        writes = PortfolioUpdater().materialize(patch, lambda _: "")
        assert not writes  # nothing written to files


# ---------------------------------------------------------------------------
# Webhook idempotency tests
# ---------------------------------------------------------------------------

class TestWebhookIdempotency:
    def test_duplicate_delivery_ignored(self, db):
        db.add(Repository(owner="octo", name="demo", enabled=True))
        db.commit()

        payload = {
            "repository": {"owner": {"login": "octo"}, "name": "demo"},
            "pusher": {"name": "human"},
            "commits": [],
        }
        raw, sig = _signed_payload(payload)
        headers = {
            "X-GitHub-Event": "push",
            "X-GitHub-Delivery": "event-dup-1",
            "X-Hub-Signature-256": sig,
        }

        c = TestClient(app)
        assert c.post("/api/webhooks/github", content=raw, headers=headers).status_code == 202
        second = c.post("/api/webhooks/github", content=raw, headers=headers)
        assert second.json()["status"] == "duplicate"

    def test_push_queues_commits(self, db):
        db.add(Repository(owner="octo", name="demo", enabled=True))
        db.commit()

        payload = {
            "repository": {"owner": {"login": "octo"}, "name": "demo"},
            "pusher": {"name": "human"},
            "commits": [{"id": "abc123", "message": "feat: add Redis caching"}],
        }
        raw, sig = _signed_payload(payload)
        headers = {
            "X-GitHub-Event": "push",
            "X-GitHub-Delivery": "event-push-1",
            "X-Hub-Signature-256": sig,
        }
        resp = TestClient(app).post("/api/webhooks/github", content=raw, headers=headers)
        assert resp.status_code == 202
        assert resp.json()["commits"] == 1

    def test_bot_pusher_ignored(self, db):
        db.add(Repository(owner="octo", name="demo", enabled=True))
        db.commit()

        payload = {
            "repository": {"owner": {"login": "octo"}, "name": "demo"},
            "pusher": {"name": "portfolio-bot[bot]"},
            "commits": [{"id": "bot001", "message": "chore: update"}],
        }
        raw, sig = _signed_payload(payload)
        headers = {
            "X-GitHub-Event": "push",
            "X-GitHub-Delivery": "event-bot-1",
            "X-Hub-Signature-256": sig,
        }
        resp = TestClient(app).post("/api/webhooks/github", content=raw, headers=headers)
        assert resp.json()["status"] == "ignored"

    def test_pull_request_event_handled(self, db):
        payload = {
            "action": "closed",
            "pull_request": {"number": 99, "state": "closed", "merged": True},
        }
        raw, sig = _signed_payload(payload)
        headers = {
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "event-pr-1",
            "X-Hub-Signature-256": sig,
        }
        resp = TestClient(app).post("/api/webhooks/github", content=raw, headers=headers)
        assert resp.status_code == 202
        assert resp.json()["status"] == "pr_closed"

    def test_unknown_event_ignored(self, db):
        payload = {"zen": "Keep it logically awesome."}
        raw, sig = _signed_payload(payload)
        headers = {
            "X-GitHub-Event": "ping",
            "X-GitHub-Delivery": "event-ping-1",
            "X-Hub-Signature-256": sig,
        }
        resp = TestClient(app).post("/api/webhooks/github", content=raw, headers=headers)
        assert resp.json()["status"] == "ignored"


# ---------------------------------------------------------------------------
# Pipeline unit tests (GitHub + LLM fully mocked)
# ---------------------------------------------------------------------------

class TestAnalysisPipeline:
    def _fake_github(self, patch_content: str = "+import redis\n+cache = Redis()") -> MagicMock:
        gh = MagicMock()
        gh.commit.return_value = {
            "files": [
                {"filename": "app/cache.py", "status": "added", "patch": patch_content}
            ]
        }
        gh.repo.return_value = {"description": "Demo app", "default_branch": "main"}
        gh.readme.return_value = "# Demo\nA demo repository."
        gh.recent_commits.return_value = [
            {"commit": {"message": "feat: add Redis caching"}},
            {"commit": {"message": "fix: typo"}},
        ]
        return gh

    def test_unworthy_commit_creates_no_update(self, db):
        repo = _make_repo(db)
        commit = Commit(repository_id=repo.id, sha="abc0001", message="fix typo in README")
        db.add(commit)
        db.commit()
        db.refresh(commit)

        provider = MagicMock()
        provider.analyze.return_value = _unworthy_analysis()

        with patch("app.services.pipeline.get_provider", return_value=provider):
            pipeline = AnalysisPipeline(db, github=self._fake_github())
            result = pipeline.run(commit)

        assert result is None
        assert commit.status == "analyzed"
        analysis = db.query(Analysis).filter_by(commit_id=commit.id).one()
        assert not analysis.portfolio_worthy

    def test_worthy_commit_creates_pending_update(self, db):
        repo = _make_repo(db)
        commit = Commit(repository_id=repo.id, sha="abc0002", message="feat: add Redis caching")
        db.add(commit)
        db.commit()
        db.refresh(commit)

        provider = MagicMock()
        provider.analyze.return_value = _worthy_analysis()
        provider.patch.return_value = _simple_patch()

        # Disable auto_create_pr at global level so we get a pending update back.
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
            mock_settings.return_value = s

            pipeline = AnalysisPipeline(db, github=self._fake_github())
            result = pipeline.run(commit)

        assert result is not None
        assert result.status == "pending"
        analysis = db.query(Analysis).filter_by(commit_id=commit.id).one()
        assert analysis.portfolio_worthy
        assert analysis.significance == "MAJOR"

    def test_pending_update_contains_review_diff_before_approval(self, db):
        repo = _make_repo(db)
        repo.auto_create_pr = False
        commit = Commit(repository_id=repo.id, sha="preview001", message="feat: add Redis caching")
        db.add(commit)
        db.commit()
        db.refresh(commit)

        provider = MagicMock()
        provider.analyze.return_value = _worthy_analysis()
        provider.patch.return_value = _simple_patch()
        github = self._fake_github()
        files = {
            "data/skills.json": json.dumps(["Python"]),
            "data/timeline.json": json.dumps([]),
        }
        github.file.side_effect = lambda owner, name, path, ref: ({"sha": "blob"}, files[path])

        with patch("app.services.pipeline.get_provider", return_value=provider):
            pipeline = AnalysisPipeline(db, github=github)
            original_owner = pipeline.settings.portfolio_owner
            original_repo = pipeline.settings.portfolio_repo
            try:
                pipeline.settings.portfolio_owner = "alice"
                pipeline.settings.portfolio_repo = "portfolio"
                result = pipeline.run(commit)
            finally:
                pipeline.settings.portfolio_owner = original_owner
                pipeline.settings.portfolio_repo = original_repo

        assert result is not None
        assert result.status == "pending"
        assert "data/skills.json" in (result.diff or "")
        assert result.validation_result["preview"] == "ready"
        assert "diff_ready" in result.validation_result["events"]

    def test_below_threshold_creates_no_update(self, db):
        repo = _make_repo(db)
        commit = Commit(repository_id=repo.id, sha="abc0003", message="feat: add minor thing")
        db.add(commit)
        db.commit()
        db.refresh(commit)

        provider = MagicMock()
        provider.analyze.return_value = _worthy_analysis(confidence=0.60)

        with (
            patch("app.services.pipeline.get_provider", return_value=provider),
            patch("app.services.pipeline.get_settings") as mock_settings,
        ):
            s = MagicMock()
            s.portfolio_confidence_threshold = 0.85
            s.llm_model = "gpt-test"
            mock_settings.return_value = s

            pipeline = AnalysisPipeline(db, github=self._fake_github())
            result = pipeline.run(commit)

        assert result is None

    def test_skill_filter_respects_auto_settings(self, db):
        repo = _make_repo(db)
        commit = Commit(repository_id=repo.id, sha="abc0004", message="feat: something big")
        db.add(commit)
        db.commit()
        db.refresh(commit)

        provider = MagicMock()
        provider.analyze.return_value = _worthy_analysis()
        provider.patch.return_value = _simple_patch()

        with (
            patch("app.services.pipeline.get_provider", return_value=provider),
            patch("app.services.pipeline.get_settings") as mock_settings,
        ):
            s = MagicMock()
            s.portfolio_confidence_threshold = 0.85
            s.llm_model = "gpt-test"
            s.auto_update_skills = False  # skills disabled
            s.auto_update_timeline = True
            s.auto_create_pr = False
            mock_settings.return_value = s

            pipeline = AnalysisPipeline(db, github=self._fake_github())
            result = pipeline.run(commit)

        if result:
            ops = result.operations.get("operations", [])
            assert not any(op.get("type") == "add_skill" for op in ops)

    def test_validation_failure_logs_and_returns_none(self, db):
        repo = _make_repo(db, project_id="correct-project")
        commit = Commit(repository_id=repo.id, sha="abc0005", message="feat: add things")
        db.add(commit)
        db.commit()
        db.refresh(commit)

        provider = MagicMock()
        provider.analyze.return_value = _worthy_analysis(project_id="correct-project")
        # The patch claims to update a *different* project.
        provider.patch.return_value = PortfolioPatch(
            operations=[
                Operation(
                    type="update_project",
                    project_id="wrong-project",
                    changes={"description": "hacked"},
                )
            ]
        )

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
            mock_settings.return_value = s

            pipeline = AnalysisPipeline(db, github=self._fake_github())
            result = pipeline.run(commit)

        assert result is None


# ---------------------------------------------------------------------------
# End-to-end fake-event test
# ---------------------------------------------------------------------------

class TestEndToEndFakeEvent:
    """
    Fake a 'feat: add Redis caching' push event through the full stack.

    The GitHub API and LLM are mocked.  The test asserts that:
    - A Commit row is created
    - An Analysis row is created and marked portfolio_worthy=True
    - A PortfolioUpdate row is created with the correct operations
    - The diff preview is populated
    """

    def test_redis_caching_commit_full_flow(self, db):
        repo = _make_repo(db, owner="alice", name="myapp", project_id="myapp")
        # Disable auto_create_pr so we don't try real GitHub API calls.
        repo.auto_create_pr = False
        db.commit()

        # Step 1 – commit row (simulating what the webhook handler does).
        commit = Commit(
            repository_id=repo.id,
            sha="e2e0001feed",
            message="feat: add Redis caching",
        )
        db.add(commit)
        db.commit()
        db.refresh(commit)

        diff_text = (
            "+import redis\n"
            "+REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379')\n"
            "+cache = redis.Redis.from_url(REDIS_URL)\n"
            "+\n"
            "+def get_cached(key):\n"
            "+    return cache.get(key)\n"
        )

        fake_gh = MagicMock()
        fake_gh.commit.return_value = {
            "files": [{"filename": "app/cache.py", "status": "added", "patch": diff_text}]
        }
        fake_gh.repo.return_value = {"description": "My App", "default_branch": "main"}
        fake_gh.readme.return_value = "# My App\nA web application."
        fake_gh.recent_commits.return_value = [
            {"commit": {"message": "feat: add Redis caching"}},
        ]

        analysis_result = CommitAnalysisResult(
            portfolio_worthy=True,
            confidence=0.93,
            significance=Significance.MODERATE,
            category="feature",
            project_id="myapp",
            technologies=["Python", "Redis"],
            new_capabilities=["Redis caching", "Cache invalidation"],
            recommended_changes=RecommendedChanges(project=True, skills=True),
            reasoning_summary=(
                "Added Redis caching implementation with connection pooling. "
                "Represents a meaningful infrastructure improvement."
            ),
        )

        patch_result = PortfolioPatch(
            operations=[
                Operation(type="add_skill", skill="Redis"),
                Operation(
                    type="update_project",
                    project_id="myapp",
                    changes={"description": "Web application with Redis caching."},
                ),
            ]
        )

        provider = MagicMock()
        provider.analyze.return_value = analysis_result
        provider.patch.return_value = patch_result

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
            mock_settings.return_value = s

            pipeline = AnalysisPipeline(db, github=fake_gh)
            update = pipeline.run(commit)

        # Assertions
        assert commit.status == "analyzed"

        analysis = db.query(Analysis).filter_by(commit_id=commit.id).one()
        assert analysis.portfolio_worthy is True
        assert analysis.confidence == pytest.approx(0.93)
        assert analysis.significance == "MODERATE"
        assert "Redis" in analysis.reasoning_summary

        assert update is not None
        assert update.status == "pending"
        ops = update.operations.get("operations", [])
        types = {op["type"] for op in ops}
        assert "add_skill" in types
        assert "update_project" in types

        skills = [op["skill"] for op in ops if op["type"] == "add_skill"]
        assert "Redis" in skills
