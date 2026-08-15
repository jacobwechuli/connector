"""FastAPI route definitions."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.github.client import GitHubClient
from app.models import Analysis, Commit, PortfolioUpdate, Repository, WebhookEvent, WorkflowEvent
from app.schemas.contracts import (
    AnalysisOut,
    CommitOut,
    RepositoryCreate,
    RepositoryOut,
    GitHubAccountOut,
    GitHubRepositoryOut,
    UpdateOut,
    WorkflowEventOut,
)
from app.services.pipeline import AnalysisPipeline, _emit
from app.services.security import verify_github_signature
from app.workers.jobs import analyze_commit_job

log = logging.getLogger(__name__)
router = APIRouter()


def _record_update_event(item: PortfolioUpdate, event: str) -> None:
    """Append an auditable lifecycle stage without requiring a schema change."""
    result = dict(item.validation_result or {})
    events = list(result.get("events", []))
    if event not in events:
        events.append(event)
    result["events"] = events
    item.validation_result = result


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Repositories
# ---------------------------------------------------------------------------

@router.get("/repositories", response_model=list[RepositoryOut])
def list_repositories(db: Session = Depends(get_db)):
    return db.query(Repository).order_by(Repository.id.desc()).all()


@router.post("/repositories", response_model=RepositoryOut, status_code=201)
def add_repository(body: RepositoryCreate, db: Session = Depends(get_db)):
    if db.query(Repository).filter_by(owner=body.owner, name=body.name).first():
        raise HTTPException(409, "repository already connected")
    item = Repository(**body.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/github/status", response_model=GitHubAccountOut)
def github_status():
    """Validate configured GitHub credentials and reveal their account."""
    try:
        account = GitHubClient().authenticated_account()
        return GitHubAccountOut(
            connected=True,
            login=account.get("login"),
            avatar_url=account.get("avatar_url"),
        )
    except Exception as exc:
        # Do not expose tokens or raw GitHub errors to the browser.
        return GitHubAccountOut(connected=False, message=str(exc)[:300])


@router.get("/github/repositories", response_model=list[GitHubRepositoryOut])
def github_repositories(db: Session = Depends(get_db)):
    """Discover repositories accessible to the configured GitHub credential."""
    try:
        items = GitHubClient().accessible_repositories()
    except Exception as exc:
        raise HTTPException(502, f"Could not read GitHub repositories: {str(exc)[:300]}") from exc

    connected = {(repo.owner, repo.name) for repo in db.query(Repository).all()}
    return [
        GitHubRepositoryOut(
            owner=item.get("owner", {}).get("login", ""),
            name=item.get("name", ""),
            full_name=item.get("full_name", ""),
            private=bool(item.get("private")),
            default_branch=item.get("default_branch") or "main",
            connected=(item.get("owner", {}).get("login", ""), item.get("name", "")) in connected,
        )
        for item in items
        if item.get("owner", {}).get("login") and item.get("name")
    ]


@router.patch("/repositories/{repository_id}", response_model=RepositoryOut)
def update_repository(repository_id: int, body: RepositoryCreate, db: Session = Depends(get_db)):
    item = db.get(Repository, repository_id)
    if not item:
        raise HTTPException(404, "repository not found")
    for key, value in body.model_dump().items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/repositories/{repository_id}", status_code=204)
def disconnect_repository(repository_id: int, db: Session = Depends(get_db)):
    item = db.get(Repository, repository_id)
    if not item:
        raise HTTPException(404, "repository not found")
    db.delete(item)
    db.commit()


@router.get("/repositories/{repository_id}/commits", response_model=list[CommitOut])
def repository_commits(repository_id: int, db: Session = Depends(get_db)):
    if not db.get(Repository, repository_id):
        raise HTTPException(404, "repository not found")
    return (
        db.query(Commit)
        .filter_by(repository_id=repository_id)
        .order_by(Commit.id.desc())
        .limit(50)
        .all()
    )


@router.post("/repositories/{repository_id}/sync")
def sync_repository(
    repository_id: int,
    tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Import recent GitHub commits and queue any new ones for analysis."""
    repository = db.get(Repository, repository_id)
    if not repository:
        raise HTTPException(404, "repository not found")
    try:
        recent = GitHubClient().recent_commits(repository.owner, repository.name)
    except Exception as exc:
        raise HTTPException(502, f"Could not fetch commits: {str(exc)[:300]}") from exc

    queued = 0
    for raw in recent:
        sha = raw.get("sha", "")
        if not sha or db.query(Commit).filter_by(repository_id=repository.id, sha=sha).first():
            continue
        message = raw.get("commit", {}).get("message", "")
        commit = Commit(repository_id=repository.id, sha=sha, message=message)
        db.add(commit)
        db.flush()
        tasks.add_task(analyze_commit_job, commit.id)
        queued += 1
    db.commit()
    return {"status": "queued", "commits": queued}


# ---------------------------------------------------------------------------
# Analyses
# ---------------------------------------------------------------------------

@router.get("/analyses", response_model=list[AnalysisOut])
def list_analyses(db: Session = Depends(get_db)):
    return db.query(Analysis).order_by(Analysis.id.desc()).limit(100).all()


@router.get("/analyses/{analysis_id}", response_model=AnalysisOut)
def get_analysis(analysis_id: int, db: Session = Depends(get_db)):
    item = db.get(Analysis, analysis_id)
    if not item:
        raise HTTPException(404, "analysis not found")
    return item


@router.get("/commits/{commit_id}/analysis", response_model=AnalysisOut)
def commit_analysis(commit_id: int, db: Session = Depends(get_db)):
    item = db.query(Analysis).filter_by(commit_id=commit_id).one_or_none()
    if not item:
        raise HTTPException(404, "analysis not found for commit")
    return item


# ---------------------------------------------------------------------------
# Portfolio updates
# ---------------------------------------------------------------------------

@router.get("/updates", response_model=list[UpdateOut])
def list_updates(db: Session = Depends(get_db)):
    return db.query(PortfolioUpdate).order_by(PortfolioUpdate.id.desc()).all()


@router.get("/updates/{update_id}", response_model=UpdateOut)
def update_detail(update_id: int, db: Session = Depends(get_db)):
    item = db.get(PortfolioUpdate, update_id)
    if not item:
        raise HTTPException(404, "update not found")
    return item


@router.post("/updates/{update_id}/approve")
def approve(update_id: int, db: Session = Depends(get_db)):
    item = db.get(PortfolioUpdate, update_id)
    if not item:
        raise HTTPException(404, "update not found")
    if item.status not in {"pending", "approved"}:
        raise HTTPException(409, f"cannot approve a '{item.status}' update")
    item.status = "approved"
    _record_update_event(item, "approved")
    commit = db.get(Commit, item.commit_id)
    _emit(db, "approved",
          repository_id=commit.repository_id if commit else None,
          commit_id=item.commit_id, update_id=update_id)
    db.commit()
    return {"status": item.status}


@router.post("/updates/{update_id}/reject")
def reject(update_id: int, db: Session = Depends(get_db)):
    item = db.get(PortfolioUpdate, update_id)
    if not item:
        raise HTTPException(404, "update not found")
    if item.status not in {"pending", "rejected"}:
        raise HTTPException(409, f"cannot reject a '{item.status}' update")
    item.status = "rejected"
    _record_update_event(item, "rejected")
    commit = db.get(Commit, item.commit_id)
    _emit(db, "rejected",
          repository_id=commit.repository_id if commit else None,
          commit_id=item.commit_id, update_id=update_id)
    db.commit()
    return {"status": item.status}


@router.post("/updates/{update_id}/create-pr")
def create_portfolio_pr(update_id: int, db: Session = Depends(get_db)):
    item = db.get(PortfolioUpdate, update_id)
    if not item:
        raise HTTPException(404, "update not found")
    if item.pr_number:
        return {"status": item.status, "pr_number": item.pr_number}
    commit = db.get(Commit, item.commit_id)
    source = db.get(Repository, commit.repository_id) if commit else None
    if not commit or not source:
        raise HTTPException(409, "source commit is unavailable")
    try:
        AnalysisPipeline(db).create_pr(item, commit, source)
    except (RuntimeError, ValueError) as exc:
        item.error_message = str(exc)[:2000]
        _record_update_event(item, "pr_creation_failed")
        db.commit()
        raise HTTPException(422, str(exc)) from exc
    return {"status": item.status, "pr_number": item.pr_number}


@router.post("/updates/{update_id}/revert")
def revert_update(update_id: int, db: Session = Depends(get_db)):
    """Mark a pr_created or merged update as reverted (manual safety net)."""
    item = db.get(PortfolioUpdate, update_id)
    if not item:
        raise HTTPException(404, "update not found")
    if item.status not in {"pr_created", "merged", "approved"}:
        raise HTTPException(409, f"cannot revert a '{item.status}' update")
    item.status = "reverted"
    db.commit()
    return {
        "status": "reverted",
        "note": "Database status updated. Close or revert the GitHub PR manually if needed.",
        "branch": item.branch,
        "pr_number": item.pr_number,
    }


# ---------------------------------------------------------------------------
# Activity feed
# ---------------------------------------------------------------------------

@router.get("/activity", response_model=list[WorkflowEventOut])
def list_activity(limit: int = 50, db: Session = Depends(get_db)):
    """Return the most recent workflow events across all repositories."""
    return (
        db.query(WorkflowEvent)
        .order_by(WorkflowEvent.id.desc())
        .limit(min(limit, 200))
        .all()
    )


# ---------------------------------------------------------------------------
# Manual commit analysis trigger
# ---------------------------------------------------------------------------

@router.post("/commits/{commit_id}/analyze")
def manual_analyze(commit_id: int, tasks: BackgroundTasks, db: Session = Depends(get_db)):
    item = db.get(Commit, commit_id)
    if not item:
        raise HTTPException(404, "commit not found")
    item.status = "queued"
    item.error_message = None
    db.commit()
    tasks.add_task(analyze_commit_job, item.id)
    return {"status": "queued"}


# ---------------------------------------------------------------------------
# GitHub webhook
# ---------------------------------------------------------------------------

@router.post("/webhooks/github", status_code=202)
async def github_webhook(
    request: Request,
    tasks: BackgroundTasks,
    x_github_event: str = Header(""),
    x_github_delivery: str = Header(""),
    x_hub_signature_256: str | None = Header(None),
    db: Session = Depends(get_db),
):
    raw = await request.body()
    s = get_settings()

    if not verify_github_signature(raw, x_hub_signature_256, s.github_webhook_secret):
        raise HTTPException(401, "invalid webhook signature")

    # Idempotency – ignore replayed deliveries.
    if db.query(WebhookEvent).filter_by(delivery_id=x_github_delivery).first():
        _emit(db, "webhook_ignored",
              detail=f"duplicate delivery {x_github_delivery[:40]}")
        db.commit()
        return {"status": "duplicate"}

    payload = json.loads(raw)
    event = WebhookEvent(
        delivery_id=x_github_delivery,
        event_type=x_github_event,
        payload=payload,
    )
    db.add(event)

    extra: dict = {}
    if x_github_event == "push":
        extra = _handle_push(payload, event, tasks, db)
    elif x_github_event == "pull_request":
        _handle_pull_request(payload, event, db)
    else:
        event.status = "ignored"
        _emit(db, "webhook_ignored", detail=f"event={x_github_event[:40]}")

    db.commit()
    return {"status": event.status, **extra}


def _handle_push(payload: dict, event: WebhookEvent, tasks: BackgroundTasks, db: Session) -> dict:
    info = payload.get("repository", {})
    repository = db.query(Repository).filter_by(
        owner=info.get("owner", {}).get("login"),
        name=info.get("name"),
    ).first()

    repo_id = repository.id if repository else None

    # Ignore pushes from our own bot or untracked / disabled repos.
    pusher = payload.get("pusher", {}).get("name", "")
    if not repository or not repository.enabled or pusher.endswith("[bot]"):
        event.status = "ignored"
        _emit(db, "webhook_ignored",
              repository_id=repo_id,
              detail=f"push ignored: pusher={pusher[:40]} enabled={getattr(repository, 'enabled', False)}")
        return {}

    _emit(db, "webhook_received", repository_id=repo_id,
          detail=f"push from {pusher[:40]}")

    queued = 0
    for incoming in payload.get("commits", []):
        sha = incoming.get("id") or incoming.get("sha", "")
        if not sha:
            continue
        if db.query(Commit).filter_by(repository_id=repository.id, sha=sha).first():
            continue
        commit = Commit(
            repository_id=repository.id,
            sha=sha,
            message=incoming.get("message", ""),
        )
        db.add(commit)
        db.flush()
        tasks.add_task(analyze_commit_job, commit.id)
        queued += 1

    event.status = "queued"
    log.info("push event queued %d commits for repo=%s/%s", queued, info.get("owner", {}).get("login"), info.get("name"))
    return {"commits": queued}


def _handle_pull_request(payload: dict, event: WebhookEvent, db: Session) -> None:
    """Record pull_request events and link them to existing PortfolioUpdate rows."""
    action = payload.get("action", "")
    pr_data = payload.get("pull_request", {})
    pr_number = pr_data.get("number")
    pr_state = pr_data.get("state", "")
    merged = pr_data.get("merged", False)

    if pr_number is None:
        event.status = "ignored"
        return

    # Find a PortfolioUpdate that owns this PR and update its status.
    update: PortfolioUpdate | None = (
        db.query(PortfolioUpdate).filter_by(pr_number=pr_number).one_or_none()
    )
    if update:
        if merged:
            update.status = "merged"
            _emit(db, "merged", commit_id=update.commit_id, update_id=update.id,
                  detail=f"PR #{pr_number} merged")
        elif pr_state == "closed":
            update.status = "pr_closed"
            _emit(db, "pr_closed", commit_id=update.commit_id, update_id=update.id,
                  detail=f"PR #{pr_number} closed")
        # For 'synchronize', 'review_requested', etc. – no status change needed.

    event.status = f"pr_{action}"
    log.info("pull_request event action=%s pr=#%d", action, pr_number)
