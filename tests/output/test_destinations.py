"""Tests for output targets."""

from pathlib import Path

from colin.output import ClaudeSkillTarget, LocalTarget, SkillTarget


class TestLocalTarget:
    """Tests for LocalTarget."""

    def test_name(self) -> None:
        """Local target has correct name."""
        target = LocalTarget(path="output")
        assert target.name == "local"

    def test_resolve_path_relative(self, tmp_path: Path) -> None:
        """Local target resolves relative path to project root."""
        target = LocalTarget(path="output")
        result = target.resolve_path(tmp_path)
        assert result == (tmp_path / "output").resolve()

    def test_resolve_path_absolute(self, tmp_path: Path) -> None:
        """Local target uses absolute path as-is."""
        abs_path = tmp_path / "custom" / "output"
        target = LocalTarget(path=str(abs_path))
        result = target.resolve_path(tmp_path / "other")
        assert result == abs_path.resolve()

    def test_manifest_locations_default(self) -> None:
        """Local target returns root manifest for any file structure."""
        target = LocalTarget(path="output")

        # Single file
        assert target.get_manifest_locations(["file.md"]) == [""]

        # Multiple files
        assert target.get_manifest_locations(["a.md", "b.md", "c.md"]) == [""]

        # Files in subdirectories
        assert target.get_manifest_locations(["dir/file.md", "other/file.md"]) == [""]

        # Empty list
        assert target.get_manifest_locations([]) == [""]


class TestSkillTarget:
    """Tests for SkillTarget."""

    def test_name(self) -> None:
        """Skill target has correct name."""
        target = SkillTarget(path="output/skills")
        assert target.name == "skill"

    def test_resolve_path(self, tmp_path: Path) -> None:
        """Skill target resolves to specified path."""
        target = SkillTarget(path="output/skills")
        result = target.resolve_path(tmp_path)
        assert result == (tmp_path / "output" / "skills").resolve()

    def test_manifest_locations_single_subdir(self) -> None:
        """Single subdirectory returns that dir."""
        target = SkillTarget(path="output/skills")
        files = ["stripe/SKILL.md", "stripe/greet.md", "stripe/calculate.md"]
        assert target.get_manifest_locations(files) == ["stripe"]

    def test_manifest_locations_multiple_subdirs(self) -> None:
        """Multiple subdirectories return sorted list."""
        target = SkillTarget(path="output/skills")
        files = [
            "stripe/SKILL.md",
            "stripe/greet.md",
            "github/SKILL.md",
            "github/issues.md",
            "linear/SKILL.md",
        ]
        assert target.get_manifest_locations(files) == ["github", "linear", "stripe"]

    def test_manifest_locations_root_files_only(self) -> None:
        """Files only at root return root manifest."""
        target = SkillTarget(path="output/skills")
        files = ["SKILL.md", "tool.md", "README.md"]
        assert target.get_manifest_locations(files) == [""]

    def test_manifest_locations_mixed(self) -> None:
        """Mix of root and subdirectory files returns subdirs only."""
        target = SkillTarget(path="output/skills")
        # Root files don't create manifests when there are subdirs
        files = ["stripe/SKILL.md", "README.md", "github/SKILL.md"]
        assert target.get_manifest_locations(files) == ["github", "stripe"]

    def test_manifest_locations_empty(self) -> None:
        """Empty file list returns root manifest."""
        target = SkillTarget(path="output/skills")
        assert target.get_manifest_locations([]) == [""]

    def test_manifest_locations_nested_paths(self) -> None:
        """Deeply nested paths use first-level dir."""
        target = SkillTarget(path="output/skills")
        files = [
            "stripe/scripts/greet.py",
            "stripe/SKILL.md",
            "github/docs/README.md",
        ]
        assert target.get_manifest_locations(files) == ["github", "stripe"]


class TestClaudeSkillTarget:
    """Tests for ClaudeSkillTarget."""

    def test_name(self) -> None:
        """Claude skill target has correct name."""
        target = ClaudeSkillTarget()
        assert target.name == "claude-skill"

    def test_resolve_path_user_scope(self, tmp_path: Path) -> None:
        """User scope resolves to ~/.claude/skills/."""
        target = ClaudeSkillTarget(scope="user")
        result = target.resolve_path(tmp_path)
        assert result == (Path.home() / ".claude" / "skills").resolve()

    def test_resolve_path_default_is_user(self, tmp_path: Path) -> None:
        """Default scope is user."""
        target = ClaudeSkillTarget()
        result = target.resolve_path(tmp_path)
        assert result == (Path.home() / ".claude" / "skills").resolve()

    def test_resolve_path_project_scope_with_claude_dir(self, tmp_path: Path) -> None:
        """Project scope finds .claude dir above project."""
        # Create .claude dir at project root
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()

        target = ClaudeSkillTarget(scope="project")
        result = target.resolve_path(tmp_path)
        assert result == (claude_dir / "skills").resolve()

    def test_resolve_path_project_scope_walks_up(self, tmp_path: Path) -> None:
        """Project scope walks up to find .claude dir."""
        # Create .claude dir at parent
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()

        # Project is in subdirectory
        project_dir = tmp_path / "projects" / "my-project"
        project_dir.mkdir(parents=True)

        target = ClaudeSkillTarget(scope="project")
        result = target.resolve_path(project_dir)
        assert result == (claude_dir / "skills").resolve()

    def test_resolve_path_project_scope_no_claude_dir(self, tmp_path: Path) -> None:
        """Project scope creates in project root if no .claude found."""
        target = ClaudeSkillTarget(scope="project")
        result = target.resolve_path(tmp_path)
        # Falls back to project root
        assert result == (tmp_path / ".claude" / "skills").resolve()

    def test_resolve_path_custom_path(self, tmp_path: Path) -> None:
        """Custom path overrides scope default."""
        custom = tmp_path / "custom" / "skills"
        target = ClaudeSkillTarget(path=str(custom))
        result = target.resolve_path(tmp_path / "other")
        assert result == custom.resolve()

    def test_manifest_locations_same_as_skill(self) -> None:
        """Claude skill uses same manifest logic as skill target."""
        target = ClaudeSkillTarget()
        files = ["stripe/SKILL.md", "github/SKILL.md"]
        assert target.get_manifest_locations(files) == ["github", "stripe"]
