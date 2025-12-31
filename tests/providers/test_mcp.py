"""Tests for MCP provider."""

import pytest

from colin.providers.mcp import MCPProvider, build_mcp_uri


class TestBuildMcpUri:
    """Tests for build_mcp_uri helper."""

    def test_build_resource_uri(self) -> None:
        """Build URI for resource access."""
        uri = build_mcp_uri("mcp.linear", resource="colin://issues/ABC-123")

        assert uri == "mcp.linear://?resource=colin%3A%2F%2Fissues%2FABC-123"

    def test_build_prompt_uri(self) -> None:
        """Build URI for prompt access."""
        uri = build_mcp_uri("mcp.github", prompt="summarize")

        assert uri == "mcp.github://?prompt=summarize"

    def test_build_prompt_uri_with_args(self) -> None:
        """Build URI for prompt with arguments."""
        uri = build_mcp_uri("mcp.github", prompt="summarize", url="https://github.com/org/repo")

        assert "prompt=summarize" in uri
        assert "url=https" in uri

    def test_encodes_special_characters_in_resource(self) -> None:
        """Resource URIs with special characters are properly encoded."""
        uri = build_mcp_uri("mcp.test", resource="s3://bucket/path?query=value&other=123")

        # The : // ? = & should all be encoded
        assert "resource=s3%3A%2F%2F" in uri
        assert "%3F" in uri  # ? encoded
        assert "%26" in uri  # & encoded

    def test_encodes_spaces_in_resource(self) -> None:
        """Resource URIs with spaces are properly encoded."""
        uri = build_mcp_uri("mcp.test", resource="file://path/with spaces/file.txt")

        assert "+spaces" in uri or "%20spaces" in uri

    def test_prompt_with_multiple_args(self) -> None:
        """Prompt with multiple arguments includes all of them."""
        uri = build_mcp_uri(
            "mcp.test",
            prompt="generate",
            template="report",
            format="markdown",
            verbose="true",
        )

        assert "prompt=generate" in uri
        assert "template=report" in uri
        assert "format=markdown" in uri
        assert "verbose=true" in uri

    def test_empty_resource_not_included(self) -> None:
        """Empty resource string is not included in URI."""
        uri = build_mcp_uri("mcp.test", resource="")

        # Empty resource should not add resource param
        assert uri == "mcp.test://?"

    def test_neither_resource_nor_prompt(self) -> None:
        """URI with neither resource nor prompt is valid but empty."""
        uri = build_mcp_uri("mcp.test")

        assert uri == "mcp.test://?"


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
        assert provider.schemes == ["mcp.linear"]

    def test_creates_with_remote_server(self) -> None:
        """Create provider with remote server config."""
        provider = MCPProvider.from_config("remote", {"url": "http://localhost:8000/mcp"})

        assert provider.namespace == "mcp"
        assert provider.schemes == ["mcp.remote"]

    def test_creates_with_command_only(self) -> None:
        """Create with just command, no args."""
        provider = MCPProvider.from_config("simple", {"command": "mcp-server"})

        assert provider.namespace == "mcp"
        assert provider.schemes == ["mcp.simple"]

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
        assert provider.schemes == ["mcp.configured"]

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
        assert provider.schemes == ["mcp.authenticated"]

    def test_name_includes_instance_name(self) -> None:
        """Scheme is always mcp.<instance>."""
        provider1 = MCPProvider.from_config("github", {"command": "npx", "args": ["@github/mcp"]})
        provider2 = MCPProvider.from_config("linear", {"command": "npx", "args": ["@linear/mcp"]})
        provider3 = MCPProvider.from_config("my-custom-server", {"url": "http://localhost:3000"})

        assert provider1.schemes == ["mcp.github"]
        assert provider2.schemes == ["mcp.linear"]
        assert provider3.schemes == ["mcp.my-custom-server"]

    def test_default_instance_name(self) -> None:
        """Default instance uses bare mcp name."""
        provider = MCPProvider.from_config(None, {"command": "npx", "args": ["@github/mcp"]})

        assert provider.namespace == "mcp"

    async def test_read_rejects_invalid_uri(self) -> None:
        """read() rejects URI without resource or prompt."""
        provider = MCPProvider.from_config("test", {"command": "test"})

        with pytest.raises(ValueError, match="Invalid MCP URI"):
            await provider.read("mcp.test://?other=value")

    async def test_read_rejects_empty_query_string(self) -> None:
        """read() rejects URI with empty query string."""
        provider = MCPProvider.from_config("test", {"command": "test"})

        with pytest.raises(ValueError, match="Invalid MCP URI"):
            await provider.read("mcp.test://?")
