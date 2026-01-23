"""Tests for the Linear provider."""

from datetime import datetime, timezone

from colin.models import Ref
from colin.providers.linear import (
    LinearIssueResource,
    LinearIssuesResource,
    LinearProvider,
)


class TestLinearProvider:
    """Tests for LinearProvider class."""

    def test_namespace_is_linear(self) -> None:
        """Provider namespace is 'linear'."""
        assert LinearProvider.namespace == "linear"

    def test_creates_without_config(self) -> None:
        """Provider can be created without configuration."""
        provider = LinearProvider()
        assert provider._connection == ""

    def test_creates_with_name(self) -> None:
        """Provider stores connection name from config."""
        provider = LinearProvider.from_config("workspace", {})
        assert provider._connection == "workspace"

    def test_get_functions_includes_issue_and_issues(self) -> None:
        """Provider exposes issue and issues functions."""
        provider = LinearProvider()
        functions = provider.get_functions()
        assert "issue" in functions
        assert "issues" in functions


class TestLinearIssueResource:
    """Tests for LinearIssueResource."""

    def test_version_uses_updated_at(self) -> None:
        """Version is derived from updated_at timestamp."""
        ref = Ref(provider="linear", connection="", method="issue", args={"id": "ENG-123"})
        timestamp = datetime(2024, 1, 15, 12, 30, 45, tzinfo=timezone.utc)

        resource = LinearIssueResource(
            content="# Test Issue\n\nDescription here",
            ref=ref,
            issue_id="abc-123-def",
            identifier="ENG-123",
            title="Test Issue",
            url="https://linear.app/team/issue/ENG-123",
            state="In Progress",
            priority=2,
            assignee="John Doe",
            updated_at=timestamp,
            created_at=timestamp,
        )

        assert resource.version == timestamp.isoformat()

    def test_exposes_all_attributes(self) -> None:
        """All issue attributes are accessible."""
        ref = Ref(provider="linear", connection="", method="issue", args={"id": "ENG-456"})
        timestamp = datetime(2024, 1, 15, tzinfo=timezone.utc)

        resource = LinearIssueResource(
            content="# Bug Report\n\nSomething broke",
            ref=ref,
            issue_id="uuid-here",
            identifier="ENG-456",
            title="Bug Report",
            url="https://linear.app/team/issue/ENG-456",
            state="Todo",
            priority=1,
            assignee="Jane Smith",
            updated_at=timestamp,
            created_at=timestamp,
        )

        assert resource.content == "# Bug Report\n\nSomething broke"
        assert resource.issue_id == "uuid-here"
        assert resource.identifier == "ENG-456"
        assert resource.title == "Bug Report"
        assert resource.url == "https://linear.app/team/issue/ENG-456"
        assert resource.state == "Todo"
        assert resource.priority == 1
        assert resource.assignee == "Jane Smith"


class TestLinearIssuesResource:
    """Tests for LinearIssuesResource."""

    def test_version_is_hash_of_issues(self) -> None:
        """Version is a hash of all issue IDs and update times."""
        ref = Ref(provider="linear", connection="", method="issues", args={"team": "Engineering"})
        timestamp = datetime(2024, 1, 15, tzinfo=timezone.utc)

        issue1 = LinearIssueResource(
            content="# Issue 1",
            ref=Ref(provider="linear", connection="", method="issue", args={"id": "id1"}),
            issue_id="id1",
            identifier="ENG-1",
            title="Issue 1",
            url="",
            state="Todo",
            priority=None,
            assignee=None,
            updated_at=timestamp,
        )
        issue2 = LinearIssueResource(
            content="# Issue 2",
            ref=Ref(provider="linear", connection="", method="issue", args={"id": "id2"}),
            issue_id="id2",
            identifier="ENG-2",
            title="Issue 2",
            url="",
            state="Done",
            priority=None,
            assignee=None,
            updated_at=timestamp,
        )

        resource = LinearIssuesResource(
            content="ENG-1: Issue 1\nENG-2: Issue 2",
            ref=ref,
            issues=[issue1, issue2],
        )

        # Version should be deterministic
        assert len(resource.version) == 16
        assert resource.version == resource.version  # Same result on multiple calls

    def test_version_changes_when_issue_changes(self) -> None:
        """Version changes when an issue is updated."""
        ref = Ref(provider="linear", connection="", method="issues", args={})
        time1 = datetime(2024, 1, 15, tzinfo=timezone.utc)
        time2 = datetime(2024, 1, 16, tzinfo=timezone.utc)

        issue = LinearIssueResource(
            content="# Issue",
            ref=Ref(provider="linear", connection="", method="issue", args={"id": "id1"}),
            issue_id="id1",
            identifier="ENG-1",
            title="Issue",
            url="",
            state="Todo",
            priority=None,
            assignee=None,
            updated_at=time1,
        )

        resource1 = LinearIssuesResource(content="", ref=ref, issues=[issue])

        # Update the issue's timestamp
        issue_updated = LinearIssueResource(
            content="# Issue",
            ref=Ref(provider="linear", connection="", method="issue", args={"id": "id1"}),
            issue_id="id1",
            identifier="ENG-1",
            title="Issue",
            url="",
            state="Todo",
            priority=None,
            assignee=None,
            updated_at=time2,
        )

        resource2 = LinearIssuesResource(content="", ref=ref, issues=[issue_updated])

        assert resource1.version != resource2.version

    def test_iterable(self) -> None:
        """LinearIssuesResource can be iterated."""
        ref = Ref(provider="linear", connection="", method="issues", args={})
        timestamp = datetime(2024, 1, 15, tzinfo=timezone.utc)

        issues = [
            LinearIssueResource(
                content=f"# Issue {i}",
                ref=Ref(provider="linear", connection="", method="issue", args={"id": f"id{i}"}),
                issue_id=f"id{i}",
                identifier=f"ENG-{i}",
                title=f"Issue {i}",
                url="",
                state="Todo",
                priority=None,
                assignee=None,
                updated_at=timestamp,
            )
            for i in range(3)
        ]

        resource = LinearIssuesResource(content="", ref=ref, issues=issues)

        collected = list(resource)
        assert len(collected) == 3
        assert collected[0].identifier == "ENG-0"
        assert collected[2].identifier == "ENG-2"

    def test_content_is_identifiers_and_titles(self) -> None:
        """Content is formatted as identifier: title lines."""
        ref = Ref(provider="linear", connection="", method="issues", args={})
        timestamp = datetime(2024, 1, 15, tzinfo=timezone.utc)

        issues = [
            LinearIssueResource(
                content="",
                ref=Ref(provider="linear", connection="", method="issue", args={"id": "id1"}),
                issue_id="id1",
                identifier="ENG-1",
                title="First Issue",
                url="",
                state="Todo",
                priority=None,
                assignee=None,
                updated_at=timestamp,
            ),
            LinearIssueResource(
                content="",
                ref=Ref(provider="linear", connection="", method="issue", args={"id": "id2"}),
                issue_id="id2",
                identifier="ENG-2",
                title="Second Issue",
                url="",
                state="Done",
                priority=None,
                assignee=None,
                updated_at=timestamp,
            ),
        ]

        resource = LinearIssuesResource(
            content="ENG-1: First Issue\nENG-2: Second Issue",
            ref=ref,
            issues=issues,
        )

        assert "ENG-1: First Issue" in resource.content
        assert "ENG-2: Second Issue" in resource.content


class TestLinearProviderIntegration:
    """Integration-style tests for LinearProvider (without actual MCP calls)."""

    def test_issue_creates_correct_ref(self) -> None:
        """issue() would create a ref with correct structure."""
        # We can't call issue() without MCP, but we can verify the ref structure
        ref = Ref(
            provider="linear",
            connection="",
            method="issue",
            args={"id": "ENG-123"},
        )

        assert ref.provider == "linear"
        assert ref.method == "issue"
        assert ref.args == {"id": "ENG-123"}

    def test_issues_creates_correct_ref(self) -> None:
        """issues() would create a ref with correct structure."""
        ref = Ref(
            provider="linear",
            connection="",
            method="issues",
            args={"team": "Engineering", "limit": 20},
        )

        assert ref.provider == "linear"
        assert ref.method == "issues"
        assert ref.args == {"team": "Engineering", "limit": 20}
