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

    Template usage:
        {{ github.myrepo.file("README.md") }}
        {{ github.myrepo.file("src/main.py", ref="v1.0") }}

    Configuration:
        [[providers.github]]
        name = "myrepo"
        repo = "owner/repo"
        token = "${GITHUB_TOKEN}"  # Optional
    """

    namespace: ClassVar[str] = "github"

    repo: str
    """Repository in "owner/repo" format."""

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

    async def _resolve_ref(self, ref: str) -> str:
        """Resolve a git ref to a commit SHA.

        Uses caching to avoid repeated API calls for the same ref.

        Args:
            ref: Git ref (branch, tag, or SHA).

        Returns:
            Resolved commit SHA.
        """
        if self._sha_cache is None:
            self._sha_cache = {}

        if ref in self._sha_cache:
            return self._sha_cache[ref]

        client = self._require_client()
        url = f"https://api.github.com/repos/{self.repo}/commits/{ref}"

        response = await client.get(url, headers=self._headers())

        if response.status_code == 404:
            raise FileNotFoundError(f"Ref not found: {ref} in {self.repo}")

        if response.status_code == 401:
            raise PermissionError(
                f"Authentication required for {self.repo}. Set token in provider config."
            )

        if response.status_code == 403:
            raise PermissionError(
                f"Access denied or rate limited for {self.repo}. "
                "Consider setting a GitHub token for higher rate limits."
            )

        response.raise_for_status()

        sha = response.json()["sha"]
        self._sha_cache[ref] = sha
        return sha

    async def _fetch_raw(self, path: str, sha: str) -> str:
        """Fetch file content from raw.githubusercontent.com.

        Args:
            path: File path in the repository.
            sha: Commit SHA.

        Returns:
            File content as string.
        """
        client = self._require_client()
        url = f"https://raw.githubusercontent.com/{self.repo}/{sha}/{path}"

        response = await client.get(url)

        if response.status_code == 404:
            raise FileNotFoundError(f"File not found: {path} at {sha[:7]} in {self.repo}")

        response.raise_for_status()
        return response.text

    @validate_call
    async def file(self, path: str, ref: str = "HEAD", watch: bool = True) -> GitHubFileResource:
        """Fetch a file from the GitHub repository.

        Template usage:
            {{ github.myrepo.file("README.md") }}
            {{ github.myrepo.file("src/main.py", ref="v1.0") }}

        Args:
            path: File path in the repository.
            ref: Git ref (branch, tag, or SHA). Defaults to HEAD.
            watch: Whether to track this ref for staleness.

        Returns:
            GitHubFileResource with content and metadata.
        """
        resolved_sha = await self._resolve_ref(ref)
        content = await self._fetch_raw(path, resolved_sha)

        colin_ref = Ref(
            provider=self.namespace,
            connection=self._connection,
            method="file",
            args={"path": path, "ref": ref},
        )

        resource = GitHubFileResource(
            content=content,
            ref=colin_ref,
            path=path,
            repo=self.repo,
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
        self, path: str = "", ref: str = "HEAD", watch: bool = True
    ) -> GitHubListingResource:
        """List directory contents in the GitHub repository.

        Template usage:
            {% for entry in github.myrepo.ls("src/") %}
            - {{ entry.name }} ({{ entry.type }})
            {% endfor %}

        Args:
            path: Directory path in the repository. Empty string for root.
            ref: Git ref (branch, tag, or SHA). Defaults to HEAD.
            watch: Whether to track this ref for staleness.

        Returns:
            GitHubListingResource with entries and metadata.
        """
        resolved_sha = await self._resolve_ref(ref)

        client = self._require_client()
        url = f"https://api.github.com/repos/{self.repo}/contents/{path}"

        response = await client.get(
            url,
            params={"ref": resolved_sha},
            headers=self._headers(),
        )

        if response.status_code == 404:
            raise FileNotFoundError(f"Path not found: {path} at {ref} in {self.repo}")

        response.raise_for_status()

        items = response.json()

        # Handle case where path is a file, not a directory
        if isinstance(items, dict):
            raise ValueError(f"Path is a file, not a directory: {path}")

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
            args={"path": path, "ref": ref},
        )

        resource = GitHubListingResource(
            content="\n".join(e.path for e in entries),
            ref=colin_ref,
            path=path,
            repo=self.repo,
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
        git_ref = ref.args.get("ref", "HEAD")
        # Clear cache to get fresh resolution
        if self._sha_cache is not None and git_ref in self._sha_cache:
            del self._sha_cache[git_ref]
        return await self._resolve_ref(git_ref)

    def get_functions(self) -> dict[str, Callable[..., Awaitable[object]]]:
        return {"file": self.file, "ls": self.ls}
