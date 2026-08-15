"""Portfolio file materializer and operation validator."""
from __future__ import annotations

import json
import logging
from datetime import date

from app.schemas.contracts import PortfolioPatch, Significance
from app.services.security import find_secrets

log = logging.getLogger(__name__)

ALLOWED_PREFIXES = ("data/projects/", "data/skills.json", "data/timeline.json")


class PortfolioUpdater:
    """Validates and materializes constrained portfolio operations.

    Safety guarantees:
    - Only allowed portfolio paths are ever written.
    - Secret-like content causes an immediate abort.
    - Operations are idempotent (no duplicate skills / timeline entries).
    - Deletion of existing content is never performed.
    """

    def validate(
        self,
        patch: PortfolioPatch,
        mapped_project: str | None,
        significance: Significance | None = None,
    ) -> None:
        for op in patch.operations:
            if op.type == "update_project":
                if not mapped_project or op.project_id != mapped_project:
                    raise ValueError(
                        f"update_project for '{op.project_id}' does not match "
                        f"repository mapping '{mapped_project}'"
                    )
                allowed_fields = {"name", "description", "features", "technologies", "url"}
                bad = set(op.changes) - allowed_fields
                if bad:
                    raise ValueError(f"update_project contains unsupported fields: {bad}")

            if op.type == "add_timeline_entry":
                if not (op.title and op.description):
                    raise ValueError("add_timeline_entry requires title and description")
                if significance not in {Significance.MAJOR, Significance.MILESTONE, None}:
                    raise ValueError(
                        "Timeline entries are only added for MAJOR or MILESTONE analyses; "
                        f"got {significance}"
                    )

            if op.type == "suggest_new_project":
                # Suggestions are never materialized – validation always passes.
                pass

    def required_paths(self, patch: PortfolioPatch) -> set[str]:
        """Return the set of portfolio paths that must exist before materialization."""
        paths: set[str] = set()
        for op in patch.operations:
            if op.type == "update_project" and op.project_id:
                paths.add(f"data/projects/{op.project_id}.json")
            elif op.type == "add_skill":
                paths.add("data/skills.json")
            elif op.type == "add_timeline_entry":
                paths.add("data/timeline.json")
            # suggest_* operations are never written to files
        return paths

    def materialize(self, patch: PortfolioPatch, read_file) -> dict[str, str]:
        """Return {path: new_content} for safe, non-destructive writes.

        ``read_file`` is a callable (path: str) -> str that returns the current
        file content, or an empty string for a new file.
        """
        writes: dict[str, str] = {}

        for op in patch.operations:
            if op.type == "update_project":
                path = f"data/projects/{op.project_id}.json"
                current = json.loads(read_file(path) or "{}")
                # Merge – never replace the entire object.
                for key, value in op.changes.items():
                    if key == "features" and isinstance(value, list):
                        # Extend the feature list without duplicating entries.
                        existing: list = current.get("features", [])
                        for f in value:
                            if f not in existing:
                                existing.append(f)
                        current["features"] = existing
                    elif key == "technologies" and isinstance(value, list):
                        existing_tech: list = current.get("technologies", [])
                        for t in value:
                            if t not in existing_tech:
                                existing_tech.append(t)
                        current["technologies"] = existing_tech
                    else:
                        current[key] = value
                writes[path] = json.dumps(current, indent=2) + "\n"

            elif op.type == "add_skill":
                path = "data/skills.json"
                skills: list = json.loads(read_file(path) or "[]")
                if op.skill and op.skill.lower() not in {str(x).lower() for x in skills}:
                    skills.append(op.skill)
                writes[path] = json.dumps(skills, indent=2) + "\n"

            elif op.type == "add_timeline_entry":
                path = "data/timeline.json"
                timeline: list = json.loads(read_file(path) or "[]")
                item = {
                    "date": op.date or date.today().isoformat(),
                    "title": op.title,
                    "description": op.description,
                }
                # Idempotency: skip if an identical entry already exists.
                duplicate = any(
                    x.get("title") == item["title"] and x.get("description") == item["description"]
                    for x in timeline
                )
                if not duplicate:
                    timeline.append(item)
                writes[path] = json.dumps(timeline, indent=2) + "\n"

            elif op.type in {"suggest_resume", "suggest_blog", "suggest_new_project"}:
                # Suggestions are stored in the DB audit trail (raw_result) only;
                # they are never written to portfolio files.
                log.info("suggestion operation recorded (not materialized): %s", op.type)
                continue

        # Safety: assert only allowed paths are written.
        unsafe = [p for p in writes if not p.startswith(ALLOWED_PREFIXES)]
        if unsafe:
            raise ValueError(f"unsafe portfolio paths detected: {unsafe}")

        # Safety: scan final content for secrets.
        combined = "\n".join(writes.values())
        hits = find_secrets(combined)
        if hits:
            raise ValueError(f"secret-like content detected in portfolio patch: {hits}")

        return writes
