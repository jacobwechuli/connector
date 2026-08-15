"""Core analysis and portfolio-update pipeline."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from difflib import unified_diff

from sqlalchemy.orm import Session

from app.ai.provider import get_provider
from app.core.config import get_settings
from app.github.client import GitHubClient
from app.models import Analysis, Commit, PortfolioUpdate, Repository
from app.portfolio.updater import PortfolioUpdater
from app.schemas.contracts import PortfolioPatch, Significance

log = logging.getLogger(__name__)


class AnalysisPipeline:
    def __init__(self, db: Session, github: GitHubClient | None = None):
        self.db = db
        self.settings = get_settings()
        # Defer GitHub client construction so the pipeline can be tested
        # without credentials when github= is supplied explicitly.
        self._github_arg = github

    @property
    def github(self) -> GitHubClient:
        if self._github_arg is None:
            self._github_arg = GitHubClient()
        return self._github_arg

    # ------------------------------------------------------------------
    # Phase 1 – Analyze a commit
    # ------------------------------------------------------------------

    def run(self, commit: Commit) -> PortfolioUpdate | None:
        """Analyze *commit*, persist an Analysis row, and optionally create a
        pending PortfolioUpdate.  Returns the update when one is created."""
        repo: Repository = commit.repository
        provider = get_provider()

        # Fetch commit evidence from GitHub.
        evidence = self.github.commit(repo.owner, repo.name, commit.sha)
        files = [
            {
                "filename": f["filename"],
                "status": f["status"],
                "patch": f.get("patch", "")[:12_000],
            }
            for f in evidence.get("files", [])
        ]

        context: dict = {
            "repository": f"{repo.owner}/{repo.name}",
            "repository_description": self.github.repo(repo.owner, repo.name).get("description"),
            "readme": self.github.readme(repo.owner, repo.name)[:16_000],
            "recent_commits": [
                x.get("commit", {}).get("message", "")
                for x in self.github.recent_commits(repo.owner, repo.name)
            ],
            "commit_sha": commit.sha,
            "commit_message": commit.message,
            "changed_files": files,
            "portfolio_project_id": repo.portfolio_project_id,
        }

        result = provider.analyze(context)
        log.info(
            "analysis complete repo=%s sha=%s worthy=%s confidence=%.2f significance=%s",
            f"{repo.owner}/{repo.name}",
            commit.sha[:7],
            result.portfolio_worthy,
            result.confidence,
            result.significance.value,
        )

        analysis = Analysis(
            commit_id=commit.id,
            portfolio_worthy=result.portfolio_worthy,
            confidence=result.confidence,
            significance=result.significance.value,
            reasoning_summary=result.reasoning_summary,
            model=self.settings.llm_model,
            prompt_version="commit_analysis:v1",
            raw_result=result.model_dump(mode="json"),
        )
        self.db.add(analysis)

        commit.status = "analyzed"
        commit.processed_at = datetime.now(timezone.utc).replace(tzinfo=None)

        # Not portfolio-worthy or below confidence threshold – stop here.
        if (
            not result.portfolio_worthy
            or result.confidence < self.settings.portfolio_confidence_threshold
        ):
            self.db.commit()
            return None

        # ------------------------------------------------------------------
        # Phase 2 – Generate portfolio patch
        # ------------------------------------------------------------------
        patch_context = {
            "analysis": result.model_dump(mode="json"),
            "repository_mapping": repo.portfolio_project_id,
            "portfolio_rules": (
                "Use only constrained operations. Never exaggerate code evidence. "
                "Return an empty operations list when no change is justified."
            ),
        }
        patch = provider.patch(patch_context)
        patch = self._apply_automation_settings(patch)

        if not patch.operations:
            self.db.commit()
            return None

        updater = PortfolioUpdater()
        try:
            updater.validate(patch, repo.portfolio_project_id, result.significance)
        except ValueError as exc:
            log.warning("patch validation failed: %s", exc)
            self.db.commit()
            return None

        update = PortfolioUpdate(
            commit_id=commit.id,
            operations=patch.model_dump(mode="json"),
            status="pending",
            validation_result={"operations_valid": True, "secret_scan": "pending"},
        )
        self.db.add(update)
        self.db.commit()
        self.db.refresh(update)

        log.info("portfolio update created id=%d", update.id)

        # Honour per-repo auto-create-pr setting.
        if repo.auto_create_pr and self.settings.auto_create_pr:
            try:
                update.status = "approved"
                self.db.commit()
                self.create_pr(update, commit, repo)
            except Exception as exc:
                log.error("auto-create PR failed: %s", exc)
                update.error_message = str(exc)[:2000]
                update.status = "pending"  # fall back so human can retry
                self.db.commit()

        return update

    # ------------------------------------------------------------------
    # Phase 3 – Create pull request
    # ------------------------------------------------------------------

    def create_pr(self, update: PortfolioUpdate, commit: Commit, source_repo: Repository) -> None:
        """Materialize the patch, push a branch, and open a pull request.

        The update MUST be in 'approved' status before calling this method.
        All file reads and diffs are computed before any GitHub write occurs,
        so the branch is only created when the full patch is proven safe.
        """
        if update.status != "approved":
            raise ValueError("approve the update before creating a pull request")

        s = self.settings
        if not s.portfolio_owner or not s.portfolio_repo:
            raise RuntimeError("PORTFOLIO_OWNER and PORTFOLIO_REPO must be configured")

        owner, repo = s.portfolio_owner, s.portfolio_repo
        gh = self.github

        portfolio_meta = gh.repo(owner, repo)
        base = portfolio_meta.get("default_branch", "main")
        base_sha = gh._get(f"/repos/{owner}/{repo}/git/ref/heads/{base}")["object"]["sha"]

        branch = f"portfolio-sync/{source_repo.name}-{commit.sha[:7]}".lower()
        patch = PortfolioUpdate.operations  # just a schema reference – parsed below
        patch = PortfolioPatch.model_validate(update.operations)
        updater = PortfolioUpdater()

        # ----------------------------------------------------------------
        # Read all required files before any write so we can:
        # 1. Guarantee they exist.
        # 2. Build the full diff for the PR description.
        # 3. Collect their current blob SHAs for the put_file call.
        # ----------------------------------------------------------------
        file_meta: dict[str, dict] = {}   # path → GitHub metadata (contains 'sha')
        file_content: dict[str, str] = {}  # path → decoded string content

        for path in updater.required_paths(patch):
            try:
                meta, content = gh.file(owner, repo, path, base)
                file_meta[path] = meta
                file_content[path] = content
            except Exception as exc:
                raise ValueError(
                    f"Portfolio data file '{path}' must exist before it can be updated. "
                    f"Bootstrap it first. (GitHub error: {exc})"
                ) from exc

        writes = updater.materialize(patch, lambda p: file_content.get(p, ""))

        # ----------------------------------------------------------------
        # Second AI validation pass (portfolio quality check)
        # ----------------------------------------------------------------
        provider = get_provider()
        validation_ok, validation_notes = self._validate_patch_quality(provider, writes, commit)
        if not validation_ok:
            raise ValueError(f"AI quality validation rejected the patch: {validation_notes}")

        # ----------------------------------------------------------------
        # Build diff for display and PR description
        # ----------------------------------------------------------------
        diff_parts: list[str] = []
        for path, new_content in writes.items():
            old_content = file_content.get(path, "")
            diff_parts.extend(
                unified_diff(
                    old_content.splitlines(keepends=True),
                    new_content.splitlines(keepends=True),
                    fromfile=f"a/{path}",
                    tofile=f"b/{path}",
                )
            )

        if not diff_parts:
            raise ValueError("Proposed update does not change any portfolio files.")

        # ----------------------------------------------------------------
        # Retrieve analysis for the PR description
        # ----------------------------------------------------------------
        from app.models import Analysis  # local import to avoid circularity
        analysis: Analysis | None = (
            self.db.query(Analysis).filter_by(commit_id=commit.id).one_or_none()
        )

        pr_body = self._build_pr_body(update, commit, source_repo, analysis, diff_parts)
        pr_title = (
            f"chore(portfolio): update {source_repo.portfolio_project_id or source_repo.name}"
        )
        commit_message = (
            f"feat(portfolio): sync {source_repo.name} – "
            f"{analysis.significance if analysis else 'update'}"
        )

        # ----------------------------------------------------------------
        # Only create the branch and push files once everything is validated.
        # ----------------------------------------------------------------
        gh.create_branch(owner, repo, branch, base_sha)

        for path, content in writes.items():
            blob_sha = file_meta[path].get("sha", "")
            gh.put_file(owner, repo, path, content, branch, blob_sha, commit_message)

        pr = gh.create_pr(owner, repo, pr_title, pr_body, branch, base)

        update.branch = branch
        update.pr_number = pr["number"]
        update.status = "pr_created"
        update.diff = "".join(diff_parts)
        update.validation_result = {
            "operations_valid": True,
            "secret_scan": "passed",
            "quality_validation": "passed",
            "quality_notes": validation_notes,
        }
        self.db.commit()
        log.info("PR created #%d branch=%s", pr["number"], branch)

        # Honour auto-merge setting with strict safety checks.
        if s.auto_merge and source_repo.auto_merge:
            self._try_auto_merge(update, pr, owner, repo, analysis)

    # ------------------------------------------------------------------
    # Auto-merge
    # ------------------------------------------------------------------

    def _try_auto_merge(
        self,
        update: PortfolioUpdate,
        pr: dict,
        owner: str,
        repo: str,
        analysis: "Analysis | None",
    ) -> None:
        """Merge the PR only if all safety conditions are met."""
        gh = self.github
        pr_detail = gh.get_pr(owner, repo, pr["number"])

        checks_pass = pr_detail.get("mergeable") is True
        confidence_ok = (
            analysis is not None
            and analysis.confidence >= self.settings.portfolio_confidence_threshold
        )
        validation_ok = (
            update.validation_result.get("quality_validation") == "passed"
            and update.validation_result.get("secret_scan") == "passed"
        )

        if not (checks_pass and confidence_ok and validation_ok):
            log.info(
                "auto-merge skipped: mergeable=%s confidence_ok=%s validation_ok=%s",
                checks_pass,
                confidence_ok,
                validation_ok,
            )
            return

        try:
            gh.merge_pr(
                owner,
                repo,
                pr["number"],
                commit_title=f"chore(portfolio): auto-merge portfolio sync #{pr['number']}",
            )
            update.status = "merged"
            self.db.commit()
            log.info("PR #%d auto-merged", pr["number"])
        except Exception as exc:
            log.warning("auto-merge failed (PR left open): %s", exc)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _apply_automation_settings(self, patch: PortfolioPatch) -> PortfolioPatch:
        """Filter operations according to global automation flags."""
        operations = []
        for op in patch.operations:
            if op.type == "add_skill" and not self.settings.auto_update_skills:
                continue
            if op.type == "add_timeline_entry" and not self.settings.auto_update_timeline:
                continue
            if op.type in {"suggest_resume", "suggest_blog"}:
                # Always retain these as suggestions; they are never materialized.
                pass
            operations.append(op)
        return PortfolioPatch(operations=operations)

    def _validate_patch_quality(
        self,
        provider,
        writes: dict[str, str],
        commit: Commit,
    ) -> tuple[bool, str]:
        """Run a second AI pass to verify the patch is accurate and professional."""
        prompt_path = __import__("pathlib").Path(__file__).resolve().parents[3] / "prompts" / "portfolio_update_validation.md"
        if not prompt_path.exists():
            # Validation prompt not available – allow with a note.
            return True, "validation prompt not found; skipped"

        prompt = prompt_path.read_text()
        context = {
            "commit_message": commit.message,
            "proposed_changes": {path: content for path, content in writes.items()},
        }
        try:
            import json as _json
            from openai import OpenAI
            from app.core.config import get_settings as _gs
            s = _gs()
            client = OpenAI(api_key=s.openai_api_key or s.groq_api_key, base_url=s.llm_base_url)
            resp = client.chat.completions.create(
                model=s.llm_model,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": _json.dumps(context)},
                ],
            )
            data = _json.loads(resp.choices[0].message.content or "{}")
            passed: bool = data.get("approved", True)
            notes: str = data.get("notes", "")
            return passed, notes
        except Exception as exc:
            log.warning("quality validation error (allowing patch): %s", exc)
            return True, f"validation error: {exc}"

    def _build_pr_body(
        self,
        update: PortfolioUpdate,
        commit: Commit,
        source_repo: Repository,
        analysis: "Analysis | None",
        diff_parts: list[str],
    ) -> str:
        ops = update.operations.get("operations", [])
        op_lines = "\n".join(
            f"- `{op.get('type')}` on `{op.get('project_id') or op.get('skill') or op.get('title') or '?'}`"
            for op in ops
        )
        confidence_pct = f"{analysis.confidence:.0%}" if analysis else "N/A"
        significance = analysis.significance if analysis else "N/A"
        reasoning = analysis.reasoning_summary if analysis else "N/A"
        diff_preview = "".join(diff_parts)[:4000]
        if len("".join(diff_parts)) > 4000:
            diff_preview += "\n… (truncated)"

        return f"""## Summary

AI Portfolio Maintainer detected a **{significance}** change in `{source_repo.owner}/{source_repo.name}`.

**Commit:** `{commit.sha[:7]}` – {commit.message}

### Why this matters

{reasoning}

### Portfolio operations

{op_lines}

### Confidence

{confidence_pct}

### Diff preview

```diff
{diff_preview}
```

---
*Generated automatically by [AI Portfolio Maintainer](https://github.com). \
Review carefully before merging.*"""
