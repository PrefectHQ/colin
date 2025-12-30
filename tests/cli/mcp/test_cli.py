"""CLI tests for colin mcp commands."""

from collections.abc import Callable
from pathlib import Path

import pytest
from fastmcp.mcp_config import RemoteMCPServer, StdioMCPServer

from colin.api.project import load_project
from colin.cli import app


class TestMCPAdd:
    """Tests for colin mcp add command."""

    def test_add_stdio_server(self, project: Path, cli: Callable[..., None]):
        """Adding a stdio MCP server updates colin.toml."""
        cli("mcp", "add", "greeter", "python", "server.py")

        config = load_project(project / "colin.toml")
        assert "greeter" in config.mcp.mcpServers
        server = config.mcp.mcpServers["greeter"]
        assert isinstance(server, StdioMCPServer)
        assert server.command == "python"
        assert server.args == ["server.py"]

    def test_add_url_server(self, project: Path, cli: Callable[..., None]):
        """Adding an HTTP MCP server updates colin.toml."""
        cli("mcp", "add", "remote", "http://localhost:8000/mcp")

        config = load_project(project / "colin.toml")
        assert "remote" in config.mcp.mcpServers
        server = config.mcp.mcpServers["remote"]
        assert isinstance(server, RemoteMCPServer)
        assert server.url == "http://localhost:8000/mcp"

    def test_add_with_env(self, project: Path, cli: Callable[..., None]):
        """Adding a server with env vars works."""
        cli("mcp", "add", "api", "npx", "server", "-e", "API_KEY=secret")

        config = load_project(project / "colin.toml")
        server = config.mcp.mcpServers["api"]
        assert isinstance(server, StdioMCPServer)
        assert server.env == {"API_KEY": "secret"}

    def test_add_rejects_env_with_http(self, project: Path, capsys):
        """Adding http server with --env fails."""
        with pytest.raises(SystemExit) as exc_info:
            app(["mcp", "add", "bad", "http://example.com", "-e", "KEY=val"])

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "only apply to stdio" in captured.err

    def test_add_shows_confirmation(self, project: Path, capsys, cli: Callable[..., None]):
        """Adding a server shows confirmation message."""
        cli("mcp", "add", "greeter", "python")

        captured = capsys.readouterr()
        assert "Added" in captured.out
        assert "greeter" in captured.out

    def test_add_explicit_transport(self, project: Path, cli: Callable[..., None]):
        """Transport can be explicitly specified."""
        cli("mcp", "add", "remote", "http://localhost:8000", "-t", "sse")

        config = load_project(project / "colin.toml")
        assert "remote" in config.mcp.mcpServers


class TestMCPRemove:
    """Tests for colin mcp remove command."""

    def test_remove_server(self, project: Path, cli: Callable[..., None]):
        """Removing an MCP server updates colin.toml."""
        cli("mcp", "add", "temp", "python")

        config = load_project(project / "colin.toml")
        assert "temp" in config.mcp.mcpServers

        cli("mcp", "remove", "temp")

        config = load_project(project / "colin.toml")
        assert "temp" not in config.mcp.mcpServers

    def test_remove_nonexistent_fails(self, project: Path, capsys):
        """Removing a nonexistent server fails."""
        with pytest.raises(SystemExit) as exc_info:
            app(["mcp", "remove", "nonexistent"])

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Error" in captured.err
        assert "nonexistent" in captured.err

    def test_remove_shows_confirmation(self, project: Path, capsys, cli: Callable[..., None]):
        """Removing a server shows confirmation message."""
        cli("mcp", "add", "temp", "python")
        capsys.readouterr()

        cli("mcp", "remove", "temp")

        captured = capsys.readouterr()
        assert "Removed" in captured.out
        assert "temp" in captured.out


class TestMCPTest:
    """Tests for colin mcp test command."""

    def test_test_nonexistent_fails(self, project: Path, capsys):
        """Testing a nonexistent server fails."""
        with pytest.raises(SystemExit) as exc_info:
            app(["mcp", "test", "nonexistent"])

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err


class TestMCPList:
    """Tests for colin mcp list command."""

    def test_list_empty(self, project: Path, capsys, cli: Callable[..., None]):
        """Listing with no servers shows message."""
        cli("mcp", "list")

        captured = capsys.readouterr()
        assert "No MCP servers" in captured.out

    def test_list_shows_servers(self, project: Path, capsys, cli: Callable[..., None]):
        """Listing shows configured servers."""
        cli("mcp", "add", "greeter", "python", "server.py")
        capsys.readouterr()

        cli("mcp", "list")

        captured = capsys.readouterr()
        assert "greeter" in captured.out
        assert "stdio" in captured.out

    def test_list_shows_url_servers(self, project: Path, capsys, cli: Callable[..., None]):
        """Listing shows HTTP servers correctly."""
        cli("mcp", "add", "remote", "http://localhost:8000/mcp")
        capsys.readouterr()

        cli("mcp", "list")

        captured = capsys.readouterr()
        assert "remote" in captured.out
        assert "http" in captured.out
