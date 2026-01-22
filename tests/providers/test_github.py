"""Tests for GitHub provider."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from colin.models import Ref
from colin.providers.github import (
    GitHubEntry,
    GitHubFileResource,
    GitHubListingResource,
    GitHubProvider,
)


class TestGitHubFileResource:
    """Tests for GitHubFileResource class."""

    def test_version_uses_resolved_sha(self) -> None:
        """version returns the resolved SHA."""
        ref = Ref(
            provider="github",
            connection="myrepo",
            method="file",
            args={"path": "README.md", "ref": "main"},
        )
        resource = GitHubFileResource(
            content="# Hello",
            ref=ref,
            path="README.md",
            repo="owner/repo",
            git_ref="main",
            resolved_sha="abc123def456",
        )

        assert resource.version == "abc123def456"

    def test_str_returns_descriptive_string(self) -> None:
        """__str__ returns a descriptive string, not content."""
        ref = Ref(
            provider="github",
            connection="myrepo",
            method="file",
            args={"path": "README.md", "ref": "main"},
        )
        resource = GitHubFileResource(
            content="# Hello World",
            ref=ref,
            path="README.md",
            repo="owner/repo",
            git_ref="main",
            resolved_sha="abc123",
        )

        result = str(resource)
        assert result.startswith("<GitHubFileResource(")
        assert result.endswith(")>")
        assert resource.content == "# Hello World"

    def test_ref_returns_valid_ref(self) -> None:
        """ref() returns a Ref with correct fields."""
        ref = Ref(
            provider="github",
            connection="myrepo",
            method="file",
            args={"path": "src/main.py", "ref": "v1.0"},
        )
        resource = GitHubFileResource(
            content="print('hello')",
            ref=ref,
            path="src/main.py",
            repo="owner/repo",
            git_ref="v1.0",
            resolved_sha="abc123",
        )

        result = resource.ref()

        assert result.provider == "github"
        assert result.connection == "myrepo"
        assert result.method == "file"
        assert result.args["path"] == "src/main.py"
        assert result.args["ref"] == "v1.0"


class TestGitHubListingResource:
    """Tests for GitHubListingResource class."""

    def test_version_uses_tree_sha(self) -> None:
        """version returns the tree SHA."""
        ref = Ref(
            provider="github",
            connection="myrepo",
            method="ls",
            args={"path": "src/", "ref": "main"},
        )
        resource = GitHubListingResource(
            content="file1.py\nfile2.py",
            ref=ref,
            path="src/",
            repo="owner/repo",
            git_ref="main",
            entries=[],
            tree_sha="tree123",
        )

        assert resource.version == "tree123"

    def test_iteration_over_entries(self) -> None:
        """Can iterate over entries."""
        entries = [
            GitHubEntry(path="src/a.py", name="a.py", type="file", sha="sha1", size=100),
            GitHubEntry(path="src/b.py", name="b.py", type="file", sha="sha2", size=200),
        ]
        ref = Ref(
            provider="github",
            connection="myrepo",
            method="ls",
            args={"path": "src/", "ref": "main"},
        )
        resource = GitHubListingResource(
            content="src/a.py\nsrc/b.py",
            ref=ref,
            path="src/",
            repo="owner/repo",
            git_ref="main",
            entries=entries,
            tree_sha="tree123",
        )

        result = list(resource)

        assert len(result) == 2
        assert result[0].name == "a.py"
        assert result[1].name == "b.py"


class TestGitHubEntry:
    """Tests for GitHubEntry class."""

    def test_file_entry(self) -> None:
        """File entry has correct fields."""
        entry = GitHubEntry(
            path="src/main.py",
            name="main.py",
            type="file",
            sha="abc123",
            size=1024,
        )

        assert entry.path == "src/main.py"
        assert entry.name == "main.py"
        assert entry.type == "file"
        assert entry.sha == "abc123"
        assert entry.size == 1024

    def test_dir_entry(self) -> None:
        """Directory entry has None size."""
        entry = GitHubEntry(
            path="src/utils",
            name="utils",
            type="dir",
            sha="def456",
            size=None,
        )

        assert entry.type == "dir"
        assert entry.size is None


class TestGitHubProvider:
    """Tests for GitHubProvider."""

    def test_namespace_is_github(self) -> None:
        """Namespace is 'github'."""
        provider = GitHubProvider(repo="owner/repo")

        assert provider.namespace == "github"

    def test_repo_required(self) -> None:
        """repo is a required field."""
        with pytest.raises(Exception):  # Pydantic validation error
            GitHubProvider()  # type: ignore[call-arg]

    def test_token_optional(self) -> None:
        """token is optional."""
        provider = GitHubProvider(repo="owner/repo")

        assert provider.token is None

    def test_token_can_be_set(self) -> None:
        """token can be set."""
        provider = GitHubProvider(repo="owner/repo", token="ghp_xxx")

        assert provider.token == "ghp_xxx"


class TestGitHubProviderHeaders:
    """Tests for GitHubProvider._headers()."""

    def test_headers_without_token(self) -> None:
        """Headers without token have Accept header."""
        provider = GitHubProvider(repo="owner/repo")

        headers = provider._headers()

        assert "Accept" in headers
        assert "Authorization" not in headers

    def test_headers_with_token(self) -> None:
        """Headers with token have Authorization header."""
        provider = GitHubProvider(repo="owner/repo", token="ghp_xxx")

        headers = provider._headers()

        assert headers["Authorization"] == "Bearer ghp_xxx"


class TestGitHubProviderResolveRef:
    """Tests for GitHubProvider._resolve_ref()."""

    async def test_resolves_ref_to_sha(self) -> None:
        """_resolve_ref() returns SHA from API."""
        provider = GitHubProvider(repo="owner/repo")
        provider._sha_cache = {}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"sha": "abc123def456"}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        result = await provider._resolve_ref("main")

        assert result == "abc123def456"
        mock_client.get.assert_called_once()
        assert "commits/main" in mock_client.get.call_args[0][0]

    async def test_caches_resolved_sha(self) -> None:
        """_resolve_ref() caches the result."""
        provider = GitHubProvider(repo="owner/repo")
        provider._sha_cache = {}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"sha": "abc123"}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        # First call
        await provider._resolve_ref("main")
        # Second call should use cache
        result = await provider._resolve_ref("main")

        assert result == "abc123"
        assert mock_client.get.call_count == 1  # Only one API call

    async def test_raises_on_404(self) -> None:
        """_resolve_ref() raises FileNotFoundError on 404."""
        provider = GitHubProvider(repo="owner/repo")
        provider._sha_cache = {}

        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        with pytest.raises(FileNotFoundError, match="Ref not found"):
            await provider._resolve_ref("nonexistent")

    async def test_raises_on_401(self) -> None:
        """_resolve_ref() raises PermissionError on 401."""
        provider = GitHubProvider(repo="owner/private-repo")
        provider._sha_cache = {}

        mock_response = MagicMock()
        mock_response.status_code = 401

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        with pytest.raises(PermissionError, match="Authentication required"):
            await provider._resolve_ref("main")

    async def test_raises_on_403(self) -> None:
        """_resolve_ref() raises PermissionError on 403 (rate limit)."""
        provider = GitHubProvider(repo="owner/repo")
        provider._sha_cache = {}

        mock_response = MagicMock()
        mock_response.status_code = 403

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        with pytest.raises(PermissionError, match="rate limited"):
            await provider._resolve_ref("main")


class TestGitHubProviderFile:
    """Tests for GitHubProvider.file()."""

    async def test_returns_github_file_resource(self) -> None:
        """file() returns GitHubFileResource with content."""
        provider = GitHubProvider(repo="owner/repo")
        provider._sha_cache = {}

        # Mock resolve ref
        mock_commits_response = MagicMock()
        mock_commits_response.status_code = 200
        mock_commits_response.json.return_value = {"sha": "abc123"}

        # Mock raw content
        mock_raw_response = MagicMock()
        mock_raw_response.status_code = 200
        mock_raw_response.text = "# Hello World"

        mock_client = AsyncMock()

        async def mock_get(url: str, **kwargs) -> MagicMock:
            if "api.github.com" in url:
                return mock_commits_response
            return mock_raw_response

        mock_client.get = AsyncMock(side_effect=mock_get)
        provider._client = mock_client

        result = await provider.file("README.md", ref="main")

        assert isinstance(result, GitHubFileResource)
        assert result.content == "# Hello World"
        assert result.path == "README.md"
        assert result.repo == "owner/repo"
        assert result.git_ref == "main"
        assert result.resolved_sha == "abc123"

    async def test_file_not_found(self) -> None:
        """file() raises FileNotFoundError when file doesn't exist."""
        provider = GitHubProvider(repo="owner/repo")
        provider._sha_cache = {}

        # Mock resolve ref
        mock_commits_response = MagicMock()
        mock_commits_response.status_code = 200
        mock_commits_response.json.return_value = {"sha": "abc123"}

        # Mock raw content 404
        mock_raw_response = MagicMock()
        mock_raw_response.status_code = 404

        mock_client = AsyncMock()

        async def mock_get(url: str, **kwargs) -> MagicMock:
            if "api.github.com" in url:
                return mock_commits_response
            return mock_raw_response

        mock_client.get = AsyncMock(side_effect=mock_get)
        provider._client = mock_client

        with pytest.raises(FileNotFoundError, match="File not found"):
            await provider.file("nonexistent.md")


class TestGitHubProviderLs:
    """Tests for GitHubProvider.ls()."""

    async def test_returns_listing_resource(self) -> None:
        """ls() returns GitHubListingResource with entries."""
        provider = GitHubProvider(repo="owner/repo")
        provider._sha_cache = {}

        # Mock resolve ref
        mock_commits_response = MagicMock()
        mock_commits_response.status_code = 200
        mock_commits_response.json.return_value = {"sha": "abc123"}

        # Mock contents API
        mock_contents_response = MagicMock()
        mock_contents_response.status_code = 200
        mock_contents_response.json.return_value = [
            {"path": "src/a.py", "name": "a.py", "type": "file", "sha": "sha1", "size": 100},
            {"path": "src/b.py", "name": "b.py", "type": "file", "sha": "sha2", "size": 200},
            {"path": "src/utils", "name": "utils", "type": "dir", "sha": "sha3"},
        ]

        mock_client = AsyncMock()

        async def mock_get(url: str, **kwargs) -> MagicMock:
            if "commits" in url:
                return mock_commits_response
            return mock_contents_response

        mock_client.get = AsyncMock(side_effect=mock_get)
        provider._client = mock_client

        result = await provider.ls("src/")

        assert isinstance(result, GitHubListingResource)
        assert len(result.entries) == 3
        assert result.entries[0].name == "a.py"
        assert result.entries[0].type == "file"
        assert result.entries[2].name == "utils"
        assert result.entries[2].type == "dir"

    async def test_ls_path_not_found(self) -> None:
        """ls() raises FileNotFoundError when path doesn't exist."""
        provider = GitHubProvider(repo="owner/repo")
        provider._sha_cache = {}

        # Mock resolve ref
        mock_commits_response = MagicMock()
        mock_commits_response.status_code = 200
        mock_commits_response.json.return_value = {"sha": "abc123"}

        # Mock contents API 404
        mock_contents_response = MagicMock()
        mock_contents_response.status_code = 404

        mock_client = AsyncMock()

        async def mock_get(url: str, **kwargs) -> MagicMock:
            if "commits" in url:
                return mock_commits_response
            return mock_contents_response

        mock_client.get = AsyncMock(side_effect=mock_get)
        provider._client = mock_client

        with pytest.raises(FileNotFoundError, match="Path not found"):
            await provider.ls("nonexistent/")

    async def test_ls_file_raises_error(self) -> None:
        """ls() raises ValueError when path is a file, not directory."""
        provider = GitHubProvider(repo="owner/repo")
        provider._sha_cache = {}

        # Mock resolve ref
        mock_commits_response = MagicMock()
        mock_commits_response.status_code = 200
        mock_commits_response.json.return_value = {"sha": "abc123"}

        # Mock contents API returning a file (dict, not list)
        mock_contents_response = MagicMock()
        mock_contents_response.status_code = 200
        mock_contents_response.json.return_value = {
            "path": "README.md",
            "name": "README.md",
            "type": "file",
            "sha": "sha1",
        }

        mock_client = AsyncMock()

        async def mock_get(url: str, **kwargs) -> MagicMock:
            if "commits" in url:
                return mock_commits_response
            return mock_contents_response

        mock_client.get = AsyncMock(side_effect=mock_get)
        provider._client = mock_client

        with pytest.raises(ValueError, match="Path is a file, not a directory"):
            await provider.ls("README.md")


class TestGitHubProviderGetRefVersion:
    """Tests for GitHubProvider.get_ref_version()."""

    async def test_re_resolves_ref(self) -> None:
        """get_ref_version() re-resolves the ref to get current SHA."""
        provider = GitHubProvider(repo="owner/repo")
        provider._sha_cache = {"main": "old_sha"}  # Pre-cached

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"sha": "new_sha"}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        ref = Ref(
            provider="github",
            connection="myrepo",
            method="file",
            args={"path": "README.md", "ref": "main"},
        )
        result = await provider.get_ref_version(ref)

        assert result == "new_sha"
        # Should have cleared cache and re-resolved
        mock_client.get.assert_called_once()


class TestGitHubProviderLifecycle:
    """Tests for GitHubProvider lifespan lifecycle."""

    async def test_lifespan_creates_and_clears_client(self) -> None:
        """lifespan() creates client on enter and clears on exit."""
        provider = GitHubProvider(repo="owner/repo")

        assert provider._client is None
        assert provider._sha_cache is None

        async with provider.lifespan():
            assert provider._client is not None
            assert isinstance(provider._client, httpx.AsyncClient)
            assert provider._sha_cache == {}

        assert provider._client is None
        assert provider._sha_cache is None


class TestGitHubProviderGetFunctions:
    """Tests for GitHubProvider.get_functions()."""

    def test_exposes_file_and_ls(self) -> None:
        """get_functions() exposes file and ls methods."""
        provider = GitHubProvider(repo="owner/repo")

        funcs = provider.get_functions()

        assert "file" in funcs
        assert "ls" in funcs
        assert funcs["file"] == provider.file
        assert funcs["ls"] == provider.ls
