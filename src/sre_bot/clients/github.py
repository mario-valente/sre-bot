"""GitHub API client implementation."""

from datetime import datetime
from typing import Any

import httpx
import structlog

from sre_bot.clients.protocols import GitClient, GitQueryError
from sre_bot.config import get_settings

logger = structlog.get_logger()


class GitHubClient(GitClient):
    """
    HTTP client for GitHub REST API.

    Implements the GitClient protocol for querying GitHub.

    API Documentation:
        https://docs.github.com/en/rest
    """

    BASE_URL = "https://api.github.com"

    def __init__(
        self,
        token: str | None = None,
        timeout: float | None = None,
    ):
        """
        Initialize GitHub client.

        Args:
            token: GitHub Personal Access Token. Defaults to settings.
            timeout: Request timeout in seconds. Defaults to settings.
        """
        settings = get_settings()
        self.token = token or (
            settings.github_token.get_secret_value() if settings.github_token else None
        )
        self.timeout = timeout or settings.query_timeout_seconds
        self.default_org = settings.github_org
        self._log = logger.bind(client="github")

        self.headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            self.headers["Authorization"] = f"Bearer {self.token}"

    async def get_recent_commits(
        self,
        repo: str,
        since: datetime,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        List recent commits on the default branch.

        Endpoint: GET /repos/{owner}/{repo}/commits

        Args:
            repo: Repository name (e.g., "org/repo" or just "repo").
            since: Only include commits after this time.
            limit: Maximum number of commits.

        Returns:
            List of commit information.

        Raises:
            GitQueryError: If the query fails.
        """
        full_repo = self._resolve_repo(repo)
        self._log.debug("fetching commits", repo=full_repo, since=since.isoformat(), limit=limit)

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.BASE_URL}/repos/{full_repo}/commits",
                    params={
                        "since": since.isoformat(),
                        "per_page": limit,
                    },
                    headers=self.headers,
                )
                response.raise_for_status()
                data = response.json()

                commits = self._parse_commits(data)
                self._log.debug("commits fetched", repo=full_repo, count=len(commits))
                return commits

        except httpx.HTTPStatusError as e:
            self._log.error("HTTP error", repo=full_repo, status=e.response.status_code)
            raise GitQueryError(f"GitHub HTTP error: {e.response.status_code}") from e
        except httpx.RequestError as e:
            self._log.error("request error", repo=full_repo, error=str(e))
            raise GitQueryError(f"GitHub request error: {e}") from e

    async def get_recent_prs(
        self,
        repo: str,
        state: str = "merged",
        since: datetime | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        List recent pull requests.

        Endpoint: GET /repos/{owner}/{repo}/pulls

        Args:
            repo: Repository name.
            state: PR state filter ("merged", "open", "closed").
            since: Only include PRs after this time.
            limit: Maximum number of PRs.

        Returns:
            List of pull request information.

        Raises:
            GitQueryError: If the query fails.
        """
        full_repo = self._resolve_repo(repo)
        self._log.debug(
            "fetching PRs",
            repo=full_repo,
            state=state,
            since=since.isoformat() if since else None,
            limit=limit,
        )

        # GitHub API uses "closed" for merged PRs, we filter by merge status
        api_state = "closed" if state == "merged" else state

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.BASE_URL}/repos/{full_repo}/pulls",
                    params={
                        "state": api_state,
                        "sort": "updated",
                        "direction": "desc",
                        "per_page": limit * 2,  # Fetch more to filter
                    },
                    headers=self.headers,
                )
                response.raise_for_status()
                data = response.json()

                prs = self._parse_prs(data, state, since, limit)
                self._log.debug("PRs fetched", repo=full_repo, count=len(prs))
                return prs

        except httpx.HTTPStatusError as e:
            self._log.error("HTTP error", repo=full_repo, status=e.response.status_code)
            raise GitQueryError(f"GitHub HTTP error: {e.response.status_code}") from e
        except httpx.RequestError as e:
            self._log.error("request error", repo=full_repo, error=str(e))
            raise GitQueryError(f"GitHub request error: {e}") from e

    async def get_latest_release(self, repo: str) -> dict[str, Any] | None:
        """
        Fetch the most recent release.

        Endpoint: GET /repos/{owner}/{repo}/releases/latest

        Args:
            repo: Repository name.

        Returns:
            Release information, or None if no releases exist.

        Raises:
            GitQueryError: If the query fails (except 404).
        """
        full_repo = self._resolve_repo(repo)
        self._log.debug("fetching latest release", repo=full_repo)

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.BASE_URL}/repos/{full_repo}/releases/latest",
                    headers=self.headers,
                )

                if response.status_code == 404:
                    self._log.debug("no releases found", repo=full_repo)
                    return None

                response.raise_for_status()
                data = response.json()

                release = self._parse_release(data)
                self._log.debug("release fetched", repo=full_repo, tag=release["tag"])
                return release

        except httpx.HTTPStatusError as e:
            self._log.error("HTTP error", repo=full_repo, status=e.response.status_code)
            raise GitQueryError(f"GitHub HTTP error: {e.response.status_code}") from e
        except httpx.RequestError as e:
            self._log.error("request error", repo=full_repo, error=str(e))
            raise GitQueryError(f"GitHub request error: {e}") from e

    def _resolve_repo(self, repo: str) -> str:
        """
        Resolve repository name to full path.

        If repo doesn't contain '/', prepends the default org.
        """
        if "/" in repo:
            return repo
        if self.default_org:
            return f"{self.default_org}/{repo}"
        raise GitQueryError(
            f"Repository '{repo}' must include owner (e.g., 'org/repo') "
            "or set GITHUB_ORG environment variable."
        )

    def _parse_commits(self, data: list[dict]) -> list[dict[str, Any]]:
        """Parse GitHub commits response."""
        commits = []
        for item in data:
            commit = item.get("commit", {})
            author = commit.get("author", {})
            commits.append(
                {
                    "sha": item.get("sha", "")[:7],  # Short SHA
                    "full_sha": item.get("sha", ""),
                    "message": commit.get("message", "").split("\n")[0],  # First line
                    "author": author.get("name", "unknown"),
                    "timestamp": self._parse_datetime(author.get("date")),
                    "url": item.get("html_url", ""),
                }
            )
        return commits

    def _parse_prs(
        self,
        data: list[dict],
        state: str,
        since: datetime | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Parse GitHub PRs response with filtering."""
        prs = []
        for item in data:
            # Filter merged if requested
            merged_at = item.get("merged_at")
            if state == "merged" and not merged_at:
                continue

            # Filter by time if specified
            if since:
                pr_time = merged_at or item.get("updated_at")
                parsed_time = self._parse_datetime(pr_time) if pr_time else None
                if parsed_time and parsed_time < since:
                    continue

            prs.append(
                {
                    "number": item.get("number", 0),
                    "title": item.get("title", ""),
                    "author": item.get("user", {}).get("login", "unknown"),
                    "merged_at": self._parse_datetime(merged_at) if merged_at else None,
                    "created_at": self._parse_datetime(item.get("created_at")),
                    "url": item.get("html_url", ""),
                    "additions": item.get("additions", 0),
                    "deletions": item.get("deletions", 0),
                    "changed_files": item.get("changed_files", 0),
                }
            )

            if len(prs) >= limit:
                break

        return prs

    def _parse_release(self, data: dict) -> dict[str, Any]:
        """Parse GitHub release response."""
        return {
            "tag": data.get("tag_name", ""),
            "name": data.get("name", ""),
            "published_at": self._parse_datetime(data.get("published_at")),
            "url": data.get("html_url", ""),
            "author": data.get("author", {}).get("login", "unknown"),
            "is_prerelease": data.get("prerelease", False),
        }

    @staticmethod
    def _parse_datetime(value: str | None) -> datetime | None:
        """Parse ISO datetime string."""
        if not value:
            return None
        # GitHub uses ISO format with Z suffix
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
