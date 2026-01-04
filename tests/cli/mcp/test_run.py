"""Tests for MCP resource integration via CLI."""

from collections.abc import Callable
from pathlib import Path

import pytest
from fastmcp.mcp_config import StdioMCPServer

from colin import api
from tests.cli.conftest import strip_ansi


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


def test_mcp_resource_direct(greeter_server: Path, output_dir: Path, cli: Callable[..., None]):
    """MCP resource content appears in compiled output."""
    cli("run", "--output", str(output_dir), "--quiet")

    output = (output_dir / "direct.md").read_text()
    assert "Hello, world!" in output


def test_mcp_resource_with_parameter(
    greeter_server: Path, output_dir: Path, cli: Callable[..., None]
):
    """MCP resource with URI parameter works."""
    cli("run", "--output", str(output_dir), "--quiet")

    output = (output_dir / "with_param.md").read_text()
    assert "Goodbye, Alice!" in output


def test_mcp_access_shown_in_output(
    greeter_server: Path, output_dir: Path, cli: Callable[..., None], capfd
):
    """MCP resource access appears in CLI output like refs."""
    cli("run", "--output", str(output_dir))

    captured = capfd.readouterr()
    output = strip_ansi(captured.out)
    # MCP access should be shown in output (mcp with server.resource(uri) detail)
    assert "mcp greeter.resource" in output


def test_mcp_test_command(greeter_server: Path, cli: Callable[..., None], capfd):
    """colin mcp test shows resources from working server."""
    cli("mcp", "test", "greeter")

    captured = capfd.readouterr()
    output = strip_ansi(captured.out)
    assert "Connected to greeter" in output
    assert "colin://hello" in output


def test_mcp_prompt_basic(greeter_server: Path, output_dir: Path, cli: Callable[..., None]):
    """MCP prompt content appears in compiled output."""
    cli("run", "--output", str(output_dir), "--quiet")

    output = (output_dir / "prompt_basic.md").read_text()
    assert "greet the user warmly" in output


def test_mcp_prompt_with_args(greeter_server: Path, output_dir: Path, cli: Callable[..., None]):
    """MCP prompt with arguments works."""
    cli("run", "--output", str(output_dir), "--quiet")

    output = (output_dir / "prompt_with_args.md").read_text()
    assert "Spanish" in output
    assert "formal" in output


def test_mcp_prompt_shown_in_output(
    greeter_server: Path, output_dir: Path, cli: Callable[..., None], capfd
):
    """MCP prompt access appears in CLI output."""
    cli("run", "--output", str(output_dir))

    captured = capfd.readouterr()
    output = strip_ansi(captured.out)
    # MCP prompt access should be shown in output (mcp with server.prompt(name) detail)
    assert "mcp greeter.prompt" in output
    assert "greet" in output  # Prompt name shown in detail
