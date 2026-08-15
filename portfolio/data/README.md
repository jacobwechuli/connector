# Portfolio Data

This directory contains the structured data files that the AI Portfolio Maintainer
reads and writes when synchronizing your GitHub activity to your portfolio.

## Files

| File | Purpose |
|------|---------|
| `skills.json` | Array of skill/technology strings |
| `timeline.json` | Array of chronological milestone entries |
| `projects/*.json` | One JSON file per portfolio project |

## Project schema

```json
{
  "id": "project-slug",
  "name": "Human-readable name",
  "description": "What the project does.",
  "url": "https://github.com/you/project",
  "technologies": ["Python", "FastAPI"],
  "features": ["Feature 1", "Feature 2"]
}
```

## Timeline entry schema

```json
{
  "date": "2026-08-14",
  "title": "Launched AI Portfolio Maintainer",
  "description": "Deployed production system for automated portfolio sync."
}
```

## Adding a new project

1. Create `data/projects/<slug>.json` with the schema above.
2. In the dashboard, connect the matching GitHub repository and set
   `portfolio_project_id` to `<slug>`.
3. Future commits to that repository will update this file automatically.
