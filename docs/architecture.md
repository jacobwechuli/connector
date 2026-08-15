# Architecture

The synchronous webhook surface verifies GitHub's HMAC before storing a unique delivery ID. A `BackgroundTasks` job then fetches commit evidence, invokes the configured model provider, and persists an analysis. High-confidence structured operations are validated against the repository mapping and materialized only into approved portfolio data paths. Secret scanning occurs before GitHub branch, content commit, and pull-request calls.

Database records provide the audit chain: webhook event → commit SHA → analysis/prompt/model → portfolio update → diff/branch/PR. `Commit(repository_id, sha)` and `WebhookEvent.delivery_id` are unique, making replay safe.

The GitHub integration is deliberately isolated in `GitHubClient`; GitHub App installation-token minting can be introduced there without changing orchestration. `LLMProvider` similarly isolates OpenAI-compatible structured responses from the pipeline.
