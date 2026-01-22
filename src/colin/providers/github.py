"""GitHub provider for fetching files from GitHub repositories."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
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

    async def get_ref_version(self, ref: Ref) -> str:
        """Get current version for a ref by re-resolving the git ref.

        Args:
            ref: The Ref to check.

        Returns:
            Current resolved SHA.
        """
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
        return {"file": self.file, "ls": self.ls}
