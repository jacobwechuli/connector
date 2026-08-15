"""
AI Portfolio Maintainer – CLI

Install (editable from backend/):
    pip install -e .   (if setup.py/pyproject.toml has a console_scripts entry)

Or run directly:
    python -m app.cli repositories
    python -m app.cli analyze owner/repo SHA
"""
from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from app.core.database import SessionLocal
from app.github.client import GitHubClient
from app.models import Commit, PortfolioUpdate, Repository
from app.services.pipeline import AnalysisPipeline

app = typer.Typer(
    name="portfolio-ai",
    help="AI Portfolio Maintainer – manage and monitor your portfolio sync.",
    no_args_is_help=True,
)
console = Console()


# ---------------------------------------------------------------------------
# repositories
# ---------------------------------------------------------------------------

@app.command()
def repositories() -> None:
    """List all connected repositories."""
    db = SessionLocal()
    try:
        rows = db.query(Repository).all()
    finally:
        db.close()

    if not rows:
        console.print("[dim]No repositories connected.[/dim]")
        return

    table = Table(show_header=True, header_style="bold dim")
    table.add_column("ID", style="dim")
    table.add_column("Repository")
    table.add_column("Enabled")
    table.add_column("Project ID")
    table.add_column("Auto PR")

    for r in rows:
        table.add_row(
            str(r.id),
            f"{r.owner}/{r.name}",
            "✓" if r.enabled else "✗",
            r.portfolio_project_id or "–",
            "✓" if r.auto_create_pr else "✗",
        )
    console.print(table)


# ---------------------------------------------------------------------------
# analyze
# ---------------------------------------------------------------------------

@app.command()
def analyze(
    repository: str = typer.Argument(..., help="OWNER/REPO"),
    commit: str = typer.Argument(..., help="Commit SHA"),
) -> None:
    """Analyze a specific commit for portfolio impact."""
    owner, name = repository.split("/", 1)
    db = SessionLocal()
    try:
        repo = db.query(Repository).filter_by(owner=owner, name=name).one_or_none()
        if not repo:
            console.print(f"[red]Repository {repository!r} is not connected.[/red]")
            raise typer.Exit(1)

        item = (
            db.query(Commit).filter_by(repository_id=repo.id, sha=commit).one_or_none()
            or Commit(repository_id=repo.id, sha=commit, message="manual CLI analysis")
        )
        db.add(item)
        db.commit()
        db.refresh(item)

        console.print(f"[cyan]Analyzing {commit[:7]} …[/cyan]")
        result = AnalysisPipeline(db).run(item)

        if result:
            console.print(f"[green]Portfolio update created: id={result.id} status={result.status}[/green]")
        else:
            console.print("[dim]Not portfolio-worthy – no update created.[/dim]")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# sync (latest N commits of a repo)
# ---------------------------------------------------------------------------

@app.command()
def sync(
    repository: str = typer.Argument(..., help="OWNER/REPO"),
    limit: int = typer.Option(5, "--limit", "-n", help="Number of recent commits to analyze"),
) -> None:
    """Fetch and analyze the latest commits from a repository."""
    owner, name = repository.split("/", 1)
    db = SessionLocal()
    try:
        repo = db.query(Repository).filter_by(owner=owner, name=name).one_or_none()
        if not repo:
            console.print(f"[red]Repository {repository!r} is not connected.[/red]")
            raise typer.Exit(1)

        gh = GitHubClient()
        recent = gh.recent_commits(owner, name)[:limit]
        console.print(f"[cyan]Found {len(recent)} recent commit(s) in {repository}.[/cyan]")

        for raw in recent:
            sha = raw["sha"]
            message = raw.get("commit", {}).get("message", "")[:72]

            if db.query(Commit).filter_by(repository_id=repo.id, sha=sha).one_or_none():
                console.print(f"  [dim]{sha[:7]}  (already analyzed)[/dim]")
                continue

            console.print(f"  [cyan]→ {sha[:7]}  {message}[/cyan]")
            item = Commit(repository_id=repo.id, sha=sha, message=message)
            db.add(item)
            db.commit()
            db.refresh(item)

            result = AnalysisPipeline(db).run(item)
            if result:
                console.print(f"    [green]Update #{result.id} created ({result.status})[/green]")
            else:
                console.print("    [dim]Not portfolio-worthy.[/dim]")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# pending
# ---------------------------------------------------------------------------

@app.command()
def pending() -> None:
    """List pending portfolio updates."""
    db = SessionLocal()
    try:
        rows = db.query(PortfolioUpdate).filter_by(status="pending").all()
    finally:
        db.close()

    if not rows:
        console.print("[green]No pending updates.[/green]")
        return

    table = Table(show_header=True, header_style="bold dim")
    table.add_column("ID")
    table.add_column("Commit ID")
    table.add_column("Operations")
    table.add_column("Status")

    for u in rows:
        ops = u.operations.get("operations", [])
        op_str = ", ".join(op.get("type", "?") for op in ops[:3])
        table.add_row(str(u.id), str(u.commit_id), op_str, u.status)

    console.print(table)


# ---------------------------------------------------------------------------
# approve / reject
# ---------------------------------------------------------------------------

@app.command()
def approve(update_id: int = typer.Argument(..., help="Update ID")) -> None:
    """Approve a pending portfolio update."""
    _set_status(update_id, "approved")


@app.command()
def reject(update_id: int = typer.Argument(..., help="Update ID")) -> None:
    """Reject a pending portfolio update."""
    _set_status(update_id, "rejected")


def _set_status(update_id: int, status: str) -> None:
    db = SessionLocal()
    try:
        u = db.get(PortfolioUpdate, update_id)
        if not u:
            console.print(f"[red]Update #{update_id} not found.[/red]")
            raise typer.Exit(1)
        u.status = status
        db.commit()
        console.print(f"[green]Update #{update_id} → {status}[/green]")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# create-pr
# ---------------------------------------------------------------------------

@app.command(name="create-pr")
def create_pr_command(update_id: int = typer.Argument(..., help="Update ID")) -> None:
    """Create a GitHub pull request for an approved update."""
    db = SessionLocal()
    try:
        u = db.get(PortfolioUpdate, update_id)
        if not u:
            console.print(f"[red]Update #{update_id} not found.[/red]")
            raise typer.Exit(1)
        commit = db.get(Commit, u.commit_id)
        source = db.get(Repository, commit.repository_id) if commit else None
        if not commit or not source:
            console.print("[red]Source commit or repository missing.[/red]")
            raise typer.Exit(1)
        console.print("[cyan]Creating pull request…[/cyan]")
        AnalysisPipeline(db).create_pr(u, commit, source)
        console.print(f"[green]PR #{u.pr_number} created on branch {u.branch}[/green]")
    except (RuntimeError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    app()
