from __future__ import annotations

import base64
import logging
import time
from typing import Any

import httpx
from app.core.config import get_settings


log = logging.getLogger(__name__)


def _normalise_private_key(raw: str) -> str:
    """Convert literal \\n sequences (common in .env files) to real newlines."""
    if "\n" not in raw and "\\n" in raw:
        raw = raw.replace("\\n", "\n")
    return raw.strip()


def _make_app_jwt(app_id: str, private_key: str) -> str:
    """Produce a short-lived GitHub App JWT (RS256, 60 s validity)."""
    try:
        import jwt  # PyJWT
    except ImportError as exc:
        raise RuntimeError("PyJWT is required for GitHub App auth: pip install PyJWT[crypto]") from exc

    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + 60, "iss": app_id}
    return jwt.encode(payload, _normalise_private_key(private_key), algorithm="RS256")


class GitHubClient:
    """
    Real GitHub REST client.

    Authentication hierarchy (in priority order):
    1. Explicit ``token`` argument – used as-is (PAT or installation token).
    2. GitHub App credentials (GITHUB_APP_ID + GITHUB_PRIVATE_KEY):
       - Mints a JWT, fetches the first matching installation, then exchanges
         it for a short-lived installation access token.
    3. GITHUB_TOKEN env-var (PAT fallback for local development).
    """

    def __init__(self, token: str | None = None):
        settings = get_settings()

        if token:
            self.token = token
        elif settings.github_app_id and settings.github_private_key:
            try:
                self.token = self._installation_token(
                    settings.github_app_id,
                    _normalise_private_key(settings.github_private_key),
                )
            except Exception as exc:
                # App auth failed (malformed key, no installations, network error, etc.).
                # Fall back to a PAT when one is configured so a broken App key
                # does not block access when the user has a working GITHUB_TOKEN.
                if settings.github_token:
                    log.warning(
                        "GitHub App authentication failed; falling back to GITHUB_TOKEN: %s", exc
                    )
                    self.token = settings.github_token
                else:
                    raise RuntimeError(
                        f"GitHub App authentication failed ({exc}). "
                        "Fix GITHUB_APP_ID / GITHUB_PRIVATE_KEY, or set GITHUB_TOKEN as a fallback."
                    ) from exc
        elif settings.github_token:
            self.token = settings.github_token
        else:
            raise RuntimeError(
                "GitHub credentials are missing. "
                "Set GITHUB_TOKEN (PAT) or GITHUB_APP_ID + GITHUB_PRIVATE_KEY."
            )

        self.client = httpx.Client(
            base_url="https://api.github.com",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30,
        )

    # ------------------------------------------------------------------
    # GitHub App helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _installation_token(app_id: str, private_key: str) -> str:
        """Exchange App JWT for an installation access token."""
        jwt_token = _make_app_jwt(app_id, private_key)
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {jwt_token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        with httpx.Client(base_url="https://api.github.com", headers=headers, timeout=15) as tmp:
            installations = tmp.get("/app/installations").raise_for_status().json()
            if not installations:
                raise RuntimeError("GitHub App has no installations.")
            install_id = installations[0]["id"]
            token_resp = tmp.post(f"/app/installations/{install_id}/access_tokens").raise_for_status().json()
            return token_resp["token"]

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    def _get(self, url: str) -> Any:
        response = self.client.get(url)
        response.raise_for_status()
        return response.json()

    # ------------------------------------------------------------------
    # Repository information
    # ------------------------------------------------------------------

    def repo(self, owner: str, repo: str) -> dict:
        return self._get(f"/repos/{owner}/{repo}")

    def authenticated_account(self) -> dict:
        """Return the account represented by the configured GitHub credential."""
        try:
            return self._get("/user")
        except httpx.HTTPStatusError:
            # GitHub App installation tokens have no `/user` identity. Use the
            # owner of an installed repository as the visible account instead.
            repositories = self.accessible_repositories()
            if repositories:
                return repositories[0].get("owner", {})
            return {}

    def accessible_repositories(self) -> list[dict]:
        """List repositories visible to a PAT or GitHub App installation token."""
        try:
            return self._get("/user/repos?per_page=100&sort=updated&affiliation=owner,collaborator")
        except httpx.HTTPStatusError as user_error:
            # Installation tokens do not have a user context. They can list the
            # repositories selected when the GitHub App was installed instead.
            try:
                return self._get("/installation/repositories?per_page=100").get("repositories", [])
            except httpx.HTTPStatusError:
                raise user_error

    def readme(self, owner: str, repo: str) -> str:
        try:
            data = self._get(f"/repos/{owner}/{repo}/readme")
            return base64.b64decode(data["content"]).decode(errors="replace")
        except httpx.HTTPStatusError:
            return ""

    def recent_commits(self, owner: str, repo: str) -> list[dict]:
        return self._get(f"/repos/{owner}/{repo}/commits?per_page=10")

    def commit(self, owner: str, repo: str, sha: str) -> dict:
        return self._get(f"/repos/{owner}/{repo}/commits/{sha}")

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------

    def file(self, owner: str, repo: str, path: str, ref: str) -> tuple[dict, str]:
        """Returns (metadata_dict, decoded_content).  metadata_dict contains 'sha'."""
        item = self._get(f"/repos/{owner}/{repo}/contents/{path}?ref={ref}")
        return item, base64.b64decode(item["content"]).decode(errors="replace")

    def put_file(
        self,
        owner: str,
        repo: str,
        path: str,
        content: str,
        branch: str,
        sha: str,
        message: str,
    ) -> None:
        body: dict[str, Any] = {
            "message": message,
            "content": base64.b64encode(content.encode()).decode(),
            "branch": branch,
        }
        if sha:
            body["sha"] = sha
        r = self.client.put(f"/repos/{owner}/{repo}/contents/{path}", json=body)
        r.raise_for_status()

    # ------------------------------------------------------------------
    # Branch & PR operations
    # ------------------------------------------------------------------

    def create_branch(self, owner: str, repo: str, branch: str, sha: str) -> None:
        r = self.client.post(
            f"/repos/{owner}/{repo}/git/refs",
            json={"ref": f"refs/heads/{branch}", "sha": sha},
        )
        r.raise_for_status()

    def create_pr(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str,
        branch: str,
        base: str = "main",
    ) -> dict:
        r = self.client.post(
            f"/repos/{owner}/{repo}/pulls",
            json={"title": title, "body": body, "head": branch, "base": base},
        )
        r.raise_for_status()
        return r.json()

    def get_pr(self, owner: str, repo: str, pr_number: int) -> dict:
        return self._get(f"/repos/{owner}/{repo}/pulls/{pr_number}")

    def merge_pr(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        commit_title: str | None = None,
    ) -> dict:
        body: dict[str, Any] = {"merge_method": "squash"}
        if commit_title:
            body["commit_title"] = commit_title
        r = self.client.put(f"/repos/{owner}/{repo}/pulls/{pr_number}/merge", json=body)
        r.raise_for_status()
        return r.json()
