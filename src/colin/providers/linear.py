"""Linear provider for fetching issues from Linear workspaces."""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, ClassVar

from fastmcp import Client
from fastmcp.client.auth import OAuth
from pydantic import validate_call
from typing_extensions import Self

from colin.compiler.cache import get_compile_context
from colin.models import Ref
from colin.providers.base import Provider
from colin.providers.oauth_store import get_oauth_store
from colin.resources import Resource

# Linear's hosted MCP server URL
LINEAR_MCP_URL = "https://mcp.linear.app/mcp"


class LinearIssueResource(Resource):
    """Resource returned by LinearProvider.issue()."""

    def __init__(
        self,
        content: str,
        ref: Ref,
        issue_id: str,
        identifier: str,
        title: str,
        url: str,
        state: str,
        priority: int | None,
        assignee: str | None,
        updated_at: datetime,
        created_at: datetime | None = None,
    ) -> None:
        """Initialize a Linear issue resource.

        Args:
            content: Issue description/content as markdown.
            ref: The Ref for this resource.
            issue_id: Linear issue UUID.
            identifier: Issue identifier (e.g., "ENG-123").
            title: Issue title.
            url: Linear issue URL.
            state: Issue state (e.g., "In Progress", "Done").
            priority: Priority level (0=none, 1=urgent, 2=high, 3=medium, 4=low).
            assignee: Assignee name or None.
            updated_at: When the issue was last modified.
            created_at: When the issue was created.
        """
        super().__init__(content, ref)
        self.issue_id = issue_id
        self.identifier = identifier
        self.title = title
        self.url = url
        self.state = state
        self.priority = priority
        self.assignee = assignee
        self.updated_at = updated_at
        self.created_at = created_at

    @property
    def version(self) -> str:
        """Use updated_at as version for efficient staleness checking."""
        return self.updated_at.isoformat()


class LinearIssuesResource(Resource):
    """Resource returned by LinearProvider.issues()."""

    def __init__(
        self,
        content: str,
        ref: Ref,
        issues: list[LinearIssueResource],
    ) -> None:
        """Initialize a Linear issues search resource.

        Args:
            content: Newline-separated issue identifiers and titles.
            ref: The Ref for this resource.
            issues: List of issue resources.
        """
        super().__init__(content, ref)
        self.issues = issues

    @property
    def version(self) -> str:
        """Version based on all issue IDs and their update times."""
        parts = sorted(f"{i.issue_id}:{i.updated_at.isoformat()}" for i in self.issues)
        combined = "\n".join(parts)
        return hashlib.sha256(combined.encode()).hexdigest()[:16]

    def __iter__(self):
        """Allow iteration over issues."""
        return iter(self.issues)

    def __len__(self) -> int:
        """Return number of issues."""
        return len(self.issues)


class LinearProvider(Provider):
    """Provider for fetching issues from Linear workspaces.

    Uses Linear's hosted MCP server for OAuth and API access.

    Template usage:
        {{ colin.linear.issue("ENG-123").content }}
        {{ colin.linear.issue("uuid-here").title }}

        {% for issue in colin.linear.issues(team="Engineering") %}
            {{ issue.identifier }}: {{ issue.title }}
        {% endfor %}

    Configuration:
        [[providers.linear]]
        # No configuration needed - auto-connects to Linear MCP
        # OAuth flow triggered on first use
    """

    namespace: ClassVar[str] = "linear"

    _client: Client | None = None
    _connection: str = ""

    @classmethod
    def from_config(cls, name: str | None, config: dict[str, Any]) -> Self:
        """Create Linear provider from configuration.

        Args:
            name: Instance name (unused - only one Linear workspace per OAuth).
            config: Provider configuration (currently unused).

        Returns:
            Configured LinearProvider instance.
        """
        instance = cls()
        instance._connection = name or ""
        return instance

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        """Manage MCP client lifecycle."""
        # Create persistent token storage (with optional encryption)
        token_storage = get_oauth_store()
        oauth = OAuth(mcp_url=LINEAR_MCP_URL, token_storage=token_storage)  # type: ignore[arg-type]

        try:
            async with Client(LINEAR_MCP_URL, auth=oauth) as client:
                self._client = client
                yield
        except Exception as e:
            raise RuntimeError(
                f"Failed to connect to Linear MCP server\n"
                f"  URL: {LINEAR_MCP_URL}\n"
                f"  Error: {e}\n\n"
                f"If this is an authentication error, try clearing your OAuth tokens:\n"
                f"  colin mcp auth clear"
            ) from None
        finally:
            self._client = None

    def _require_client(self) -> Client:
        """Get client, raising if not initialized."""
        if self._client is None:
            raise RuntimeError("LinearProvider not initialized - use within lifespan context")
        return self._client

    def get_functions(self) -> dict[str, Callable[..., Awaitable[object]]]:
        """Return template functions this provider contributes."""
        return {
            "issue": self.issue,
            "issues": self.issues,
        }

    @validate_call
    async def issue(self, id: str, *, watch: bool = True) -> LinearIssueResource:
        """Fetch a Linear issue by ID or identifier.

        Args:
            id: Issue identifier (e.g., "ENG-123") or UUID.
            watch: Whether to track this ref for staleness (default True).

        Returns:
            LinearIssueResource with issue content and metadata.
        """
        client = self._require_client()

        # Call the get_issue tool
        result = await client.call_tool("get_issue", {"id": id})

        # Parse the response
        issue_data = self._parse_issue_response(result)

        ref = Ref(
            provider=self.namespace,
            connection=self._connection,
            method="issue",
            args={"id": id},
        )

        resource = LinearIssueResource(
            content=issue_data["content"],
            ref=ref,
            issue_id=issue_data["issue_id"],
            identifier=issue_data["identifier"],
            title=issue_data["title"],
            url=issue_data["url"],
            state=issue_data["state"],
            priority=issue_data["priority"],
            assignee=issue_data["assignee"],
            updated_at=issue_data["updated_at"],
            created_at=issue_data["created_at"],
        )

        if watch:
            ctx = get_compile_context()
            if ctx:
                ctx.track(ref, resource.version)

        return resource

    @validate_call
    async def issues(
        self,
        *,
        query: str | None = None,
        team: str | None = None,
        assignee: str | None = None,
        state: str | None = None,
        limit: int = 20,
        watch: bool = True,
    ) -> LinearIssuesResource:
        """Search Linear issues.

        Args:
            query: Search query string.
            team: Filter by team name or ID.
            assignee: Filter by assignee (name, email, or "me").
            state: Filter by state name or ID.
            limit: Maximum number of results (default 20).
            watch: Whether to track this ref for staleness (default True).

        Returns:
            LinearIssuesResource with matching issues.
        """
        client = self._require_client()

        # Build the search parameters
        params: dict[str, Any] = {"limit": limit}
        if query:
            params["query"] = query
        if team:
            params["team"] = team
        if assignee:
            params["assignee"] = assignee
        if state:
            params["state"] = state

        # Call the list_issues tool
        result = await client.call_tool("list_issues", params)

        # Parse the response
        issues_data = self._parse_issues_response(result, limit)

        # Build issue resources
        issue_resources: list[LinearIssueResource] = []
        for issue_info in issues_data["issues"]:
            issue_ref = Ref(
                provider=self.namespace,
                connection=self._connection,
                method="issue",
                args={"id": issue_info["issue_id"]},
            )
            issue_resources.append(
                LinearIssueResource(
                    content=issue_info["content"],
                    ref=issue_ref,
                    issue_id=issue_info["issue_id"],
                    identifier=issue_info["identifier"],
                    title=issue_info["title"],
                    url=issue_info["url"],
                    state=issue_info["state"],
                    priority=issue_info["priority"],
                    assignee=issue_info["assignee"],
                    updated_at=issue_info["updated_at"],
                    created_at=issue_info["created_at"],
                )
            )

        # Build content as list of identifiers and titles
        content_lines = [f"{i.identifier}: {i.title}" for i in issue_resources]
        content = "\n".join(content_lines)

        ref = Ref(
            provider=self.namespace,
            connection=self._connection,
            method="issues",
            args={
                k: v
                for k, v in {
                    "query": query,
                    "team": team,
                    "assignee": assignee,
                    "state": state,
                    "limit": limit,
                }.items()
                if v is not None
            },
        )

        resource = LinearIssuesResource(
            content=content,
            ref=ref,
            issues=issue_resources,
        )

        if watch:
            ctx = get_compile_context()
            if ctx:
                ctx.track(ref, resource.version)

        return resource

    def _parse_issue_response(self, result: Any) -> dict[str, Any]:
        """Parse get_issue tool response into issue data."""
        # Extract text content from CallToolResult
        raw_text = ""
        if hasattr(result, "content"):
            for block in result.content:
                if hasattr(block, "text"):
                    raw_text = block.text
                    break
        elif isinstance(result, str):
            raw_text = result
        else:
            raw_text = str(result)

        # Parse the JSON response
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError:
            # Fallback if not JSON - use content hash for deterministic versioning
            content_hash = int(hashlib.sha256(raw_text.encode()).hexdigest()[:8], 16)
            epoch_seconds = content_hash % (50 * 365 * 24 * 3600)
            return {
                "content": raw_text,
                "issue_id": hashlib.sha256(raw_text.encode()).hexdigest()[:16],
                "identifier": "UNKNOWN",
                "title": "Untitled",
                "url": "",
                "state": "Unknown",
                "priority": None,
                "assignee": None,
                "updated_at": datetime.fromtimestamp(epoch_seconds, tz=timezone.utc),
                "created_at": None,
            }

        # Handle the response structure from Linear MCP
        # The response contains issue fields directly
        issue = data.get("issue", data)  # May be wrapped in "issue" key

        # Parse timestamps
        updated_at = self._parse_timestamp(issue.get("updatedAt"))
        created_at = self._parse_timestamp(issue.get("createdAt"))

        # Build content from description
        description = issue.get("description", "") or ""
        title = issue.get("title", "Untitled")
        content = f"# {title}\n\n{description}" if description else f"# {title}"

        return {
            "content": content,
            "issue_id": issue.get("id", ""),
            "identifier": issue.get("identifier", ""),
            "title": title,
            "url": issue.get("url", ""),
            "state": issue.get("state", {}).get("name", "Unknown")
            if isinstance(issue.get("state"), dict)
            else str(issue.get("state", "Unknown")),
            "priority": issue.get("priority"),
            "assignee": issue.get("assignee", {}).get("name")
            if isinstance(issue.get("assignee"), dict)
            else issue.get("assignee"),
            "updated_at": updated_at,
            "created_at": created_at,
        }

    def _parse_issues_response(self, result: Any, limit: int) -> dict[str, Any]:
        """Parse list_issues tool response into issues data."""
        raw_text = ""
        if hasattr(result, "content"):
            for block in result.content:
                if hasattr(block, "text"):
                    raw_text = block.text
                    break
        elif isinstance(result, str):
            raw_text = result
        else:
            raw_text = str(result)

        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError:
            return {"issues": []}

        # Handle the response structure - may be {"issues": [...]} or just [...]
        issues_list = data.get("issues", data) if isinstance(data, dict) else data
        if not isinstance(issues_list, list):
            issues_list = []

        # Limit results
        issues_list = issues_list[:limit]

        issues = []
        for issue in issues_list:
            updated_at = self._parse_timestamp(issue.get("updatedAt"))
            created_at = self._parse_timestamp(issue.get("createdAt"))

            description = issue.get("description", "") or ""
            title = issue.get("title", "Untitled")
            content = f"# {title}\n\n{description}" if description else f"# {title}"

            issues.append(
                {
                    "content": content,
                    "issue_id": issue.get("id", ""),
                    "identifier": issue.get("identifier", ""),
                    "title": title,
                    "url": issue.get("url", ""),
                    "state": issue.get("state", {}).get("name", "Unknown")
                    if isinstance(issue.get("state"), dict)
                    else str(issue.get("state", "Unknown")),
                    "priority": issue.get("priority"),
                    "assignee": issue.get("assignee", {}).get("name")
                    if isinstance(issue.get("assignee"), dict)
                    else issue.get("assignee"),
                    "updated_at": updated_at,
                    "created_at": created_at,
                }
            )

        return {"issues": issues}

    def _parse_timestamp(self, timestamp: str | None) -> datetime:
        """Parse ISO timestamp string to datetime, with fallback."""
        if timestamp:
            try:
                # Handle various ISO formats
                ts = timestamp.replace("Z", "+00:00")
                return datetime.fromisoformat(ts)
            except ValueError:
                pass

        # Fallback to epoch for deterministic versioning
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
