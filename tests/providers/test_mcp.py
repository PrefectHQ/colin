"""Tests for MCP provider.

Note: MCPProvider is imported inside test classes to avoid circular import
issues at module load time (mcp.py -> compiler.cache -> compiler.__init__ ->
compiler.engine -> providers.manager -> mcp.py).
"""

import pytest

from colin.providers.mcp_types import (
    MCPResourceInfo,
    MCPServerConfig,
    MCPServerInfo,
    SkillFileInfo,
    SkillInfo,
)


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
        assert "list_resources" in functions
        assert "list_skills" in functions
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
        # User env is preserved, banner suppression added automatically
        assert config.env["API_KEY"] == "secret"
        assert config.env["FASTMCP_SHOW_SERVER_BANNER"] == "0"
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
        # Banner suppression added automatically for stdio servers
        assert config.env == {"FASTMCP_SHOW_SERVER_BANNER": "0"}


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


class TestMCPResourceInfo:
    """Tests for MCPResourceInfo dataclass."""

    def test_required_uri(self) -> None:
        """MCPResourceInfo requires uri."""
        info = MCPResourceInfo(uri="skill://test/SKILL.md")

        assert info.uri == "skill://test/SKILL.md"
        assert info.name is None
        assert info.description is None
        assert info.mime_type is None

    def test_all_fields(self) -> None:
        """MCPResourceInfo with all optional fields."""
        info = MCPResourceInfo(
            uri="skill://test/SKILL.md",
            name="SKILL.md",
            description="Test skill",
            mime_type="text/markdown",
        )

        assert info.uri == "skill://test/SKILL.md"
        assert info.name == "SKILL.md"
        assert info.description == "Test skill"
        assert info.mime_type == "text/markdown"


class TestSkillFileInfo:
    """Tests for SkillFileInfo dataclass."""

    def test_required_path(self) -> None:
        """SkillFileInfo requires path."""
        info = SkillFileInfo(path="SKILL.md")

        assert info.path == "SKILL.md"
        assert info.hash is None

    def test_with_hash(self) -> None:
        """SkillFileInfo with hash."""
        info = SkillFileInfo(path="tools/deploy.md", hash="abc123def456")

        assert info.path == "tools/deploy.md"
        assert info.hash == "abc123def456"


class TestSkillInfo:
    """Tests for SkillInfo dataclass."""

    def test_required_name(self) -> None:
        """SkillInfo requires name."""
        info = SkillInfo(name="my-skill")

        assert info.name == "my-skill"
        assert info.description is None
        assert info.files == []

    def test_with_files(self) -> None:
        """SkillInfo with files."""
        info = SkillInfo(
            name="my-skill",
            description="A test skill",
            files=[
                SkillFileInfo(path="SKILL.md", hash="abc123"),
                SkillFileInfo(path="tools/run.md"),
            ],
        )

        assert info.name == "my-skill"
        assert info.description == "A test skill"
        assert len(info.files) == 2
        assert info.files[0].path == "SKILL.md"
        assert info.files[0].hash == "abc123"
        assert info.files[1].path == "tools/run.md"
        assert info.files[1].hash is None
