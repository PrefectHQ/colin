"""GitHub provider for fetching files and issues from GitHub repositories."""

from __future__ import annotations

import hashlib
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, ClassVar

import httpx
from pydantic import BaseModel, validate_call

from colin.compiler.cache import get_compile_context
from colin.models import Ref
from colin.providers.base import Provider
from colin.resources import Resource

if TYPE_CHECKING:
    pass


class GitHubEntry(BaseModel):
    """Entry in a GitHub directory listing."""

    path: str
    name: str
    type: str  # "file" or "dir"
    sha: str
    size: int | None = None


class GitHubFileResource(Resource):
    """Resource returned by GitHubProvider.file()."""

    def __init__(
        self,
        content: str,
        ref: Ref,
        path: str,
        repo: str,
        git_ref: str,
        resolved_sha: str,
    ) -> None:
        """Initialize a GitHub file resource.

        Args:
            content: File content.
            ref: The Ref for this resource.
            path: File path in the repository.
            repo: Repository in "owner/repo" format.
            git_ref: Original git ref (branch, tag, or SHA).
            resolved_sha: Resolved commit SHA.
        """
        super().__init__(content, ref)
        self.path = path
        self.repo = repo
        self.git_ref = git_ref
        self.resolved_sha = resolved_sha

    @property
    def version(self) -> str:
        """Use resolved SHA as version."""
        return self.resolved_sha


class GitHubListingResource(Resource):
    """Resource returned by GitHubProvider.ls()."""

    def __init__(
        self,
        content: str,
        ref: Ref,
        path: str,
        repo: str,
        git_ref: str,
        entries: list[GitHubEntry],
        tree_sha: str,
    ) -> None:
        """Initialize a GitHub listing resource.

        Args:
            content: Listing as newline-separated paths.
            ref: The Ref for this resource.
            path: Directory path in the repository.
            repo: Repository in "owner/repo" format.
            git_ref: Original git ref (branch, tag, or SHA).
            entries: List of directory entries.
            tree_sha: Tree SHA for versioning.
        """
        super().__init__(content, ref)
        self.path = path
        self.repo = repo
        self.git_ref = git_ref
        self.entries = entries
        self.tree_sha = tree_sha

    @property
    def version(self) -> str:
        """Use tree SHA as version."""
        return self.tree_sha

    def __iter__(self) -> Any:
        """Allow iteration over entries."""
        return iter(self.entries)


class GitHubIssueResource(Resource):
    """Resource returned by GitHubProvider.issue()."""

    def __init__(
        self,
        content: str,
        ref: Ref,
        repo: str,
        number: int,
        title: str,
        body: str | None,
        state: str,
        labels: list[str],
        assignees: list[str],
        author: str | None,
        url: str,
        updated_at: datetime,
        created_at: datetime,
        closed_at: datetime | None,
        comments_count: int,
    ) -> None:
        """Initialize a GitHub issue resource.

        Args:
            content: Issue formatted as markdown (title + body).
            ref: The Ref for this resource.
            repo: Repository in "owner/repo" format.
            number: Issue number.
            title: Issue title.
            body: Issue body (markdown).
            state: Issue state ("open" or "closed").
            labels: List of label names.
            assignees: List of assignee usernames.
            author: Username of issue creator.
            url: HTML URL to the issue.
            updated_at: When the issue was last updated.
            created_at: When the issue was created.
            closed_at: When the issue was closed (None if open).
            comments_count: Number of comments.
        """
        super().__init__(content, ref)
        self.repo = repo
        self.number = number
        self.title = title
        self.body = body
        self.state = state
        self.labels = labels
        self.assignees = assignees
        self.author = author
        self.url = url
        self.updated_at = updated_at
        self.created_at = created_at
        self.closed_at = closed_at
        self.comments_count = comments_count

    @property
    def version(self) -> str:
        """Use updated_at as version for staleness detection."""
        return self.updated_at.isoformat()


class GitHubPRResource(Resource):
    """Resource returned by GitHubProvider.pr()."""

    def __init__(
        self,
        content: str,
        ref: Ref,
        repo: str,
        number: int,
        title: str,
        body: str | None,
        state: str,
        labels: list[str],
        assignees: list[str],
        author: str | None,
        url: str,
        updated_at: datetime,
        created_at: datetime,
        closed_at: datetime | None,
        merged_at: datetime | None,
        head_ref: str,
        base_ref: str,
        head_sha: str,
        is_draft: bool,
        additions: int,
        deletions: int,
        changed_files: int,
    ) -> None:
        """Initialize a GitHub PR resource.

        Args:
            content: PR formatted as markdown (title + body).
            ref: The Ref for this resource.
            repo: Repository in "owner/repo" format.
            number: PR number.
            title: PR title.
            body: PR body (markdown).
            state: PR state ("open", "closed", or "merged").
            labels: List of label names.
            assignees: List of assignee usernames.
            author: Username of PR creator.
            url: HTML URL to the PR.
            updated_at: When the PR was last updated.
            created_at: When the PR was created.
            closed_at: When the PR was closed (None if open).
            merged_at: When the PR was merged (None if not merged).
            head_ref: Source branch name.
            base_ref: Target branch name.
            head_sha: Current head commit SHA.
            is_draft: Whether the PR is a draft.
            additions: Number of lines added.
            deletions: Number of lines deleted.
            changed_files: Number of files changed.
        """
        super().__init__(content, ref)
        self.repo = repo
        self.number = number
        self.title = title
        self.body = body
        self.state = state
        self.labels = labels
        self.assignees = assignees
        self.author = author
        self.url = url
        self.updated_at = updated_at
        self.created_at = created_at
        self.closed_at = closed_at
        self.merged_at = merged_at
        self.head_ref = head_ref
        self.base_ref = base_ref
        self.head_sha = head_sha
        self.is_draft = is_draft
        self.additions = additions
        self.deletions = deletions
        self.changed_files = changed_files

    @property
    def version(self) -> str:
        """Use updated_at as version for staleness detection."""
        return self.updated_at.isoformat()


class GitHubIssuesResource(Resource):
    """Resource returned by GitHubProvider.issues()."""

    def __init__(
        self,
        content: str,
        ref: Ref,
        issues: list[GitHubIssueResource],
    ) -> None:
        """Initialize a GitHub issues list resource.

        Args:
            content: Newline-separated issue numbers and titles.
            ref: The Ref for this resource.
            issues: List of issue resources.
        """
        super().__init__(content, ref)
        self.issues = issues

    @property
    def version(self) -> str:
        """Version based on all issue numbers and their update times."""
        parts = sorted(f"{i.number}:{i.updated_at.isoformat()}" for i in self.issues)
        combined = "\n".join(parts)
        return hashlib.sha256(combined.encode()).hexdigest()[:16]

    def __iter__(self) -> Any:
        """Allow iteration over issues."""
        return iter(self.issues)

    def __len__(self) -> int:
        """Return number of issues."""
        return len(self.issues)


class GitHubPRsResource(Resource):
    """Resource returned by GitHubProvider.prs()."""

    def __init__(
        self,
        content: str,
        ref: Ref,
        prs: list[GitHubPRResource],
    ) -> None:
        """Initialize a GitHub PRs list resource.

        Args:
            content: Newline-separated PR numbers and titles.
            ref: The Ref for this resource.
            prs: List of PR resources.
        """
        super().__init__(content, ref)
        self.prs = prs

    @property
    def version(self) -> str:
        """Version based on all PR numbers and their update times."""
        parts = sorted(f"{p.number}:{p.updated_at.isoformat()}" for p in self.prs)
        combined = "\n".join(parts)
        return hashlib.sha256(combined.encode()).hexdigest()[:16]

    def __iter__(self) -> Any:
        """Allow iteration over PRs."""
        return iter(self.prs)

    def __len__(self) -> int:
        """Return number of PRs."""
        return len(self.prs)


class GitHubProvider(Provider):
    """Provider for fetching files from GitHub repositories.

    Template usage (default provider, no config needed):
        {{ colin.github.file("owner/repo", "README.md").content }}
        {{ colin.github.file("owner/repo", "src/main.py", ref="v1.0").content }}

    Template usage (named instance with pre-configured repo):
        {{ colin.github.myrepo.file("README.md").content }}
        {{ colin.github.myrepo.file("src/main.py", ref="v1.0").content }}

    Configuration:
        [[providers.github]]
        name = "myrepo"
        repo = "owner/repo"      # Pre-configured repo
        token = "${GITHUB_TOKEN}"  # Optional, for private repos / rate limits
    """

    namespace: ClassVar[str] = "github"

    repo: str | None = None
    """Repository in "owner/repo" format. Optional for default provider."""

    token: str | None = None
    """GitHub token for private repos and higher rate limits."""

    _client: httpx.AsyncClient | None = None
    _sha_cache: dict[str, str] | None = None
    _connection: str = ""

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        """Manage HTTP client lifecycle."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            self._client = client
            self._sha_cache = {}
            yield
        self._client = None
        self._sha_cache = None

    def _require_client(self) -> httpx.AsyncClient:
        """Get client, raising if not initialized."""
        if self._client is None:
            raise RuntimeError("GitHubProvider not initialized - use within lifespan context")
        return self._client

    def _headers(self) -> dict[str, str]:
        """Build request headers."""
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _resolve_repo_and_path(self, repo_or_path: str, path: str | None) -> tuple[str, str]:
        """Resolve repo and path from arguments.

        Args:
            repo_or_path: Either "owner/repo" (if path given) or file path (if repo configured).
            path: File path when repo_or_path is a repo, None otherwise.

        Returns:
            Tuple of (repo, path).

        Raises:
            ValueError: If repo cannot be determined.
        """
        if path is not None:
            # repo_or_path is the repo, path is the file path
            return repo_or_path, path
        elif self.repo is not None:
            # repo_or_path is the file path, use configured repo
            return self.repo, repo_or_path
        else:
            raise ValueError(
                "No repository specified. Either configure a repo in colin.toml "
                "or use github.file('owner/repo', 'path')."
            )

    async def _resolve_ref(self, repo: str, ref: str) -> str:
        """Resolve a git ref to a commit SHA.

        Uses caching to avoid repeated API calls for the same ref.

        Args:
            repo: Repository in "owner/repo" format.
            ref: Git ref (branch, tag, or SHA).

        Returns:
            Resolved commit SHA.
        """
        if self._sha_cache is None:
            self._sha_cache = {}

        cache_key = f"{repo}:{ref}"
        if cache_key in self._sha_cache:
            return self._sha_cache[cache_key]

        client = self._require_client()
        url = f"https://api.github.com/repos/{repo}/commits/{ref}"

        response = await client.get(url, headers=self._headers())

        if response.status_code == 404:
            raise FileNotFoundError(f"Ref not found: {ref} in {repo}")

        if response.status_code == 401:
            raise PermissionError(
                f"Authentication required for {repo}. Set token in provider config."
            )

        if response.status_code == 403:
            raise PermissionError(
                f"Access denied or rate limited for {repo}. "
                "Consider setting a GitHub token for higher rate limits."
            )

        response.raise_for_status()

        sha = response.json()["sha"]
        self._sha_cache[cache_key] = sha
        return sha

    async def _fetch_file(self, repo: str, path: str, sha: str) -> str:
        """Fetch file content from GitHub.

        For public repos (no token), uses raw.githubusercontent.com for speed.
        For authenticated requests (with token), uses the API to access private repos.

        Args:
            repo: Repository in "owner/repo" format.
            path: File path in the repository.
            sha: Commit SHA.

        Returns:
            File content as string.
        """
        client = self._require_client()

        if self.token:
            # Use API with auth for private repo access
            url = f"https://api.github.com/repos/{repo}/contents/{path}"
            headers = self._headers()
            headers["Accept"] = "application/vnd.github.raw+json"
            response = await client.get(url, params={"ref": sha}, headers=headers)
        else:
            # Use raw.githubusercontent.com for public repos (faster, no rate limit)
            url = f"https://raw.githubusercontent.com/{repo}/{sha}/{path}"
            response = await client.get(url)

        if response.status_code == 404:
            raise FileNotFoundError(f"File not found: {path} at {sha[:7]} in {repo}")

        response.raise_for_status()
        return response.text

    def _parse_issue_or_pr_url(self, url: str) -> tuple[str, int, str]:
        """Parse a GitHub issue or PR URL.

        Args:
            url: Full GitHub URL like https://github.com/owner/repo/issues/123
                or https://github.com/owner/repo/pull/456.

        Returns:
            Tuple of (repo, number, type) where type is "issue" or "pr".

        Raises:
            ValueError: If URL format is invalid.
        """
        pattern = r"https?://github\.com/([^/]+/[^/]+)/(issues|pull)/(\d+)"
        match = re.match(pattern, url)
        if not match:
            raise ValueError(f"Invalid GitHub URL: {url}")
        repo = match.group(1)
        url_type = "pr" if match.group(2) == "pull" else "issue"
        number = int(match.group(3))
        return repo, number, url_type

    def _resolve_repo_and_number(
        self, number_or_url: str | int, repo: str | int | None
    ) -> tuple[str, int]:
        """Resolve repo and number from arguments.

        Supports multiple call patterns:
        - issue(123) - number only, uses configured repo
        - issue("owner/repo", 123) - repo first, then number
        - issue("https://...") - full URL

        Args:
            number_or_url: Issue/PR number, repo string, or full GitHub URL.
            repo: Number when first arg is repo, or repo string, or None.

        Returns:
            Tuple of (repo, number).

        Raises:
            ValueError: If repo cannot be determined.
        """
        # If it's a URL, parse it
        if isinstance(number_or_url, str) and number_or_url.startswith("http"):
            parsed_repo, number, _ = self._parse_issue_or_pr_url(number_or_url)
            return parsed_repo, number

        # If repo is an int, first arg is the repo string
        if isinstance(repo, int):
            return str(number_or_url), repo

        # If first arg looks like a repo (contains /), swap the arguments
        if isinstance(number_or_url, str) and "/" in number_or_url and repo is None:
            raise ValueError(
                f"Issue/PR number required. Use github.issue('{number_or_url}', NUMBER)."
            )

        # Convert to int
        number = int(number_or_url)

        # Determine repo
        if repo is not None:
            return repo, number
        elif self.repo is not None:
            return self.repo, number
        else:
            raise ValueError(
                "No repository specified. Either configure a repo in colin.toml "
                "or use github.issue('owner/repo', 123)."
            )

    def _parse_timestamp(self, timestamp: str | None) -> datetime:
        """Parse ISO timestamp from GitHub API response.

        Args:
            timestamp: ISO format timestamp string.

        Returns:
            Parsed datetime (UTC). Falls back to epoch if None or invalid.
        """
        if timestamp:
            try:
                # GitHub uses Z suffix for UTC
                ts = timestamp.replace("Z", "+00:00")
                return datetime.fromisoformat(ts)
            except ValueError:
                pass
        return datetime(1970, 1, 1, tzinfo=timezone.utc)

    async def _fetch_issue(self, repo: str, number: int) -> dict[str, Any]:
        """Fetch raw issue data from GitHub API.

        Args:
            repo: Repository in "owner/repo" format.
            number: Issue number.

        Returns:
            Raw issue data from API.
        """
        client = self._require_client()
        url = f"https://api.github.com/repos/{repo}/issues/{number}"
        response = await client.get(url, headers=self._headers())

        if response.status_code == 404:
            raise FileNotFoundError(f"Issue not found: #{number} in {repo}")
        if response.status_code == 401:
            raise PermissionError(
                f"Authentication required for {repo}. Set token in provider config."
            )
        if response.status_code == 403:
            raise PermissionError(
                f"Access denied or rate limited for {repo}. "
                "Consider setting a GitHub token for higher rate limits."
            )
        response.raise_for_status()
        return response.json()

    async def _fetch_pr(self, repo: str, number: int) -> dict[str, Any]:
        """Fetch raw PR data from GitHub API.

        Args:
            repo: Repository in "owner/repo" format.
            number: PR number.

        Returns:
            Raw PR data from API.
        """
        client = self._require_client()
        url = f"https://api.github.com/repos/{repo}/pulls/{number}"
        response = await client.get(url, headers=self._headers())

        if response.status_code == 404:
            raise FileNotFoundError(f"PR not found: #{number} in {repo}")
        if response.status_code == 401:
            raise PermissionError(
                f"Authentication required for {repo}. Set token in provider config."
            )
        if response.status_code == 403:
            raise PermissionError(
                f"Access denied or rate limited for {repo}. "
                "Consider setting a GitHub token for higher rate limits."
            )
        response.raise_for_status()
        return response.json()

    async def _fetch_issues(
        self, repo: str, state: str, labels: list[str] | None, assignee: str | None, limit: int
    ) -> list[dict[str, Any]]:
        """Fetch issues list from GitHub API.

        Args:
            repo: Repository in "owner/repo" format.
            state: Filter by state (open, closed, all).
            labels: Filter by labels.
            assignee: Filter by assignee.
            limit: Maximum number of issues.

        Returns:
            List of raw issue data (excluding PRs).
        """
        client = self._require_client()
        url = f"https://api.github.com/repos/{repo}/issues"
        params: dict[str, Any] = {
            "state": state,
            "per_page": min(limit, 100),
            "sort": "updated",
            "direction": "desc",
        }
        if labels:
            params["labels"] = ",".join(labels)
        if assignee:
            params["assignee"] = assignee

        response = await client.get(url, params=params, headers=self._headers())

        if response.status_code == 404:
            raise FileNotFoundError(f"Repository not found: {repo}")
        if response.status_code == 401:
            raise PermissionError(
                f"Authentication required for {repo}. Set token in provider config."
            )
        if response.status_code == 403:
            raise PermissionError(
                f"Access denied or rate limited for {repo}. "
                "Consider setting a GitHub token for higher rate limits."
            )
        response.raise_for_status()

        # Filter out PRs (they have a pull_request field)
        items = response.json()
        issues = [item for item in items if "pull_request" not in item]
        return issues[:limit]

    async def _fetch_prs(
        self, repo: str, state: str, base: str | None, head: str | None, limit: int
    ) -> list[dict[str, Any]]:
        """Fetch PRs list from GitHub API.

        Args:
            repo: Repository in "owner/repo" format.
            state: Filter by state (open, closed, all).
            base: Filter by base branch.
            head: Filter by head branch.
            limit: Maximum number of PRs.

        Returns:
            List of raw PR data.
        """
        client = self._require_client()
        url = f"https://api.github.com/repos/{repo}/pulls"
        params: dict[str, Any] = {
            "state": state,
            "per_page": min(limit, 100),
            "sort": "updated",
            "direction": "desc",
        }
        if base:
            params["base"] = base
        if head:
            params["head"] = head

        response = await client.get(url, params=params, headers=self._headers())

        if response.status_code == 404:
            raise FileNotFoundError(f"Repository not found: {repo}")
        if response.status_code == 401:
            raise PermissionError(
                f"Authentication required for {repo}. Set token in provider config."
            )
        if response.status_code == 403:
            raise PermissionError(
                f"Access denied or rate limited for {repo}. "
                "Consider setting a GitHub token for higher rate limits."
            )
        response.raise_for_status()

        return response.json()[:limit]

    @validate_call
    async def file(
        self,
        repo_or_path: str,
        path: str | None = None,
        *,
        ref: str = "HEAD",
        watch: bool = True,
    ) -> GitHubFileResource:
        """Fetch a file from a GitHub repository.

        Template usage (default provider, no config needed):
            {{ colin.github.file("owner/repo", "README.md").content }}
            {{ colin.github.file("owner/repo", "src/main.py", ref="v1.0").content }}

        Template usage (named instance with pre-configured repo):
            {{ colin.github.myrepo.file("README.md").content }}
            {{ colin.github.myrepo.file("src/main.py", ref="v1.0").content }}

        Args:
            repo_or_path: Repository ("owner/repo") if no repo configured,
                otherwise file path in the repository.
            path: File path when repo is first arg, None when using configured repo.
            ref: Git ref (branch, tag, or SHA). Defaults to HEAD.
            watch: Whether to track this ref for staleness.

        Returns:
            GitHubFileResource with content and metadata.
        """
        repo, file_path = self._resolve_repo_and_path(repo_or_path, path)

        resolved_sha = await self._resolve_ref(repo, ref)
        content = await self._fetch_file(repo, file_path, resolved_sha)

        colin_ref = Ref(
            provider=self.namespace,
            connection=self._connection,
            method="file",
            args={"repo": repo, "path": file_path, "ref": ref},
        )

        resource = GitHubFileResource(
            content=content,
            ref=colin_ref,
            path=file_path,
            repo=repo,
            git_ref=ref,
            resolved_sha=resolved_sha,
        )

        if watch:
            ctx = get_compile_context()
            if ctx:
                ctx.track(colin_ref, resource.version)

        return resource

    @validate_call
    async def ls(
        self,
        repo_or_path: str = "",
        path: str | None = None,
        *,
        ref: str = "HEAD",
        watch: bool = True,
    ) -> GitHubListingResource:
        """List directory contents in a GitHub repository.

        Template usage (default provider, no config needed):
            {% for entry in colin.github.ls("owner/repo", "src/") %}
            - {{ entry.name }} ({{ entry.type }})
            {% endfor %}

        Template usage (named instance with pre-configured repo):
            {% for entry in colin.github.myrepo.ls("src/") %}
            - {{ entry.name }} ({{ entry.type }})
            {% endfor %}

        Args:
            repo_or_path: Repository ("owner/repo") if no repo configured,
                otherwise directory path in the repository.
            path: Directory path when repo is first arg, None when using configured repo.
            ref: Git ref (branch, tag, or SHA). Defaults to HEAD.
            watch: Whether to track this ref for staleness.

        Returns:
            GitHubListingResource with entries and metadata.
        """
        # Handle special case: ls() with no args on configured provider lists root
        if repo_or_path == "" and path is None and self.repo is not None:
            repo = self.repo
            dir_path = ""
        else:
            repo, dir_path = self._resolve_repo_and_path(repo_or_path, path)

        resolved_sha = await self._resolve_ref(repo, ref)

        client = self._require_client()
        url = f"https://api.github.com/repos/{repo}/contents/{dir_path}"

        response = await client.get(
            url,
            params={"ref": resolved_sha},
            headers=self._headers(),
        )

        if response.status_code == 404:
            raise FileNotFoundError(f"Path not found: {dir_path} at {ref} in {repo}")

        response.raise_for_status()

        items = response.json()

        # Handle case where path is a file, not a directory
        if isinstance(items, dict):
            raise ValueError(f"Path is a file, not a directory: {dir_path}")

        entries = [
            GitHubEntry(
                path=item["path"],
                name=item["name"],
                type="dir" if item["type"] == "dir" else "file",
                sha=item["sha"],
                size=item.get("size"),
            )
            for item in items
        ]

        colin_ref = Ref(
            provider=self.namespace,
            connection=self._connection,
            method="ls",
            args={"repo": repo, "path": dir_path, "ref": ref},
        )

        resource = GitHubListingResource(
            content="\n".join(e.path for e in entries),
            ref=colin_ref,
            path=dir_path,
            repo=repo,
            git_ref=ref,
            entries=entries,
            tree_sha=resolved_sha,
        )

        if watch:
            ctx = get_compile_context()
            if ctx:
                ctx.track(colin_ref, resource.version)

        return resource

    @validate_call
    async def issue(
        self,
        number_or_url: str | int,
        repo: str | int | None = None,
        *,
        watch: bool = True,
    ) -> GitHubIssueResource:
        """Fetch a GitHub issue by number or URL.

        Template usage:
            {{ colin.github.issue(123).title }}
            {{ colin.github.issue("owner/repo", 123).content }}
            {{ colin.github.issue("https://github.com/owner/repo/issues/123").state }}

        Args:
            number_or_url: Issue number, or full GitHub URL.
            repo: Repository in "owner/repo" format. Required if number given
                and no repo configured on provider.
            watch: Whether to track this ref for staleness (default True).

        Returns:
            GitHubIssueResource with issue content and metadata.
        """
        resolved_repo, number = self._resolve_repo_and_number(number_or_url, repo)
        data = await self._fetch_issue(resolved_repo, number)

        # Build content as markdown
        title = data.get("title", "")
        body = data.get("body") or ""
        content = f"# {title}\n\n{body}" if body else f"# {title}"

        colin_ref = Ref(
            provider=self.namespace,
            connection=self._connection,
            method="issue",
            args={"number_or_url": number, "repo": resolved_repo},
        )

        resource = GitHubIssueResource(
            content=content,
            ref=colin_ref,
            repo=resolved_repo,
            number=data["number"],
            title=title,
            body=body or None,
            state=data.get("state", "open"),
            labels=[label["name"] for label in data.get("labels", [])],
            assignees=[a["login"] for a in data.get("assignees", [])],
            author=data.get("user", {}).get("login"),
            url=data.get("html_url", ""),
            updated_at=self._parse_timestamp(data.get("updated_at")),
            created_at=self._parse_timestamp(data.get("created_at")),
            closed_at=self._parse_timestamp(data.get("closed_at"))
            if data.get("closed_at")
            else None,
            comments_count=data.get("comments", 0),
        )

        if watch:
            ctx = get_compile_context()
            if ctx:
                ctx.track(colin_ref, resource.version)

        return resource

    @validate_call
    async def pr(
        self,
        number_or_url: str | int,
        repo: str | int | None = None,
        *,
        watch: bool = True,
    ) -> GitHubPRResource:
        """Fetch a GitHub pull request by number or URL.

        Template usage:
            {{ colin.github.pr(456).title }}
            {{ colin.github.pr("owner/repo", 456).head_ref }}
            {{ colin.github.pr("https://github.com/owner/repo/pull/456").state }}

        Args:
            number_or_url: PR number, or full GitHub URL.
            repo: Repository in "owner/repo" format. Required if number given
                and no repo configured on provider.
            watch: Whether to track this ref for staleness (default True).

        Returns:
            GitHubPRResource with PR content and metadata.
        """
        resolved_repo, number = self._resolve_repo_and_number(number_or_url, repo)
        data = await self._fetch_pr(resolved_repo, number)

        # Build content as markdown
        title = data.get("title", "")
        body = data.get("body") or ""
        content = f"# {title}\n\n{body}" if body else f"# {title}"

        # Determine state (open, closed, or merged)
        state = data.get("state", "open")
        if state == "closed" and data.get("merged_at"):
            state = "merged"

        colin_ref = Ref(
            provider=self.namespace,
            connection=self._connection,
            method="pr",
            args={"number_or_url": number, "repo": resolved_repo},
        )

        resource = GitHubPRResource(
            content=content,
            ref=colin_ref,
            repo=resolved_repo,
            number=data["number"],
            title=title,
            body=body or None,
            state=state,
            labels=[label["name"] for label in data.get("labels", [])],
            assignees=[a["login"] for a in data.get("assignees", [])],
            author=data.get("user", {}).get("login"),
            url=data.get("html_url", ""),
            updated_at=self._parse_timestamp(data.get("updated_at")),
            created_at=self._parse_timestamp(data.get("created_at")),
            closed_at=self._parse_timestamp(data.get("closed_at"))
            if data.get("closed_at")
            else None,
            merged_at=self._parse_timestamp(data.get("merged_at"))
            if data.get("merged_at")
            else None,
            head_ref=data.get("head", {}).get("ref", ""),
            base_ref=data.get("base", {}).get("ref", ""),
            head_sha=data.get("head", {}).get("sha", ""),
            is_draft=data.get("draft", False),
            additions=data.get("additions", 0),
            deletions=data.get("deletions", 0),
            changed_files=data.get("changed_files", 0),
        )

        if watch:
            ctx = get_compile_context()
            if ctx:
                ctx.track(colin_ref, resource.version)

        return resource

    @validate_call
    async def issues(
        self,
        repo: str | None = None,
        *,
        state: str = "open",
        labels: list[str] | None = None,
        assignee: str | None = None,
        limit: int = 30,
        watch: bool = True,
    ) -> GitHubIssuesResource:
        """List GitHub issues with filtering.

        Template usage:
            {% for issue in colin.github.issues() %}
                #{{ issue.number }}: {{ issue.title }}
            {% endfor %}

            {% for issue in colin.github.issues("owner/repo", labels=["bug"]) %}
                {{ issue.title }} - {{ issue.state }}
            {% endfor %}

        Args:
            repo: Repository in "owner/repo" format. Uses configured repo if None.
            state: Filter by state ("open", "closed", "all"). Default: "open".
            labels: Filter by labels.
            assignee: Filter by assignee username (or "none", "*").
            limit: Maximum number of issues (default 30).
            watch: Whether to track this ref for staleness (default True).

        Returns:
            GitHubIssuesResource with matching issues.
        """
        resolved_repo = repo or self.repo
        if resolved_repo is None:
            raise ValueError(
                "No repository specified. Either configure a repo in colin.toml "
                "or use github.issues('owner/repo')."
            )

        items = await self._fetch_issues(resolved_repo, state, labels, assignee, limit)

        # Build issue resources
        issue_resources: list[GitHubIssueResource] = []
        for data in items:
            title = data.get("title", "")
            body = data.get("body") or ""
            issue_content = f"# {title}\n\n{body}" if body else f"# {title}"

            issue_ref = Ref(
                provider=self.namespace,
                connection=self._connection,
                method="issue",
                args={"number_or_url": data["number"], "repo": resolved_repo},
            )

            issue_resources.append(
                GitHubIssueResource(
                    content=issue_content,
                    ref=issue_ref,
                    repo=resolved_repo,
                    number=data["number"],
                    title=title,
                    body=body or None,
                    state=data.get("state", "open"),
                    labels=[label["name"] for label in data.get("labels", [])],
                    assignees=[a["login"] for a in data.get("assignees", [])],
                    author=data.get("user", {}).get("login"),
                    url=data.get("html_url", ""),
                    updated_at=self._parse_timestamp(data.get("updated_at")),
                    created_at=self._parse_timestamp(data.get("created_at")),
                    closed_at=self._parse_timestamp(data.get("closed_at"))
                    if data.get("closed_at")
                    else None,
                    comments_count=data.get("comments", 0),
                )
            )

        # Build content as list of issue summaries
        content_lines = [f"#{i.number}: {i.title}" for i in issue_resources]
        content = "\n".join(content_lines)

        colin_ref = Ref(
            provider=self.namespace,
            connection=self._connection,
            method="issues",
            args={
                k: v
                for k, v in {
                    "repo": resolved_repo,
                    "state": state,
                    "labels": labels,
                    "assignee": assignee,
                    "limit": limit,
                }.items()
                if v is not None
            },
        )

        resource = GitHubIssuesResource(
            content=content,
            ref=colin_ref,
            issues=issue_resources,
        )

        if watch:
            ctx = get_compile_context()
            if ctx:
                ctx.track(colin_ref, resource.version)

        return resource

    @validate_call
    async def prs(
        self,
        repo: str | None = None,
        *,
        state: str = "open",
        base: str | None = None,
        head: str | None = None,
        limit: int = 30,
        watch: bool = True,
    ) -> GitHubPRsResource:
        """List GitHub pull requests with filtering.

        Template usage:
            {% for pr in colin.github.prs() %}
                #{{ pr.number }}: {{ pr.title }} ({{ pr.head_ref }} -> {{ pr.base_ref }})
            {% endfor %}

            {% for pr in colin.github.prs("owner/repo", state="open", base="main") %}
                {{ pr.title }} - {{ pr.state }}
            {% endfor %}

        Args:
            repo: Repository in "owner/repo" format. Uses configured repo if None.
            state: Filter by state ("open", "closed", "all"). Default: "open".
            base: Filter by base branch.
            head: Filter by head branch.
            limit: Maximum number of PRs (default 30).
            watch: Whether to track this ref for staleness (default True).

        Returns:
            GitHubPRsResource with matching PRs.
        """
        resolved_repo = repo or self.repo
        if resolved_repo is None:
            raise ValueError(
                "No repository specified. Either configure a repo in colin.toml "
                "or use github.prs('owner/repo')."
            )

        items = await self._fetch_prs(resolved_repo, state, base, head, limit)

        # Build PR resources
        pr_resources: list[GitHubPRResource] = []
        for data in items:
            title = data.get("title", "")
            body = data.get("body") or ""
            pr_content = f"# {title}\n\n{body}" if body else f"# {title}"

            # Determine state
            pr_state = data.get("state", "open")
            if pr_state == "closed" and data.get("merged_at"):
                pr_state = "merged"

            pr_ref = Ref(
                provider=self.namespace,
                connection=self._connection,
                method="pr",
                args={"number_or_url": data["number"], "repo": resolved_repo},
            )

            pr_resources.append(
                GitHubPRResource(
                    content=pr_content,
                    ref=pr_ref,
                    repo=resolved_repo,
                    number=data["number"],
                    title=title,
                    body=body or None,
                    state=pr_state,
                    labels=[label["name"] for label in data.get("labels", [])],
                    assignees=[a["login"] for a in data.get("assignees", [])],
                    author=data.get("user", {}).get("login"),
                    url=data.get("html_url", ""),
                    updated_at=self._parse_timestamp(data.get("updated_at")),
                    created_at=self._parse_timestamp(data.get("created_at")),
                    closed_at=self._parse_timestamp(data.get("closed_at"))
                    if data.get("closed_at")
                    else None,
                    merged_at=self._parse_timestamp(data.get("merged_at"))
                    if data.get("merged_at")
                    else None,
                    head_ref=data.get("head", {}).get("ref", ""),
                    base_ref=data.get("base", {}).get("ref", ""),
                    head_sha=data.get("head", {}).get("sha", ""),
                    is_draft=data.get("draft", False),
                    additions=data.get("additions", 0),
                    deletions=data.get("deletions", 0),
                    changed_files=data.get("changed_files", 0),
                )
            )

        # Build content as list of PR summaries
        content_lines = [
            f"#{p.number}: {p.title} ({p.head_ref} -> {p.base_ref})" for p in pr_resources
        ]
        content = "\n".join(content_lines)

        colin_ref = Ref(
            provider=self.namespace,
            connection=self._connection,
            method="prs",
            args={
                k: v
                for k, v in {
                    "repo": resolved_repo,
                    "state": state,
                    "base": base,
                    "head": head,
                    "limit": limit,
                }.items()
                if v is not None
            },
        )

        resource = GitHubPRsResource(
            content=content,
            ref=colin_ref,
            prs=pr_resources,
        )

        if watch:
            ctx = get_compile_context()
            if ctx:
                ctx.track(colin_ref, resource.version)

        return resource

    async def get_ref_version(self, ref: Ref) -> str:
        """Get current version for a ref.

        For file/ls refs, re-resolves the git ref.
        For issue/pr refs, re-fetches and returns updated_at.

        Args:
            ref: The Ref to check.

        Returns:
            Current version string.
        """
        if ref.method in ("issue", "pr", "issues", "prs"):
            # Re-fetch to get current version
            resource = await self._load_ref(ref)
            return resource.version

        # File/ls methods use git ref resolution
        repo = ref.args.get("repo") or self.repo
        if repo is None:
            raise ValueError("No repository in ref args or provider config")
        git_ref = ref.args.get("ref", "HEAD")
        # Clear cache to get fresh resolution
        cache_key = f"{repo}:{git_ref}"
        if self._sha_cache is not None and cache_key in self._sha_cache:
            del self._sha_cache[cache_key]
        return await self._resolve_ref(repo, git_ref)

    def get_functions(self) -> dict[str, Callable[..., Awaitable[object]]]:
        return {
            "file": self.file,
            "ls": self.ls,
            "issue": self.issue,
            "pr": self.pr,
            "issues": self.issues,
            "prs": self.prs,
        }
