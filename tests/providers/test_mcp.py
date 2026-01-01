"""Tests for MCP provider."""

import pytest

from colin.providers.mcp import MCPProvider


class TestMCPProvider:
    """Tests for MCPProvider."""

    def test_rejects_empty_instance_name(self) -> None:
        """MCP provider rejects empty instance name."""
        with pytest.raises(ValueError, match="requires an instance name"):
            MCPProvider.from_config("", {"command": "test"})

    def test_creates_with_stdio_server(self) -> None:
        """Create provider with stdio server config."""
        provider = MCPProvider.from_config("linear", {"command": "npx", "args": ["@linear/mcp"]})

        assert provider.namespace == "mcp"

    def test_creates_with_remote_server(self) -> None:
        """Create provider with remote server config."""
        provider = MCPProvider.from_config("remote", {"url": "http://localhost:8000/mcp"})

        assert provider.namespace == "mcp"

    def test_creates_with_command_only(self) -> None:
        """Create with just command, no args."""
        provider = MCPProvider.from_config("simple", {"command": "mcp-server"})

        assert provider.namespace == "mcp"

    def test_creates_with_command_and_env(self) -> None:
        """Create with command, args, and environment variables."""
        provider = MCPProvider.from_config(
            "configured",
            {
                "command": "npx",
                "args": ["@example/mcp"],
                "env": {"API_KEY": "secret", "DEBUG": "true"},
            },
        )

        assert provider.namespace == "mcp"

    def test_creates_with_url_and_headers(self) -> None:
        """Create with URL and custom headers."""
        provider = MCPProvider.from_config(
            "authenticated",
            {
                "url": "https://api.example.com/mcp",
                "headers": {"Authorization": "Bearer token123"},
            },
        )

        assert provider.namespace == "mcp"


class TestMCPProviderValidation:
    """Tests for MCP provider config validation."""

    def test_rejects_none_name(self) -> None:
        """MCP provider rejects None as name."""
        with pytest.raises(ValueError, match="requires an instance name"):
            MCPProvider.from_config(None, {"command": "test"})

    def test_missing_command_and_url(self) -> None:
        """MCP config with neither command nor url fails."""
        with pytest.raises(Exception):
            MCPProvider.from_config("test", {})

    def test_missing_command_and_url_with_other_fields(self) -> None:
        """MCP config with args but no command/url fails."""
        with pytest.raises(Exception):
            MCPProvider.from_config("test", {"args": ["foo"]})

    def test_invalid_args_type(self) -> None:
        """MCP config with non-list args fails validation."""
        with pytest.raises(Exception):
            MCPProvider.from_config("test", {"command": "python", "args": "not-a-list"})

    def test_invalid_env_type(self) -> None:
        """MCP config with non-dict env fails validation."""
        with pytest.raises(Exception):
            MCPProvider.from_config("test", {"command": "python", "env": "not-a-dict"})

    def test_invalid_headers_type(self) -> None:
        """MCP config with non-dict headers fails validation."""
        with pytest.raises(Exception):
            MCPProvider.from_config(
                "test", {"url": "http://example.com", "headers": ["not", "dict"]}
            )
