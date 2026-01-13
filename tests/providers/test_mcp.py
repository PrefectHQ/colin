"""Tests for MCP provider.

Note: MCPProvider is imported inside test classes to avoid circular import
issues at module load time (mcp.py -> compiler.cache -> compiler.__init__ ->
compiler.engine -> providers.manager -> mcp.py).
"""

import pytest

from colin.providers.mcp_types import MCPServerConfig, MCPServerInfo


class TestMCPProvider:
    """Tests for MCPProvider."""

    @pytest.fixture
    def MCPProvider(self):
        """Lazy import to avoid circular import at collection time."""
        from colin.providers.mcp import MCPProvider

        return MCPProvider

    def test_rejects_empty_instance_name(self, MCPProvider) -> None:
        """MCP provider rejects empty instance name."""
        with pytest.raises(ValueError, match="requires an instance name"):
            MCPProvider.from_config("", {"command": "test"})

    def test_creates_with_stdio_server(self, MCPProvider) -> None:
        """Create provider with stdio server config."""
        provider = MCPProvider.from_config("linear", {"command": "npx", "args": ["@linear/mcp"]})

        assert provider.namespace == "mcp"

    def test_creates_with_remote_server(self, MCPProvider) -> None:
        """Create provider with remote server config."""
        provider = MCPProvider.from_config("remote", {"url": "http://localhost:8000/mcp"})

        assert provider.namespace == "mcp"

    def test_creates_with_command_only(self, MCPProvider) -> None:
        """Create with just command, no args."""
        provider = MCPProvider.from_config("simple", {"command": "mcp-server"})

        assert provider.namespace == "mcp"

    def test_creates_with_command_and_env(self, MCPProvider) -> None:
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

    def test_creates_with_url_and_headers(self, MCPProvider) -> None:
        """Create with URL and custom headers."""
        provider = MCPProvider.from_config(
            "authenticated",
            {
                "url": "https://api.example.com/mcp",
                "headers": {"Authorization": "Bearer token123"},
            },
        )

        assert provider.namespace == "mcp"

    def test_get_functions_includes_all_methods(self, MCPProvider) -> None:
        """Provider exposes all expected template functions."""
        provider = MCPProvider.from_config("test", {"command": "test"})
        functions = provider.get_functions()

        assert "resource" in functions
        assert "prompt" in functions
        assert "list_tools" in functions
        assert "server_info" in functions
        assert "config" in functions


class TestMCPServerInfo:
    """Tests for MCPServerInfo dataclass."""

    def test_required_fields(self) -> None:
        """MCPServerInfo requires name and version."""
        info = MCPServerInfo(name="test-server", version="1.0.0")

        assert info.name == "test-server"
        assert info.version == "1.0.0"
        assert info.title is None
        assert info.instructions is None
        assert info.website_url is None

    def test_all_fields(self) -> None:
        """MCPServerInfo can include all optional fields."""
        info = MCPServerInfo(
            name="full-server",
            version="2.0.0",
            title="Full Test Server",
            instructions="Use this server for testing.",
            website_url="https://example.com",
        )

        assert info.name == "full-server"
        assert info.version == "2.0.0"
        assert info.title == "Full Test Server"
        assert info.instructions == "Use this server for testing."
        assert info.website_url == "https://example.com"


class TestMCPServerConfig:
    """Tests for MCPServerConfig dataclass."""

    def test_default_values(self) -> None:
        """MCPServerConfig has sensible defaults."""
        config = MCPServerConfig()

        assert config.command is None
        assert config.args == []
        assert config.env == {}
        assert config.url is None
        assert config.headers == {}

    def test_stdio_config(self) -> None:
        """MCPServerConfig for stdio servers."""
        config = MCPServerConfig(
            command="npx -y @mcp/server",
            args=["--port", "8080"],
            env={"API_KEY": "secret"},
        )

        assert config.command == "npx -y @mcp/server"
        assert config.args == ["--port", "8080"]
        assert config.env == {"API_KEY": "secret"}
        assert config.url is None

    def test_remote_config(self) -> None:
        """MCPServerConfig for remote servers."""
        config = MCPServerConfig(
            url="https://api.example.com/mcp",
            headers={"Authorization": "Bearer token"},
        )

        assert config.command is None
        assert config.url == "https://api.example.com/mcp"
        assert config.headers == {"Authorization": "Bearer token"}


class TestMCPProviderConfig:
    """Tests for MCPProvider.config() method."""

    @pytest.fixture
    def MCPProvider(self):
        """Lazy import to avoid circular import at collection time."""
        from colin.providers.mcp import MCPProvider

        return MCPProvider

    async def test_config_for_stdio_server(self, MCPProvider) -> None:
        """config() returns command and args for stdio servers."""
        provider = MCPProvider.from_config(
            "test",
            {
                "command": "npx",
                "args": ["-y", "@mcp/server"],
                "env": {"API_KEY": "secret"},
            },
        )

        config = await provider.config()

        assert config.command == "npx"
        assert config.args == ["-y", "@mcp/server"]
        assert config.env == {"API_KEY": "secret"}
        assert config.url is None

    async def test_config_for_remote_server(self, MCPProvider) -> None:
        """config() returns url and headers for remote servers."""
        provider = MCPProvider.from_config(
            "test",
            {
                "url": "https://api.example.com/mcp",
                "headers": {"Authorization": "Bearer token"},
            },
        )

        config = await provider.config()

        assert config.command is None
        assert config.url == "https://api.example.com/mcp"
        assert config.headers == {"Authorization": "Bearer token"}

    async def test_config_without_optional_fields(self, MCPProvider) -> None:
        """config() handles servers without optional fields."""
        provider = MCPProvider.from_config("test", {"command": "mcp-server"})

        config = await provider.config()

        assert config.command == "mcp-server"
        assert config.args == []
        assert config.env == {}


class TestMCPProviderValidation:
    """Tests for MCP provider config validation."""

    @pytest.fixture
    def MCPProvider(self):
        """Lazy import to avoid circular import at collection time."""
        from colin.providers.mcp import MCPProvider

        return MCPProvider

    def test_rejects_none_name(self, MCPProvider) -> None:
        """MCP provider rejects None as name."""
        with pytest.raises(ValueError, match="requires an instance name"):
            MCPProvider.from_config(None, {"command": "test"})

    def test_missing_command_and_url(self, MCPProvider) -> None:
        """MCP config with neither command nor url fails."""
        with pytest.raises(Exception):
            MCPProvider.from_config("test", {})

    def test_missing_command_and_url_with_other_fields(self, MCPProvider) -> None:
        """MCP config with args but no command/url fails."""
        with pytest.raises(Exception):
            MCPProvider.from_config("test", {"args": ["foo"]})

    def test_invalid_args_type(self, MCPProvider) -> None:
        """MCP config with non-list args fails validation."""
        with pytest.raises(Exception):
            MCPProvider.from_config("test", {"command": "python", "args": "not-a-list"})

    def test_invalid_env_type(self, MCPProvider) -> None:
        """MCP config with non-dict env fails validation."""
        with pytest.raises(Exception):
            MCPProvider.from_config("test", {"command": "python", "env": "not-a-dict"})

    def test_invalid_headers_type(self, MCPProvider) -> None:
        """MCP config with non-dict headers fails validation."""
        with pytest.raises(Exception):
            MCPProvider.from_config(
                "test", {"url": "http://example.com", "headers": ["not", "dict"]}
            )
