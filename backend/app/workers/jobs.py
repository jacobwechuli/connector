from app.core.database import SessionLocal
from app.models import Commit
from app.services.pipeline import AnalysisPipeline

def analyze_commit_job(commit_id: int) -> None:
    db = SessionLocal()
    try:
        commit = db.get(Commit, commit_id)
        if commit and commit.status == "queued": AnalysisPipeline(db).run(commit)
    except Exception as exc:
        if commit:
            commit.status = "failed"
            commit.error_message = str(exc)[:2000]
            db.commit()
    finally: db.close()
