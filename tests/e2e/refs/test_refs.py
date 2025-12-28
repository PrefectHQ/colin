"""End-to-end tests for ref() resolution."""

from pathlib import Path

import pytest

from colin.cli.run import run


async def test_ref_content_propagates(e2e_project: Path, target_dir: Path, mock_agent):
    """Content from referenced doc appears in output."""
    await run(project=e2e_project, target=target_dir, quiet=True)

    welcome = (target_dir / "compiled" / "welcome.md").read_text()
    # welcome.md refs greeting.md, so greeting's content should appear
    assert "Hello from greeting!" in welcome


async def test_dependency_order(e2e_project: Path, target_dir: Path, mock_agent):
    """Documents compile in dependency order."""
    # summary.md refs both greeting and welcome
    # greeting must compile before welcome, both before summary
    await run(project=e2e_project, target=target_dir, quiet=True)

    summary = (target_dir / "compiled" / "summary.md").read_text()
    assert "Hello from greeting!" in summary  # from greeting
    assert "Welcome to Colin" in summary  # from welcome


async def test_all_outputs_created(e2e_project: Path, target_dir: Path, mock_agent):
    """All documents are compiled to output."""
    await run(project=e2e_project, target=target_dir, quiet=True)

    assert (target_dir / "compiled" / "greeting.md").exists()
    assert (target_dir / "compiled" / "welcome.md").exists()
    assert (target_dir / "compiled" / "summary.md").exists()


async def test_missing_ref_fails(e2e_project: Path, target_dir: Path, mock_agent):
    """Referencing a non-existent document produces an error."""
    # Add a file with a bad ref
    models_dir = e2e_project / "models"
    (models_dir / "bad.md").write_text("""\
---
name: Bad
---
{{ ref('nonexistent').content }}
""")

    with pytest.raises(SystemExit):
        await run(project=e2e_project, target=target_dir, quiet=True)
