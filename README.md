# AI Portfolio Maintainer

> Reviewable, evidence-based synchronisation between your GitHub activity and your personal developer portfolio.

The system watches repositories you choose, analyses every commit with an LLM, and opens a pull request on your portfolio repository when something genuinely portfolio-worthy has changed.

---

## Table of contents

1. [How it works](#how-it-works)
2. [Architecture](#architecture)
3. [Prerequisites](#prerequisites)
4. [Local development setup](#local-development-setup)
5. [GitHub App setup](#github-app-setup)
6. [Webhook setup](#webhook-setup)
7. [Configuring the LLM](#configuring-the-llm)
8. [Connecting your first repository](#connecting-your-first-repository)
9. [Testing a webhook locally](#testing-a-webhook-locally)
10. [Creating the first portfolio PR](#creating-the-first-portfolio-pr)
11. [Dashboard guide](#dashboard-guide)
12. [CLI reference](#cli-reference)
13. [MCP server](#mcp-server)
14. [Environment variables](#environment-variables)
15. [Running tests](#running-tests)
16. [Security model](#security-model)
17. [Extending the system](#extending-the-system)

---

## How it works

```
Developer pushes commit
        ↓
GitHub webhook  →  POST /api/webhooks/github
        ↓
Signature verified, commit queued
        ↓
Background job: fetch diff from GitHub API
        ↓
LLM analysis (commit_analysis prompt v1)
        ↓
Significance classified: IGNORE / MINOR / MODERATE / MAJOR / MILESTONE
        ↓
Below threshold?  → Stop (no portfolio change)
        ↓
LLM generates constrained portfolio operations
        ↓
Operations validated (path safety, secret scan, mapping check)
        ↓
AUTO_CREATE_PR=true?  → auto-approve + proceed
        ↓  (or manual approval via dashboard/CLI)
Second AI validation pass (portfolio quality check)
        ↓
Branch created on portfolio repo
File(s) written (only data/projects/*, data/skills.json, data/timeline.json)
        ↓
Pull request opened
        ↓
AUTO_MERGE=true + all checks pass?  → merged
        ↓
Dashboard shows result; same webhook replay → "duplicate" (idempotent)
```

---

## Architecture

```
ai-portfolio-maintainer/
├── backend/                    FastAPI application
│   ├── app/
│   │   ├── ai/                 LLM provider abstraction
│   │   ├── api/                HTTP routes
│   │   ├── core/               Config, database session
│   │   ├── github/             GitHub REST client (PAT + App auth)
│   │   ├── models/             SQLAlchemy ORM models
│   │   ├── portfolio/          Portfolio file materializer & validator
│   │   ├── schemas/            Pydantic contracts
│   │   ├── services/           Pipeline + security helpers
│   │   ├── workers/            Background job dispatcher
│   │   └── cli.py              Typer CLI
│   ├── alembic/                Database migrations
│   └── tests/                  pytest test suite
│
├── frontend/                   Next.js 14 dashboard
│   ├── app/                    App Router pages
│   ├── components/             Shared UI components
│   └── lib/                    Typed API client + types
│
├── mcp-server/                 MCP server (shares DB with backend)
│   └── server.py
│
├── portfolio/                  Bootstrap portfolio data files
│   └── data/
│       ├── projects/           One JSON per portfolio project
│       ├── skills.json
│       └── timeline.json
│
├── prompts/                    Versioned LLM prompt files
│   ├── commit_analysis.md      v1 – significance classification
│   ├── portfolio_update.md     v1 – constrained patch generation
│   └── portfolio_update_validation.md  – quality check pass
│
├── docker-compose.yml
├── .env.example
└── README.md  ← you are here
```

---

## Prerequisites

| Requirement | Minimum |
|-------------|---------|
| Python | 3.11 + |
| Node.js | 18 + |
| Docker (optional) | 24 + |
| PostgreSQL | 15 + (or use the Docker service) |
| GitHub account | – |
| OpenAI API key or Groq key | – |

---

## Local development setup

### 1 – Clone and install

```bash
git clone https://github.com/YOUR_USERNAME/ai-portfolio-maintainer
cd ai-portfolio-maintainer

# Backend
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2 – Copy and fill in the environment file

```bash
cp .env.example .env
```

Edit `.env` and fill in at minimum:

```env
DATABASE_URL=sqlite:///./portfolio.db      # or postgresql+psycopg://…
GITHUB_TOKEN=ghp_your_pat_here
GITHUB_WEBHOOK_SECRET=some-random-string
PORTFOLIO_OWNER=your-github-username
PORTFOLIO_REPO=your-portfolio-repo
OPENAI_API_KEY=sk-…
```

### 3 – Run database migrations

```bash
cd backend
alembic upgrade head
```

### Review-first portfolio workflow

The dashboard discovers repositories through the configured GitHub PAT or GitHub
App, but it never writes to GitHub when a commit first arrives. A meaningful
commit moves through: **webhook received → commit evidence fetched → AI analysis
→ constrained operations validated → review diff ready → human approval → local
portfolio validation command → branch/commit/PR**.

To require a real portfolio build or test before opening a PR, set:

```env
PORTFOLIO_WORKTREE=/absolute/path/to/your/portfolio-checkout
PORTFOLIO_VALIDATION_COMMAND=npm run build
```

For Docker Compose, set `PORTFOLIO_WORKTREE_HOST_PATH` to the same checkout on
your host. Inside the container it is available at `/portfolio-worktree`.

### 4 – Start the backend

```bash
uvicorn app.main:app --reload --port 8000
```

### 5 – Start the frontend

```bash
cd frontend
npm install
npm run dev
```

The dashboard is available at **http://localhost:3000**.

### 6 – Docker Compose (all-in-one)

```bash
cp .env.example .env
# edit .env
docker compose up --build
```

Services:
- `postgres` – PostgreSQL 16 on port 5432
- `backend` – FastAPI on port 8000
- `frontend` – Next.js on port 3000

---

## GitHub App setup

Using a GitHub App is the recommended production approach.
It provides fine-grained permissions and installation tokens.

### Creating the App

1. Go to **Settings → Developer settings → GitHub Apps → New GitHub App**.
2. Fill in:
   - **App name**: `portfolio-maintainer-yourname`
   - **Homepage URL**: your portfolio URL
   - **Webhook URL**: `https://your-domain.com/api/webhooks/github`
   - **Webhook secret**: a random string (also set as `GITHUB_WEBHOOK_SECRET`)
3. **Permissions** (Repository):
   - Contents: Read & Write
   - Pull requests: Read & Write
   - Metadata: Read-only
   - Webhooks: Read-only
4. **Subscribe to events**: `Push`, `Pull request`
5. Click **Create GitHub App**.
6. Generate and download the private key.
7. Note the **App ID**.

### Installing the App

1. Click **Install App** on your new GitHub App page.
2. Select the repositories (your portfolio repo + monitored repos).

### Environment variables

```env
GITHUB_APP_ID=123456
GITHUB_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n…\n-----END RSA PRIVATE KEY-----"
```

> The system falls back to `GITHUB_TOKEN` (PAT) if App credentials are not set.
> For local development a PAT is simpler.

---

## Webhook setup

### Production

Point the webhook URL in your GitHub App (or repository settings) to:

```
https://your-domain.com/api/webhooks/github
```

### Local development with ngrok

```bash
ngrok http 8000
```

Copy the `https://xxxx.ngrok.io` URL and use it as the webhook URL.

Events to subscribe: **push**, **pull_request**

### Testing signature

```bash
curl -X POST http://localhost:8000/api/webhooks/github \
  -H "X-GitHub-Event: push" \
  -H "X-GitHub-Delivery: test-001" \
  -H "X-Hub-Signature-256: sha256=COMPUTEDHMAC" \
  -d '{"repository":{"owner":{"login":"you"},"name":"myrepo"},"pusher":{"name":"you"},"commits":[]}'
```

---

## Configuring the LLM

### OpenAI (default)

```env
LLM_PROVIDER=openai
LLM_MODEL=gpt-4.1-mini
OPENAI_API_KEY=sk-…
```

### Groq

```env
LLM_PROVIDER=groq
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_MODEL=llama-3.3-70b-versatile
GROQ_API_KEY=gsk_…
```

Any OpenAI-compatible endpoint works via `LLM_BASE_URL`.

---

## Connecting your first repository

### Via the dashboard

1. Open **http://localhost:3000/repositories**.
2. Click **Connect repository**.
3. Enter the GitHub owner and repository name.
4. Set the **Portfolio project ID** (the slug used in `data/projects/<slug>.json`).
5. Enable monitoring and configure PR/merge settings.
6. Click **Connect**.

### Via the API

```bash
curl -X POST http://localhost:8000/api/repositories \
  -H "Content-Type: application/json" \
  -d '{"owner":"you","name":"my-app","portfolio_project_id":"my-app","enabled":true}'
```

### Via the CLI

Connect via API or dashboard, then test with:

```bash
portfolio-ai repositories
portfolio-ai sync you/my-app --limit 3
```

---

## Testing a webhook locally

1. Make a real commit to a connected repository.
2. GitHub sends the webhook to your ngrok tunnel.
3. The backend logs will show:

```
INFO  push event queued 1 commits for repo=you/my-app
INFO  analysis complete repo=you/my-app sha=abc1234 worthy=true confidence=0.92 significance=MAJOR
INFO  portfolio update created id=1
INFO  PR created #42 branch=portfolio-sync/my-app-abc1234
```

4. Check the dashboard at **http://localhost:3000**.

---

## Creating the first portfolio PR

1. Ensure `data/projects/<your-project-slug>.json` exists in your portfolio repo.
   Copy `portfolio/data/projects/ai-portfolio-maintainer.json` as a template.
2. Push a meaningful commit to a connected repository.
3. The system analyzes it and creates a `pending` update.
4. On the dashboard:
   - If `AUTO_CREATE_PR=false`: click **Approve** then **Create PR**.
   - If `AUTO_CREATE_PR=true`: the PR is created automatically after analysis.
5. Review the PR on GitHub, then merge.

---

## Dashboard guide

| Page | Purpose |
|------|---------|
| `/` | Overview – stats, recent updates, first-run guide |
| `/repositories` | Connect, edit, disable, delete repos; view commits; trigger manual analysis |
| `/updates` | All portfolio updates; approve/reject/create PR |
| `/updates/:id` | Detail – analysis, operations, diff viewer, validation result |
| `/analyses` | All AI analyses with significance and technologies |
| `/analyses/:id` | Full analysis detail with raw AI output |

---

## CLI reference

```bash
# List connected repositories
portfolio-ai repositories

# Analyze a specific commit
portfolio-ai analyze owner/repo SHA

# Sync the latest N commits of a repository
portfolio-ai sync owner/repo --limit 5

# List pending portfolio updates
portfolio-ai pending

# Approve an update
portfolio-ai approve <update-id>

# Reject an update
portfolio-ai reject <update-id>

# Create a GitHub PR for an approved update
portfolio-ai create-pr <update-id>
```

Run from the `backend/` directory after activating the virtual environment:

```bash
python -m app.cli --help
```

---

## MCP server

The MCP server allows another AI agent (Claude, GPT, etc.) to interact with the Portfolio Maintainer.

### Starting

```bash
# Development mode (with inspector UI)
mcp dev mcp-server/server.py

# Production (stdio transport)
python mcp-server/server.py
```

### Available tools

| Tool | Description |
|------|-------------|
| `list_repositories` | List all connected repos |
| `get_repository` | Get a single repo by ID |
| `get_recent_commits` | Recent commits for a repo |
| `analyze_commit` | Run full analysis on a SHA |
| `get_analysis_for_commit` | Get stored analysis by commit ID |
| `get_pending_updates` | All updates awaiting approval |
| `get_update_diff` | Diff + operations for an update |
| `approve_update` | Approve a pending update |
| `reject_update` | Reject a pending update |
| `create_portfolio_pr` | Open a GitHub PR for an approved update |
| `get_portfolio_summary` | High-level stats |

### Example agent interaction

```
User: "Analyze my latest work and tell me whether my portfolio needs updating."

Agent:
1. list_repositories()       → finds id=1 (my-app)
2. get_recent_commits(1)     → SHA abc1234
3. analyze_commit(1, "abc1234")  → {update_id: 5, status: "analyzed"}
4. get_pending_updates()     → [{id: 5, operations: […]}]
5. get_update_diff(5)        → shows the proposed diff
6. approve_update(5)         → approved
7. create_portfolio_pr(5)    → {pr_number: 42, branch: "portfolio-sync/…"}
```

---

## Environment variables

See [`.env.example`](.env.example) for the full list with comments.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Yes | `sqlite:///./portfolio.db` | PostgreSQL or SQLite |
| `GITHUB_TOKEN` | One of: | – | Personal Access Token |
| `GITHUB_APP_ID` | One of: | – | GitHub App ID |
| `GITHUB_PRIVATE_KEY` | One of: | – | GitHub App private key |
| `GITHUB_WEBHOOK_SECRET` | Yes | – | Webhook HMAC secret |
| `PORTFOLIO_OWNER` | Yes | – | GitHub owner of portfolio repo |
| `PORTFOLIO_REPO` | Yes | – | GitHub name of portfolio repo |
| `LLM_PROVIDER` | No | `openai` | `openai` or `groq` |
| `LLM_MODEL` | No | `gpt-4.1-mini` | Model name |
| `OPENAI_API_KEY` | If OpenAI | – | |
| `GROQ_API_KEY` | If Groq | – | |
| `PORTFOLIO_CONFIDENCE_THRESHOLD` | No | `0.85` | Min confidence to trigger update |
| `AUTO_CREATE_PR` | No | `true` | Create PR automatically |
| `AUTO_MERGE` | No | `false` | Merge PR automatically (strict checks) |
| `AUTO_UPDATE_SKILLS` | No | `true` | Include skill operations |
| `AUTO_UPDATE_TIMELINE` | No | `true` | Include timeline operations |
| `DASHBOARD_API_KEY` | No | – | Protect dashboard endpoints |
| `CORS_ORIGINS` | No | `http://localhost:3000` | Comma-separated browser origins allowed to call the API; use the exact HTTPS production origin, without a trailing slash |
| `NEXT_PUBLIC_API_URL` | No | `http://localhost:8000` | Public HTTPS URL of the backend. Next.js embeds this value when the frontend is built. |

For a deployed frontend, set both values before building: `CORS_ORIGINS` must include the deployed frontend's exact origin, and `NEXT_PUBLIC_API_URL` must be the deployed backend's public HTTPS URL. Restart/rebuild the backend after changing `CORS_ORIGINS`; rebuild the frontend after changing `NEXT_PUBLIC_API_URL`.

---

## Running tests

```bash
cd backend
pytest tests/ -v
```

Expected: **39 tests pass** (security, webhook idempotency, portfolio updater, pipeline unit, end-to-end).

---

## Security model

- **Webhook signature**: every incoming webhook is verified via HMAC-SHA256.
- **Path allowlist**: the portfolio updater only ever writes to `data/projects/*`, `data/skills.json`, and `data/timeline.json`. Any other path raises `ValueError` before a branch is created.
- **Secret scan**: before committing, all generated file content is scanned for API keys, tokens, private keys, and passwords.
- **Second validation pass**: the LLM is asked to review the proposed changes for accuracy and professionalism before the branch is created.
- **No deletes**: the updater merges into existing content; it never removes fields or projects.
- **Bot-push loop prevention**: commits where the pusher name ends in `[bot]` are ignored.
- **Idempotency**: webhook delivery IDs and commit SHAs are tracked in PostgreSQL; replays produce `{"status":"duplicate"}`.
- **Approval gate**: unless `AUTO_CREATE_PR=true`, a human must approve in the dashboard before a PR is created.
- **Auto-merge checks**: auto-merge only fires when PR is mergeable, confidence ≥ threshold, and both secret scan and quality validation passed.

---

## Extending the system

### Adding a new LLM provider

1. Create a class inheriting `LLMProvider` in [`backend/app/ai/provider.py`](backend/app/ai/provider.py).
2. Implement `analyze()` and `patch()`.
3. Register it in `get_provider()`.
4. Set `LLM_PROVIDER=yourprovider` in `.env`.

### Adding a new portfolio operation type

1. Add the type to `Operation.constrained_type` validator in [`backend/app/schemas/contracts.py`](backend/app/schemas/contracts.py).
2. Handle it in `PortfolioUpdater.required_paths()` and `materialize()` in [`backend/app/portfolio/updater.py`](backend/app/portfolio/updater.py).
3. Add the path to `ALLOWED_PREFIXES` if needed.
4. Update the portfolio_update prompt.

### Replacing BackgroundTasks with Celery

The job dispatcher in [`backend/app/workers/jobs.py`](backend/app/workers/jobs.py) exposes a single `analyze_commit_job(commit_id)` function.
To swap in Celery:
1. Decorate `analyze_commit_job` with `@celery_app.task`.
2. Replace `tasks.add_task(analyze_commit_job, commit.id)` in routes with `.delay()`.
3. Start a Celery worker alongside the FastAPI process.

### Adding notifications

[`backend/app/workers/jobs.py`](backend/app/workers/jobs.py) is the natural place to add notification calls after a portfolio update or PR creation.
Implement a `Notifier` interface and inject it into the pipeline or job.
