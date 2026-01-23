"""Tests for GitHub provider."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from colin.models import Ref
from colin.providers.github import (
    GitHubEntry,
    GitHubFileResource,
    GitHubIssueResource,
    GitHubIssuesResource,
    GitHubListingResource,
    GitHubProvider,
    GitHubPRResource,
    GitHubPRsResource,
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

    def test_repo_optional(self) -> None:
        """repo is optional for default provider."""
        provider = GitHubProvider()

        assert provider.repo is None

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

        result = await provider._resolve_ref("owner/repo", "main")

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
        await provider._resolve_ref("owner/repo", "main")
        # Second call should use cache
        result = await provider._resolve_ref("owner/repo", "main")

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
            await provider._resolve_ref("owner/repo", "nonexistent")

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
            await provider._resolve_ref("owner/private-repo", "main")

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
            await provider._resolve_ref("owner/repo", "main")


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
        provider._sha_cache = {"owner/repo:main": "old_sha"}  # Pre-cached

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
            args={"repo": "owner/repo", "path": "README.md", "ref": "main"},
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


class TestGitHubProviderDefaultUsage:
    """Tests for GitHubProvider default (repo-less) usage."""

    async def test_file_with_repo_as_first_arg(self) -> None:
        """file() accepts repo as first arg when no repo configured."""
        provider = GitHubProvider()  # No repo configured
        provider._sha_cache = {}

        mock_commits_response = MagicMock()
        mock_commits_response.status_code = 200
        mock_commits_response.json.return_value = {"sha": "abc123"}

        mock_raw_response = MagicMock()
        mock_raw_response.status_code = 200
        mock_raw_response.text = "# Hello"

        mock_client = AsyncMock()

        async def mock_get(url: str, **kwargs) -> MagicMock:
            if "api.github.com" in url:
                return mock_commits_response
            return mock_raw_response

        mock_client.get = AsyncMock(side_effect=mock_get)
        provider._client = mock_client

        result = await provider.file("other/repo", "README.md")

        assert result.repo == "other/repo"
        assert result.path == "README.md"
        assert result.content == "# Hello"

    async def test_file_without_repo_raises(self) -> None:
        """file() raises ValueError when no repo specified anywhere."""
        provider = GitHubProvider()  # No repo configured
        provider._sha_cache = {}
        provider._client = AsyncMock()

        with pytest.raises(ValueError, match="No repository specified"):
            await provider.file("README.md")  # No repo given

    async def test_ls_with_repo_as_first_arg(self) -> None:
        """ls() accepts repo as first arg when no repo configured."""
        provider = GitHubProvider()  # No repo configured
        provider._sha_cache = {}

        mock_commits_response = MagicMock()
        mock_commits_response.status_code = 200
        mock_commits_response.json.return_value = {"sha": "abc123"}

        mock_contents_response = MagicMock()
        mock_contents_response.status_code = 200
        mock_contents_response.json.return_value = [
            {"path": "src/a.py", "name": "a.py", "type": "file", "sha": "sha1", "size": 100},
        ]

        mock_client = AsyncMock()

        async def mock_get(url: str, **kwargs) -> MagicMock:
            if "commits" in url:
                return mock_commits_response
            return mock_contents_response

        mock_client.get = AsyncMock(side_effect=mock_get)
        provider._client = mock_client

        result = await provider.ls("other/repo", "src/")

        assert result.repo == "other/repo"
        assert result.path == "src/"
        assert len(result.entries) == 1

    async def test_configured_repo_used_when_only_path_given(self) -> None:
        """file() uses configured repo when only path is given."""
        provider = GitHubProvider(repo="configured/repo")
        provider._sha_cache = {}

        mock_commits_response = MagicMock()
        mock_commits_response.status_code = 200
        mock_commits_response.json.return_value = {"sha": "abc123"}

        mock_raw_response = MagicMock()
        mock_raw_response.status_code = 200
        mock_raw_response.text = "# Hello"

        mock_client = AsyncMock()

        async def mock_get(url: str, **kwargs) -> MagicMock:
            if "api.github.com" in url:
                return mock_commits_response
            return mock_raw_response

        mock_client.get = AsyncMock(side_effect=mock_get)
        provider._client = mock_client

        result = await provider.file("README.md")  # Only path, repo from config

        assert result.repo == "configured/repo"
        assert result.path == "README.md"


class TestGitHubIssueResource:
    """Tests for GitHubIssueResource class."""

    def test_version_uses_updated_at(self) -> None:
        """version returns the updated_at timestamp."""
        ref = Ref(
            provider="github",
            connection="",
            method="issue",
            args={"repo": "owner/repo", "number": 123},
        )
        updated = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        resource = GitHubIssueResource(
            content="# Test Issue\n\nBody",
            ref=ref,
            repo="owner/repo",
            number=123,
            title="Test Issue",
            body="Body",
            state="open",
            labels=["bug"],
            assignees=["user1"],
            author="author",
            url="https://github.com/owner/repo/issues/123",
            updated_at=updated,
            created_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
            closed_at=None,
            comments_count=5,
        )

        assert resource.version == updated.isoformat()

    def test_exposes_all_fields(self) -> None:
        """Resource exposes all expected fields."""
        ref = Ref(
            provider="github",
            connection="",
            method="issue",
            args={"repo": "owner/repo", "number": 456},
        )
        resource = GitHubIssueResource(
            content="# Bug",
            ref=ref,
            repo="owner/repo",
            number=456,
            title="Bug",
            body=None,
            state="closed",
            labels=["bug", "critical"],
            assignees=["alice", "bob"],
            author="reporter",
            url="https://github.com/owner/repo/issues/456",
            updated_at=datetime(2024, 6, 15, tzinfo=timezone.utc),
            created_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
            closed_at=datetime(2024, 6, 10, tzinfo=timezone.utc),
            comments_count=10,
        )

        assert resource.number == 456
        assert resource.title == "Bug"
        assert resource.body is None
        assert resource.state == "closed"
        assert resource.labels == ["bug", "critical"]
        assert resource.assignees == ["alice", "bob"]
        assert resource.author == "reporter"
        assert resource.closed_at is not None
        assert resource.comments_count == 10


class TestGitHubPRResource:
    """Tests for GitHubPRResource class."""

    def test_version_uses_updated_at(self) -> None:
        """version returns the updated_at timestamp."""
        ref = Ref(
            provider="github",
            connection="",
            method="pr",
            args={"repo": "owner/repo", "number": 789},
        )
        updated = datetime(2024, 7, 20, 15, 30, 0, tzinfo=timezone.utc)
        resource = GitHubPRResource(
            content="# Fix bug",
            ref=ref,
            repo="owner/repo",
            number=789,
            title="Fix bug",
            body="Fixes #123",
            state="open",
            labels=["bugfix"],
            assignees=[],
            author="developer",
            url="https://github.com/owner/repo/pull/789",
            updated_at=updated,
            created_at=datetime(2024, 7, 15, tzinfo=timezone.utc),
            closed_at=None,
            merged_at=None,
            head_ref="fix-branch",
            base_ref="main",
            head_sha="abc123",
            is_draft=False,
            additions=50,
            deletions=10,
            changed_files=3,
        )

        assert resource.version == updated.isoformat()

    def test_exposes_pr_specific_fields(self) -> None:
        """Resource exposes PR-specific fields."""
        ref = Ref(
            provider="github",
            connection="",
            method="pr",
            args={"repo": "owner/repo", "number": 100},
        )
        resource = GitHubPRResource(
            content="# Feature",
            ref=ref,
            repo="owner/repo",
            number=100,
            title="Feature",
            body="New feature",
            state="merged",
            labels=[],
            assignees=[],
            author="dev",
            url="https://github.com/owner/repo/pull/100",
            updated_at=datetime(2024, 8, 1, tzinfo=timezone.utc),
            created_at=datetime(2024, 7, 1, tzinfo=timezone.utc),
            closed_at=datetime(2024, 8, 1, tzinfo=timezone.utc),
            merged_at=datetime(2024, 8, 1, tzinfo=timezone.utc),
            head_ref="feature-branch",
            base_ref="main",
            head_sha="def456",
            is_draft=False,
            additions=100,
            deletions=20,
            changed_files=5,
        )

        assert resource.head_ref == "feature-branch"
        assert resource.base_ref == "main"
        assert resource.head_sha == "def456"
        assert resource.is_draft is False
        assert resource.merged_at is not None
        assert resource.additions == 100
        assert resource.deletions == 20
        assert resource.changed_files == 5


class TestGitHubIssuesResource:
    """Tests for GitHubIssuesResource class."""

    def test_version_is_hash_of_items(self) -> None:
        """version is hash of all issue numbers and update times."""
        ref = Ref(
            provider="github",
            connection="",
            method="issues",
            args={"repo": "owner/repo", "state": "open"},
        )
        issue_ref = Ref(
            provider="github",
            connection="",
            method="issue",
            args={"repo": "owner/repo", "number": 1},
        )
        issues = [
            GitHubIssueResource(
                content="# Issue 1",
                ref=issue_ref,
                repo="owner/repo",
                number=1,
                title="Issue 1",
                body=None,
                state="open",
                labels=[],
                assignees=[],
                author="user",
                url="",
                updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                closed_at=None,
                comments_count=0,
            ),
        ]
        resource = GitHubIssuesResource(
            content="#1: Issue 1",
            ref=ref,
            issues=issues,
        )

        # Version should be a hex hash
        assert len(resource.version) == 16
        assert all(c in "0123456789abcdef" for c in resource.version)

    def test_iteration_over_issues(self) -> None:
        """Can iterate over issues."""
        ref = Ref(
            provider="github",
            connection="",
            method="issues",
            args={"repo": "owner/repo"},
        )
        issue_ref = Ref(
            provider="github",
            connection="",
            method="issue",
            args={"repo": "owner/repo", "number": 1},
        )
        issues = [
            GitHubIssueResource(
                content="# A",
                ref=issue_ref,
                repo="owner/repo",
                number=1,
                title="A",
                body=None,
                state="open",
                labels=[],
                assignees=[],
                author="user",
                url="",
                updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                closed_at=None,
                comments_count=0,
            ),
            GitHubIssueResource(
                content="# B",
                ref=issue_ref,
                repo="owner/repo",
                number=2,
                title="B",
                body=None,
                state="open",
                labels=[],
                assignees=[],
                author="user",
                url="",
                updated_at=datetime(2024, 1, 2, tzinfo=timezone.utc),
                created_at=datetime(2024, 1, 2, tzinfo=timezone.utc),
                closed_at=None,
                comments_count=0,
            ),
        ]
        resource = GitHubIssuesResource(content="", ref=ref, issues=issues)

        result = list(resource)
        assert len(result) == 2
        assert result[0].title == "A"
        assert result[1].title == "B"

    def test_len(self) -> None:
        """len() returns number of issues."""
        ref = Ref(
            provider="github",
            connection="",
            method="issues",
            args={"repo": "owner/repo"},
        )
        resource = GitHubIssuesResource(content="", ref=ref, issues=[])
        assert len(resource) == 0


class TestGitHubPRsResource:
    """Tests for GitHubPRsResource class."""

    def test_version_is_hash_of_items(self) -> None:
        """version is hash of all PR numbers and update times."""
        ref = Ref(
            provider="github",
            connection="",
            method="prs",
            args={"repo": "owner/repo"},
        )
        pr_ref = Ref(
            provider="github",
            connection="",
            method="pr",
            args={"repo": "owner/repo", "number": 1},
        )
        prs = [
            GitHubPRResource(
                content="# PR 1",
                ref=pr_ref,
                repo="owner/repo",
                number=1,
                title="PR 1",
                body=None,
                state="open",
                labels=[],
                assignees=[],
                author="user",
                url="",
                updated_at=datetime(2024, 2, 1, tzinfo=timezone.utc),
                created_at=datetime(2024, 2, 1, tzinfo=timezone.utc),
                closed_at=None,
                merged_at=None,
                head_ref="feature",
                base_ref="main",
                head_sha="abc",
                is_draft=False,
                additions=0,
                deletions=0,
                changed_files=0,
            ),
        ]
        resource = GitHubPRsResource(content="", ref=ref, prs=prs)

        assert len(resource.version) == 16

    def test_iteration_over_prs(self) -> None:
        """Can iterate over PRs."""
        ref = Ref(
            provider="github",
            connection="",
            method="prs",
            args={"repo": "owner/repo"},
        )
        pr_ref = Ref(
            provider="github",
            connection="",
            method="pr",
            args={"repo": "owner/repo", "number": 1},
        )
        prs = [
            GitHubPRResource(
                content="# PR",
                ref=pr_ref,
                repo="owner/repo",
                number=10,
                title="PR",
                body=None,
                state="open",
                labels=[],
                assignees=[],
                author="user",
                url="",
                updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                closed_at=None,
                merged_at=None,
                head_ref="feat",
                base_ref="main",
                head_sha="abc",
                is_draft=True,
                additions=10,
                deletions=5,
                changed_files=2,
            ),
        ]
        resource = GitHubPRsResource(content="", ref=ref, prs=prs)

        result = list(resource)
        assert len(result) == 1
        assert result[0].number == 10


class TestGitHubProviderParseURL:
    """Tests for GitHubProvider URL parsing."""

    def test_parse_issue_url(self) -> None:
        """Parses issue URL correctly."""
        provider = GitHubProvider()
        repo, number, url_type = provider._parse_issue_or_pr_url(
            "https://github.com/owner/repo/issues/123"
        )

        assert repo == "owner/repo"
        assert number == 123
        assert url_type == "issue"

    def test_parse_pr_url(self) -> None:
        """Parses PR URL correctly."""
        provider = GitHubProvider()
        repo, number, url_type = provider._parse_issue_or_pr_url(
            "https://github.com/owner/repo/pull/456"
        )

        assert repo == "owner/repo"
        assert number == 456
        assert url_type == "pr"

    def test_parse_invalid_url_raises(self) -> None:
        """Invalid URL raises ValueError."""
        provider = GitHubProvider()

        with pytest.raises(ValueError, match="Invalid GitHub URL"):
            provider._parse_issue_or_pr_url("https://example.com/something")


class TestGitHubProviderIssue:
    """Tests for GitHubProvider.issue()."""

    async def test_returns_issue_resource(self) -> None:
        """issue() returns GitHubIssueResource with content."""
        provider = GitHubProvider(repo="owner/repo")
        provider._sha_cache = {}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "number": 123,
            "title": "Test Issue",
            "body": "Issue body",
            "state": "open",
            "labels": [{"name": "bug"}],
            "assignees": [{"login": "user1"}],
            "user": {"login": "author"},
            "html_url": "https://github.com/owner/repo/issues/123",
            "updated_at": "2024-06-15T12:00:00Z",
            "created_at": "2024-06-01T10:00:00Z",
            "closed_at": None,
            "comments": 5,
        }

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        result = await provider.issue(123)

        assert isinstance(result, GitHubIssueResource)
        assert result.number == 123
        assert result.title == "Test Issue"
        assert result.body == "Issue body"
        assert result.state == "open"
        assert result.labels == ["bug"]
        assert result.assignees == ["user1"]
        assert result.author == "author"
        assert result.comments_count == 5
        assert "# Test Issue" in result.content

    async def test_issue_with_url(self) -> None:
        """issue() accepts a GitHub URL."""
        provider = GitHubProvider()
        provider._sha_cache = {}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "number": 42,
            "title": "From URL",
            "body": None,
            "state": "closed",
            "labels": [],
            "assignees": [],
            "user": {"login": "someone"},
            "html_url": "https://github.com/other/project/issues/42",
            "updated_at": "2024-01-01T00:00:00Z",
            "created_at": "2024-01-01T00:00:00Z",
            "closed_at": "2024-01-02T00:00:00Z",
            "comments": 0,
        }

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        result = await provider.issue("https://github.com/other/project/issues/42")

        assert result.repo == "other/project"
        assert result.number == 42

    async def test_issue_not_found(self) -> None:
        """issue() raises FileNotFoundError on 404."""
        provider = GitHubProvider(repo="owner/repo")
        provider._sha_cache = {}

        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        with pytest.raises(FileNotFoundError, match="Issue not found"):
            await provider.issue(999)

    async def test_issue_with_repo_first(self) -> None:
        """issue() accepts repo as first arg and number as second."""
        provider = GitHubProvider()  # No configured repo
        provider._sha_cache = {}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "number": 123,
            "title": "Test",
            "body": None,
            "state": "open",
            "labels": [],
            "assignees": [],
            "user": {"login": "author"},
            "html_url": "https://github.com/other/repo/issues/123",
            "updated_at": "2024-01-01T00:00:00Z",
            "created_at": "2024-01-01T00:00:00Z",
            "closed_at": None,
            "comments": 0,
        }

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        result = await provider.issue("other/repo", 123)

        assert result.repo == "other/repo"
        assert result.number == 123


class TestGitHubProviderPR:
    """Tests for GitHubProvider.pr()."""

    async def test_returns_pr_resource(self) -> None:
        """pr() returns GitHubPRResource with content."""
        provider = GitHubProvider(repo="owner/repo")
        provider._sha_cache = {}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "number": 456,
            "title": "Fix Bug",
            "body": "Fixes #123",
            "state": "open",
            "draft": False,
            "labels": [{"name": "bugfix"}],
            "assignees": [],
            "user": {"login": "developer"},
            "html_url": "https://github.com/owner/repo/pull/456",
            "updated_at": "2024-07-15T12:00:00Z",
            "created_at": "2024-07-10T10:00:00Z",
            "closed_at": None,
            "merged_at": None,
            "head": {"ref": "fix-branch", "sha": "abc123"},
            "base": {"ref": "main"},
            "additions": 50,
            "deletions": 10,
            "changed_files": 3,
        }

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        result = await provider.pr(456)

        assert isinstance(result, GitHubPRResource)
        assert result.number == 456
        assert result.title == "Fix Bug"
        assert result.head_ref == "fix-branch"
        assert result.base_ref == "main"
        assert result.head_sha == "abc123"
        assert result.state == "open"
        assert result.additions == 50

    async def test_merged_pr_state(self) -> None:
        """pr() sets state to 'merged' when merged_at is present."""
        provider = GitHubProvider(repo="owner/repo")
        provider._sha_cache = {}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "number": 100,
            "title": "Merged PR",
            "body": None,
            "state": "closed",
            "draft": False,
            "labels": [],
            "assignees": [],
            "user": {"login": "dev"},
            "html_url": "https://github.com/owner/repo/pull/100",
            "updated_at": "2024-08-01T12:00:00Z",
            "created_at": "2024-07-01T10:00:00Z",
            "closed_at": "2024-08-01T11:00:00Z",
            "merged_at": "2024-08-01T11:00:00Z",
            "head": {"ref": "feature", "sha": "def456"},
            "base": {"ref": "main"},
            "additions": 100,
            "deletions": 20,
            "changed_files": 5,
        }

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        result = await provider.pr(100)

        assert result.state == "merged"
        assert result.merged_at is not None


class TestGitHubProviderIssues:
    """Tests for GitHubProvider.issues()."""

    async def test_returns_issues_resource(self) -> None:
        """issues() returns GitHubIssuesResource with list of issues."""
        provider = GitHubProvider(repo="owner/repo")
        provider._sha_cache = {}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "number": 1,
                "title": "First",
                "body": None,
                "state": "open",
                "labels": [],
                "assignees": [],
                "user": {"login": "user"},
                "html_url": "https://github.com/owner/repo/issues/1",
                "updated_at": "2024-01-01T00:00:00Z",
                "created_at": "2024-01-01T00:00:00Z",
                "closed_at": None,
                "comments": 0,
            },
            {
                "number": 2,
                "title": "Second",
                "body": "Body text",
                "state": "open",
                "labels": [{"name": "enhancement"}],
                "assignees": [],
                "user": {"login": "user2"},
                "html_url": "https://github.com/owner/repo/issues/2",
                "updated_at": "2024-01-02T00:00:00Z",
                "created_at": "2024-01-02T00:00:00Z",
                "closed_at": None,
                "comments": 3,
            },
        ]

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        result = await provider.issues()

        assert isinstance(result, GitHubIssuesResource)
        assert len(result) == 2
        assert result.issues[0].title == "First"
        assert result.issues[1].title == "Second"

    async def test_issues_filters_out_prs(self) -> None:
        """issues() excludes items with pull_request field."""
        provider = GitHubProvider(repo="owner/repo")
        provider._sha_cache = {}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "number": 1,
                "title": "Real Issue",
                "body": None,
                "state": "open",
                "labels": [],
                "assignees": [],
                "user": {"login": "user"},
                "html_url": "https://github.com/owner/repo/issues/1",
                "updated_at": "2024-01-01T00:00:00Z",
                "created_at": "2024-01-01T00:00:00Z",
                "closed_at": None,
                "comments": 0,
            },
            {
                "number": 2,
                "title": "Actually a PR",
                "body": None,
                "state": "open",
                "labels": [],
                "assignees": [],
                "user": {"login": "user"},
                "html_url": "https://github.com/owner/repo/issues/2",
                "updated_at": "2024-01-01T00:00:00Z",
                "created_at": "2024-01-01T00:00:00Z",
                "closed_at": None,
                "comments": 0,
                "pull_request": {"url": "..."},  # This marks it as a PR
            },
        ]

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        result = await provider.issues()

        assert len(result) == 1
        assert result.issues[0].title == "Real Issue"


class TestGitHubProviderPRs:
    """Tests for GitHubProvider.prs()."""

    async def test_returns_prs_resource(self) -> None:
        """prs() returns GitHubPRsResource with list of PRs."""
        provider = GitHubProvider(repo="owner/repo")
        provider._sha_cache = {}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "number": 10,
                "title": "Feature PR",
                "body": "Adds feature",
                "state": "open",
                "draft": False,
                "labels": [],
                "assignees": [],
                "user": {"login": "dev"},
                "html_url": "https://github.com/owner/repo/pull/10",
                "updated_at": "2024-02-01T00:00:00Z",
                "created_at": "2024-02-01T00:00:00Z",
                "closed_at": None,
                "merged_at": None,
                "head": {"ref": "feature", "sha": "sha1"},
                "base": {"ref": "main"},
                "additions": 50,
                "deletions": 10,
                "changed_files": 3,
            },
        ]

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        result = await provider.prs()

        assert isinstance(result, GitHubPRsResource)
        assert len(result) == 1
        assert result.prs[0].number == 10
        assert result.prs[0].head_ref == "feature"


class TestGitHubProviderGetFunctionsUpdated:
    """Tests for updated get_functions()."""

    def test_exposes_all_methods(self) -> None:
        """get_functions() exposes file, ls, issue, pr, issues, and prs."""
        provider = GitHubProvider(repo="owner/repo")

        funcs = provider.get_functions()

        assert "file" in funcs
        assert "ls" in funcs
        assert "issue" in funcs
        assert "pr" in funcs
        assert "issues" in funcs
        assert "prs" in funcs
