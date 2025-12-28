"""Tests for MCP resource integration via CLI."""

from collections.abc import Callable
from pathlib import Path

import pytest
from fastmcp.mcp_config import StdioMCPServer

from colin import api


@pytest.fixture
def greeter_server(test_project: Path):
    """Add the greeter MCP server and remove it after the test."""
    mcp_server_path = Path(__file__).parent / "mcp_server.py"

    server = StdioMCPServer(
        command="uvx",
        args=["--with", "fastmcp", "fastmcp", "run", str(mcp_server_path)],
        env={"FASTMCP_SHOW_BANNER": "false"},
    )
    api.mcp.add_server(project_dir=test_project, name="greeter", server=server)

    yield test_project

    api.mcp.remove_server(project_dir=test_project, name="greeter")


def test_mcp_resource_direct(greeter_server: Path, target_dir: Path, cli: Callable[..., None]):
    """MCP resource content appears in compiled output."""
    cli("run", "--target", str(target_dir), "--quiet")

    output = (target_dir / "compiled" / "direct.md").read_text()
    assert "Hello, world!" in output


def test_mcp_resource_with_parameter(
    greeter_server: Path, target_dir: Path, cli: Callable[..., None]
):
    """MCP resource with URI parameter works."""
    cli("run", "--target", str(target_dir), "--quiet")

    output = (target_dir / "compiled" / "with_param.md").read_text()
    assert "Goodbye, Alice!" in output


def test_mcp_access_shown_in_output(
    greeter_server: Path, target_dir: Path, cli: Callable[..., None], capfd
):
    """MCP resource access appears in CLI output like refs."""
    cli("run", "--target", str(target_dir))

    captured = capfd.readouterr()
    # MCP access should be shown in output (mcp with server.resource(uri) detail)
    assert "mcp greeter.resource" in captured.out


def test_mcp_test_command(greeter_server: Path, cli: Callable[..., None], capfd):
    """colin mcp test shows resources from working server."""
    cli("mcp", "test", "greeter")

    captured = capfd.readouterr()
    assert "Connected to greeter" in captured.out
    assert "colin://hello" in captured.out


def test_mcp_prompt_basic(greeter_server: Path, target_dir: Path, cli: Callable[..., None]):
    """MCP prompt content appears in compiled output."""
    cli("run", "--target", str(target_dir), "--quiet")

    output = (target_dir / "compiled" / "prompt_basic.md").read_text()
    assert "greet the user warmly" in output


def test_mcp_prompt_with_args(greeter_server: Path, target_dir: Path, cli: Callable[..., None]):
    """MCP prompt with arguments works."""
    cli("run", "--target", str(target_dir), "--quiet")

    output = (target_dir / "compiled" / "prompt_with_args.md").read_text()
    assert "Spanish" in output
    assert "formal" in output


def test_mcp_prompt_shown_in_output(
    greeter_server: Path, target_dir: Path, cli: Callable[..., None], capfd
):
    """MCP prompt access appears in CLI output."""
    cli("run", "--target", str(target_dir))

    captured = capfd.readouterr()
    # MCP prompt access should be shown in output (mcp with server.prompt(name) detail)
    assert "mcp greeter.prompt" in captured.out
    assert "greet" in captured.out  # Prompt name shown in detail
