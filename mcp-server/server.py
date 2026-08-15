"""
AI Portfolio Maintainer – MCP Server

Run with:
    mcp dev mcp-server/server.py                  # dev mode (inspector UI)
    python mcp-server/server.py                   # stdio transport

The server shares the same SQLite/Postgres database as the FastAPI backend.
Set DATABASE_URL in .env (or environment) before starting.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow the backend package to be imported without installation.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from mcp.server.fastmcp import FastMCP

from app.core.database import SessionLocal
from app.models import Analysis, Commit, PortfolioUpdate, Repository
from app.services.pipeline import AnalysisPipeline

mcp = FastMCP("AI Portfolio Maintainer")


# ---------------------------------------------------------------------------
# Repository tools
# ---------------------------------------------------------------------------

@mcp.tool()
def list_repositories() -> list[dict]:
    """List all connected GitHub repositories."""
    db = SessionLocal()
    try:
        return [
            {
                "id": r.id,
                "repository": f"{r.owner}/{r.name}",
                "enabled": r.enabled,
                "project_id": r.portfolio_project_id,
                "auto_create_pr": r.auto_create_pr,
                "auto_merge": r.auto_merge,
            }
            for r in db.query(Repository).all()
        ]
    finally:
        db.close()


@mcp.tool()
def get_repository(repository_id: int) -> dict:
    """Get a single repository by ID."""
    db = SessionLocal()
    try:
        r = db.get(Repository, repository_id)
        if not r:
            return {"error": "repository not found"}
        return {
            "id": r.id,
            "repository": f"{r.owner}/{r.name}",
            "enabled": r.enabled,
            "project_id": r.portfolio_project_id,
            "auto_create_pr": r.auto_create_pr,
            "auto_merge": r.auto_merge,
        }
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Commit tools
# ---------------------------------------------------------------------------

@mcp.tool()
def get_recent_commits(repository_id: int, limit: int = 20) -> list[dict]:
    """Return recent commits for a repository (newest first)."""
    db = SessionLocal()
    try:
        return [
            {
                "id": c.id,
                "sha": c.sha,
                "message": c.message,
                "status": c.status,
                "error": c.error_message,
                "processed_at": str(c.processed_at) if c.processed_at else None,
            }
            for c in db.query(Commit)
            .filter_by(repository_id=repository_id)
            .order_by(Commit.id.desc())
            .limit(min(limit, 50))
            .all()
        ]
    finally:
        db.close()


@mcp.tool()
def analyze_commit(repository_id: int, sha: str) -> dict:
    """
    Analyze a specific commit SHA.

    Creates the commit row if it doesn't already exist, then runs the
    full analysis pipeline synchronously.  Returns the commit status
    and, if a portfolio update was created, its ID.
    """
    db = SessionLocal()
    try:
        repo = db.get(Repository, repository_id)
        if not repo:
            return {"error": "repository not found"}

        existing = db.query(Commit).filter_by(repository_id=repo.id, sha=sha).one_or_none()
        if existing and existing.status == "analyzed":
            analysis = db.query(Analysis).filter_by(commit_id=existing.id).one_or_none()
            return {
                "commit": sha,
                "status": existing.status,
                "already_analyzed": True,
                "portfolio_worthy": analysis.portfolio_worthy if analysis else None,
                "significance": analysis.significance if analysis else None,
            }

        commit = existing or Commit(repository_id=repo.id, sha=sha, message="MCP-requested analysis")
        db.add(commit)
        db.commit()
        db.refresh(commit)

        update = AnalysisPipeline(db).run(commit)
        db.refresh(commit)
        return {
            "commit": sha,
            "status": commit.status,
            "update_id": update.id if update else None,
            "error": commit.error_message,
        }
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Portfolio update tools
# ---------------------------------------------------------------------------

@mcp.tool()
def get_pending_updates() -> list[dict]:
    """Return all portfolio updates awaiting approval."""
    db = SessionLocal()
    try:
        return [
            {
                "id": u.id,
                "commit_id": u.commit_id,
                "operations": u.operations,
                "status": u.status,
                "diff": u.diff,
                "created_at": str(u.created_at),
            }
            for u in db.query(PortfolioUpdate).filter_by(status="pending").all()
        ]
    finally:
        db.close()


@mcp.tool()
def get_update_diff(update_id: int) -> dict:
    """Return the generated diff and operations for a portfolio update."""
    db = SessionLocal()
    try:
        u = db.get(PortfolioUpdate, update_id)
        if not u:
            return {"error": "update not found"}
        return {
            "id": u.id,
            "status": u.status,
            "operations": u.operations,
            "diff": u.diff,
            "validation_result": u.validation_result,
            "branch": u.branch,
            "pr_number": u.pr_number,
        }
    finally:
        db.close()


@mcp.tool()
def approve_update(update_id: int) -> dict:
    """Approve a pending portfolio update."""
    db = SessionLocal()
    try:
        u = db.get(PortfolioUpdate, update_id)
        if not u:
            return {"error": "update not found"}
        if u.status not in {"pending", "approved"}:
            return {"error": f"cannot approve a '{u.status}' update"}
        u.status = "approved"
        db.commit()
        return {"status": "approved", "update_id": update_id}
    finally:
        db.close()


@mcp.tool()
def reject_update(update_id: int) -> dict:
    """Reject a pending portfolio update."""
    db = SessionLocal()
    try:
        u = db.get(PortfolioUpdate, update_id)
        if not u:
            return {"error": "update not found"}
        if u.status not in {"pending", "rejected"}:
            return {"error": f"cannot reject a '{u.status}' update"}
        u.status = "rejected"
        db.commit()
        return {"status": "rejected", "update_id": update_id}
    finally:
        db.close()


@mcp.tool()
def create_portfolio_pr(update_id: int) -> dict:
    """
    Create a GitHub pull request for an approved portfolio update.

    The update must already be in 'approved' status.
    """
    db = SessionLocal()
    try:
        u = db.get(PortfolioUpdate, update_id)
        if not u:
            return {"error": "update not found"}
        if u.pr_number:
            return {"status": u.status, "pr_number": u.pr_number, "already_exists": True}
        commit = db.get(Commit, u.commit_id)
        repo = db.get(Repository, commit.repository_id) if commit else None
        if not commit or not repo:
            return {"error": "source commit or repository not found"}
        AnalysisPipeline(db).create_pr(u, commit, repo)
        return {"pr_number": u.pr_number, "branch": u.branch, "status": u.status}
    except (RuntimeError, ValueError) as exc:
        return {"error": str(exc)}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Portfolio state tools
# ---------------------------------------------------------------------------

@mcp.tool()
def get_portfolio_summary() -> dict:
    """
    Return a high-level summary of the current portfolio state tracked in the database.

    Note: actual portfolio file contents live in the portfolio repository.
    This returns aggregate statistics from the analysis database.
    """
    db = SessionLocal()
    try:
        repos = db.query(Repository).filter_by(enabled=True).count()
        total_commits = db.query(Commit).count()
        worthy = db.query(Analysis).filter_by(portfolio_worthy=True).count()
        updates = db.query(PortfolioUpdate).count()
        pending = db.query(PortfolioUpdate).filter_by(status="pending").count()
        prs = db.query(PortfolioUpdate).filter(PortfolioUpdate.pr_number.isnot(None)).count()
        return {
            "monitored_repositories": repos,
            "commits_analyzed": total_commits,
            "portfolio_worthy_commits": worthy,
            "portfolio_updates_total": updates,
            "pending_approval": pending,
            "prs_created": prs,
        }
    finally:
        db.close()


@mcp.tool()
def get_analysis_for_commit(commit_id: int) -> dict:
    """Return the AI analysis for a specific commit ID."""
    db = SessionLocal()
    try:
        a = db.query(Analysis).filter_by(commit_id=commit_id).one_or_none()
        if not a:
            return {"error": "no analysis found for this commit"}
        return {
            "id": a.id,
            "commit_id": a.commit_id,
            "portfolio_worthy": a.portfolio_worthy,
            "confidence": a.confidence,
            "significance": a.significance,
            "reasoning_summary": a.reasoning_summary,
            "model": a.model,
            "prompt_version": a.prompt_version,
            "technologies": a.raw_result.get("technologies", []),
            "new_capabilities": a.raw_result.get("new_capabilities", []),
            "created_at": str(a.created_at),
        }
    finally:
        db.close()


if __name__ == "__main__":
    mcp.run()
