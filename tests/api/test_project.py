"""Tests for project configuration parsing."""

from pathlib import Path

import pytest

from colin.api.project import (
    ProjectConfig,
    _expand_env_vars,
    _expand_env_vars_recursive,
    _parse_providers,
    _parse_vars,
    clean_project,
    create_output_target,
    ensure_project_id,
    generate_project_id,
    get_stale_files,
    init_project,
    load_project,
    save_project,
)
from colin.output import TARGET_REGISTRY


class TestProjectId:
    """Tests for project ID generation and handling."""

    def test_generate_project_id_format(self) -> None:
        """Project ID has format {name}-{6 alphanumeric chars}."""
        project_id = generate_project_id("my-project")

        parts = project_id.rsplit("-", 1)
        assert len(parts) == 2
        assert parts[0] == "my-project"
        assert len(parts[1]) == 6
        assert parts[1].isalnum()
        assert parts[1].islower() or parts[1].isdigit()

    def test_generate_project_id_unique(self) -> None:
        """Each call generates a unique ID."""
        ids = {generate_project_id("test") for _ in range(100)}
        assert len(ids) == 100

    def test_ensure_project_id_returns_existing(self, tmp_path: Path) -> None:
        """ensure_project_id returns existing ID without modification."""
        config_file = tmp_path / "colin.toml"
        config_file.write_text("""\
[project]
name = "test-project"
id = "test-project-abc123"
""")
        config = load_project(config_file)

        result = ensure_project_id(config, config_file)

        assert result == "test-project-abc123"
        # File should not be modified
        content = config_file.read_text()
        assert 'id = "test-project-abc123"' in content

    def test_ensure_project_id_generates_and_saves(self, tmp_path: Path) -> None:
        """ensure_project_id generates and saves ID when missing."""
        config_file = tmp_path / "colin.toml"
        config_file.write_text("""\
[project]
name = "test-project"
""")
        config = load_project(config_file)
        assert config.id is None

        result = ensure_project_id(config, config_file)

        # ID should be generated
        assert result.startswith("test-project-")
        assert len(result.rsplit("-", 1)[1]) == 6

        # Config should be updated
        assert config.id == result

        # File should be updated
        reloaded = load_project(config_file)
        assert reloaded.id == result

    def test_load_project_with_id(self, tmp_path: Path) -> None:
        """load_project reads ID from colin.toml."""
        config_file = tmp_path / "colin.toml"
        config_file.write_text("""\
[project]
name = "test-project"
id = "test-project-x7k2m9"
""")

        config = load_project(config_file)

        assert config.id == "test-project-x7k2m9"

    def test_load_project_without_id(self, tmp_path: Path) -> None:
        """load_project returns None when ID is missing."""
        config_file = tmp_path / "colin.toml"
        config_file.write_text("""\
[project]
name = "test-project"
""")

        config = load_project(config_file)

        assert config.id is None

    def test_save_project_with_id(self, tmp_path: Path) -> None:
        """save_project writes ID to colin.toml."""
        config_file = tmp_path / "colin.toml"

        config = ProjectConfig(
            name="test-project",
            id="test-project-abc123",
            project_root=tmp_path,
            model_path=tmp_path / "models",
            output_path=tmp_path / "output",
            manifest_path=tmp_path / ".colin" / "manifest.json",
        )

        save_project(config_file, config)

        content = config_file.read_text()
        assert 'id = "test-project-abc123"' in content

        reloaded = load_project(config_file)
        assert reloaded.id == "test-project-abc123"

    def test_save_project_without_id(self, tmp_path: Path) -> None:
        """save_project omits ID when None."""
        config_file = tmp_path / "colin.toml"

        config = ProjectConfig(
            name="test-project",
            id=None,
            project_root=tmp_path,
            model_path=tmp_path / "models",
            output_path=tmp_path / "output",
            manifest_path=tmp_path / ".colin" / "manifest.json",
        )

        save_project(config_file, config)

        content = config_file.read_text()
        assert "id = " not in content

    def test_init_project_generates_id(self, tmp_path: Path) -> None:
        """init_project generates a project ID."""
        project_dir = tmp_path / "new-project"
        project_dir.mkdir()

        config_file, _ = init_project(project_dir)
        config = load_project(config_file)

        assert config.id is not None
        assert config.id.startswith("new-project-")
        assert len(config.id.rsplit("-", 1)[1]) == 6


class TestParseProviders:
    """Tests for _parse_providers function."""

    def test_direct_provider_config(self) -> None:
        """[[providers.s3]] without name creates scheme 's3'."""
        data = {
            "s3": [{"bucket": "my-bucket", "region": "us-east-1"}],
        }

        result = _parse_providers(data)

        assert "s3" in result
        assert result["s3"].get_schemes() == ["s3"]
        assert result["s3"].provider_type == "s3"
        assert result["s3"].name is None
        assert result["s3"].config == {"bucket": "my-bucket", "region": "us-east-1"}

    def test_nested_provider_instances(self) -> None:
        """Named instances create dot schemes."""
        data = {
            "s3": [
                {"name": "dev", "bucket": "dev-bucket"},
                {"name": "prod", "bucket": "prod-bucket"},
            ],
        }

        result = _parse_providers(data)

        assert "s3.dev" in result
        assert result["s3.dev"].get_schemes() == ["s3.dev"]
        assert result["s3.dev"].provider_type == "s3"
        assert result["s3.dev"].name == "dev"
        assert result["s3.dev"].config == {"bucket": "dev-bucket"}

        assert "s3.prod" in result
        assert result["s3.prod"].get_schemes() == ["s3.prod"]
        assert result["s3.prod"].provider_type == "s3"
        assert result["s3.prod"].name == "prod"
        assert result["s3.prod"].config == {"bucket": "prod-bucket"}

    def test_empty_provider_config(self) -> None:
        """Empty [[providers.markdown]] creates scheme 'markdown'."""
        data = {
            "markdown": [{}],
        }

        result = _parse_providers(data)

        assert "markdown" in result
        assert result["markdown"].get_schemes() == ["markdown"]
        assert result["markdown"].config == {}

    def test_multiple_provider_types(self) -> None:
        """Multiple provider types are parsed correctly."""
        data = {
            "s3": [{"bucket": "bucket"}],
            "mcp": [
                {"name": "linear", "command": "npx @linear/mcp"},
                {"name": "github", "command": "npx @github/mcp"},
            ],
        }

        result = _parse_providers(data)

        assert "s3" in result
        assert "mcp.linear" in result
        assert "mcp.github" in result

    def test_single_nested_instance(self) -> None:
        """Single named instance parses correctly."""
        data = {
            "mcp": [{"name": "linear", "command": "npx", "args": ["@linear/mcp"]}],
        }

        result = _parse_providers(data)

        assert "mcp.linear" in result
        assert result["mcp.linear"].provider_type == "mcp"
        assert result["mcp.linear"].name == "linear"
        assert result["mcp.linear"].config == {"command": "npx", "args": ["@linear/mcp"]}

    def test_provider_with_list_config(self) -> None:
        """Provider config can contain lists."""
        data = {
            "custom": [{"paths": ["/path/one", "/path/two"], "enabled": True}],
        }

        result = _parse_providers(data)

        assert "custom" in result
        assert result["custom"].config["paths"] == ["/path/one", "/path/two"]
        assert result["custom"].config["enabled"] is True

    def test_deeply_nested_config_treated_as_direct(self) -> None:
        """Nested dicts in config are preserved."""
        data = {
            "api": [
                {
                    "endpoint": "https://api.example.com",
                    "headers": {"Authorization": "Bearer token"},
                }
            ],
        }

        result = _parse_providers(data)

        assert "api" in result
        assert result["api"].get_schemes() == ["api"]
        assert result["api"].config["endpoint"] == "https://api.example.com"
        assert result["api"].config["headers"] == {"Authorization": "Bearer token"}

    def test_no_providers(self) -> None:
        """Empty providers section returns empty dict."""
        result = _parse_providers({})

        assert result == {}

    def test_mcp_provider_url_config(self) -> None:
        """MCP provider can have URL config for remote servers."""
        data = {
            "mcp": [{"name": "remote", "url": "http://localhost:8000/mcp"}],
        }

        result = _parse_providers(data)

        assert "mcp.remote" in result
        assert result["mcp.remote"].config["url"] == "http://localhost:8000/mcp"

    def test_provider_instance_names_with_hyphens(self) -> None:
        """Instance names can contain hyphens."""
        data = {
            "mcp": [{"name": "my-custom-server", "command": "server"}],
        }

        result = _parse_providers(data)

        assert "mcp.my-custom-server" in result
        assert result["mcp.my-custom-server"].name == "my-custom-server"

    def test_provider_schemes_override(self) -> None:
        """schemes explicitly sets which URI schemes the instance handles."""
        data = {
            "s3": [{"name": "dev", "schemes": ["s3", "s3.stage"], "bucket": "dev-bucket"}],
        }

        result = _parse_providers(data)

        # Both schemes map to the same instance
        assert "s3" in result
        assert "s3.stage" in result
        assert result["s3"].name == "dev"
        assert result["s3.stage"].name == "dev"
        assert result["s3"].schemes == ["s3", "s3.stage"]

    def test_provider_schemes_without_name(self) -> None:
        """schemes can be set on unnamed instances."""
        data = {"s3": [{"schemes": ["s3", "aws"], "bucket": "dev-bucket"}]}

        result = _parse_providers(data)

        assert "s3" in result
        assert "aws" in result
        assert result["s3"].name is None
        assert result["s3"].schemes == ["s3", "aws"]

    def test_schemes_strips_uri_suffix(self) -> None:
        """Schemes with :// suffix are cleaned."""
        data = {"s3": [{"schemes": ["s3://", "aws://"]}]}

        result = _parse_providers(data)

        assert result["s3"].schemes == ["s3", "aws"]

    def test_requires_array_of_tables(self) -> None:
        """Providers must use array-of-tables syntax."""
        data = {"s3": {"bucket": "bucket"}}

        with pytest.raises(ValueError, match="array-of-tables"):
            _parse_providers(data)

    def test_duplicate_instance_name_rejected(self) -> None:
        """Duplicate instance names are rejected."""
        data = {
            "s3": [
                {"name": "dev", "bucket": "one"},
                {"name": "dev", "bucket": "two"},
            ],
        }

        with pytest.raises(ValueError, match="duplicate name"):
            _parse_providers(data)


class TestParseVars:
    """Tests for _parse_vars function."""

    def test_simple_string_var(self) -> None:
        """Simple string assignment creates string var with default."""
        data = {"environment": "production"}

        result = _parse_vars(data)

        assert "environment" in result
        assert result["environment"].type == "string"
        assert result["environment"].default == "production"
        assert result["environment"].optional is False

    def test_simple_bool_var(self) -> None:
        """Simple bool value creates bool var with default."""
        data = {"debug": True}

        result = _parse_vars(data)

        assert result["debug"].type == "bool"
        assert result["debug"].default is True

    def test_simple_int_var(self) -> None:
        """Simple int value creates int var with default."""
        data = {"max_items": 100}

        result = _parse_vars(data)

        assert result["max_items"].type == "int"
        assert result["max_items"].default == 100

    def test_simple_float_var(self) -> None:
        """Simple float value creates float var with default."""
        data = {"rate": 3.14}

        result = _parse_vars(data)

        assert result["rate"].type == "float"
        assert result["rate"].default == 3.14

    def test_typed_var_with_default(self) -> None:
        """Typed var with explicit type and default."""
        data = {"date": {"type": "date", "default": "2024-01-15"}}

        result = _parse_vars(data)

        assert result["date"].type == "date"
        assert result["date"].default == "2024-01-15"
        assert result["date"].optional is False

    def test_optional_var_without_default(self) -> None:
        """Optional var can omit default."""
        data = {"historical_date": {"type": "string", "optional": True}}

        result = _parse_vars(data)

        assert result["historical_date"].type == "string"
        assert result["historical_date"].default is None
        assert result["historical_date"].optional is True

    def test_required_var_without_default(self) -> None:
        """Required var has no default and not optional."""
        data = {"api_key": {"type": "string"}}

        result = _parse_vars(data)

        assert result["api_key"].type == "string"
        assert result["api_key"].default is None
        assert result["api_key"].optional is False

    def test_string_default_preserved_verbatim(self) -> None:
        """String defaults are stored verbatim (no Jinja processing)."""
        data = {"date": {"type": "string", "default": "{{ now().strftime('%Y-%m-%d') }}"}}

        result = _parse_vars(data)

        # Stored as literal string - no Jinja evaluation in defaults
        assert result["date"].default == "{{ now().strftime('%Y-%m-%d') }}"

    def test_empty_vars(self) -> None:
        """Empty vars section creates empty dict."""
        result = _parse_vars({})
        assert result == {}

    def test_multiple_vars(self) -> None:
        """Multiple vars are all parsed."""
        data = {
            "env": "production",
            "debug": False,
            "api_key": {"type": "string", "optional": True},
        }

        result = _parse_vars(data)

        assert len(result) == 3
        assert result["env"].type == "string"
        assert result["debug"].type == "bool"
        assert result["api_key"].type == "string"

    def test_case_insensitive_collision_rejected(self) -> None:
        """Variable names that collide case-insensitively are rejected."""
        data = {
            "apiKey": "value1",
            "apikey": "value2",
        }

        with pytest.raises(ValueError, match="collide.*case-insensitive"):
            _parse_vars(data)


class TestEnvVarExpansion:
    """Tests for environment variable expansion in config."""

    def test_expand_single_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Single env var is expanded."""
        monkeypatch.setenv("MY_TOKEN", "secret123")

        result = _expand_env_vars("token=${MY_TOKEN}")

        assert result == "token=secret123"

    def test_expand_multiple_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Multiple env vars in same string are expanded."""
        monkeypatch.setenv("USER", "alice")
        monkeypatch.setenv("HOST", "example.com")

        result = _expand_env_vars("${USER}@${HOST}")

        assert result == "alice@example.com"

    def test_unset_var_becomes_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Unset env var expands to empty string."""
        monkeypatch.delenv("UNSET_VAR", raising=False)

        result = _expand_env_vars("prefix${UNSET_VAR}suffix")

        assert result == "prefixsuffix"

    def test_no_vars_unchanged(self) -> None:
        """String without env vars is unchanged."""
        result = _expand_env_vars("no variables here")

        assert result == "no variables here"

    def test_recursive_expands_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Dict values are recursively expanded."""
        monkeypatch.setenv("SECRET", "hunter2")

        data = {"token": "${SECRET}", "nested": {"key": "${SECRET}"}}
        result = _expand_env_vars_recursive(data)

        assert result == {"token": "hunter2", "nested": {"key": "hunter2"}}

    def test_recursive_expands_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """List items are recursively expanded."""
        monkeypatch.setenv("VAL", "expanded")

        data = ["${VAL}", {"inner": "${VAL}"}]
        result = _expand_env_vars_recursive(data)

        assert result == ["expanded", {"inner": "expanded"}]

    def test_recursive_preserves_non_strings(self) -> None:
        """Non-string values pass through unchanged."""
        data = {"count": 42, "enabled": True, "ratio": 3.14}
        result = _expand_env_vars_recursive(data)

        assert result == {"count": 42, "enabled": True, "ratio": 3.14}

    def test_load_project_expands_env_vars(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """load_project expands env vars in provider config."""
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret123")

        config_file = tmp_path / "colin.toml"
        config_file.write_text("""\
[project]
name = "test-project"

[[providers.github]]
name = "myrepo"
repo = "owner/repo"
token = "${GITHUB_TOKEN}"
""")

        config = load_project(config_file)

        # Check the provider config has the expanded token
        provider_config = config.providers["github.myrepo"]
        assert provider_config.config["token"] == "ghp_secret123"


class TestLoadProject:
    """Tests for load_project function."""

    def test_load_basic_project(self, tmp_path: Path) -> None:
        """Load a basic project config."""
        config_file = tmp_path / "colin.toml"
        config_file.write_text("""\
[project]
name = "test-project"
model-path = "src/models"
output-path = "dist"
""")

        config = load_project(config_file)

        assert config.name == "test-project"
        assert config.project_root == tmp_path
        assert config.model_path == tmp_path / "src/models"
        assert config.output_path == tmp_path / "dist"
        assert config.manifest_path == tmp_path / ".colin" / "manifest.json"

    def test_load_project_with_providers(self, tmp_path: Path) -> None:
        """Load project with provider configuration."""
        config_file = tmp_path / "colin.toml"
        config_file.write_text("""\
[project]
name = "test-project"

[[providers.s3]]
bucket = "my-bucket"

[[providers.mcp]]
name = "linear"
command = "npx @linear/mcp"
""")

        config = load_project(config_file)

        assert "s3" in config.providers
        assert config.providers["s3"].config["bucket"] == "my-bucket"

        assert "mcp.linear" in config.providers
        assert config.providers["mcp.linear"].config["command"] == "npx @linear/mcp"

    def test_load_project_rejects_mcp_section(self, tmp_path: Path) -> None:
        """Legacy mcp section is rejected."""
        config_file = tmp_path / "colin.toml"
        config_file.write_text("""\
[project]
name = "test-project"

[mcp.servers.linear]
command = "npx @linear/mcp"
""")

        with pytest.raises(ValueError, match="providers.mcp"):
            load_project(config_file)

    def test_load_project_with_storage_config(self, tmp_path: Path) -> None:
        """Load project with explicit storage configuration."""
        config_file = tmp_path / "colin.toml"
        config_file.write_text("""\
[project]
name = "test-project"

[project.storage]
provider = "file"
model_path = "custom/models"

[artifacts.storage]
provider = "s3"
bucket = "outputs"
""")

        config = load_project(config_file)

        assert config.project_storage.provider == "file"
        assert config.project_storage.config["model_path"] == "custom/models"

        assert config.artifacts_storage is not None
        assert config.artifacts_storage.provider == "s3"
        assert config.artifacts_storage.config["bucket"] == "outputs"

    def test_load_project_defaults(self, tmp_path: Path) -> None:
        """Load project with minimal config uses defaults."""
        config_file = tmp_path / "colin.toml"
        config_file.write_text("""\
[project]
name = "minimal"
""")

        config = load_project(config_file)

        assert config.name == "minimal"
        assert config.project_root == tmp_path
        assert config.model_path == tmp_path / "models"
        assert config.output_path == tmp_path / "output"
        assert config.manifest_path == tmp_path / ".colin" / "manifest.json"
        assert config.project_storage.provider == "file"
        assert config.artifacts_storage is None
        assert config.providers == {}

    def test_load_project_with_absolute_output_path(self, tmp_path: Path) -> None:
        """Load project with absolute output-path."""
        absolute_output = tmp_path / "absolute_output"
        config_file = tmp_path / "colin.toml"
        config_file.write_text(f"""\
[project]
name = "test-project"
output-path = "{absolute_output}"
""")

        config = load_project(config_file)

        assert config.name == "test-project"
        assert config.project_root == tmp_path
        assert config.output_path == absolute_output.resolve()
        assert config.output_path.is_absolute()
        assert config.manifest_path == tmp_path / ".colin" / "manifest.json"

    def test_save_project_preserves_absolute_output_path(self, tmp_path: Path) -> None:
        """Saving project with absolute output-path preserves it."""
        absolute_output = tmp_path / "absolute_output"
        config_file = tmp_path / "colin.toml"

        # Create config with absolute output path
        config = ProjectConfig(
            name="test-project",
            project_root=tmp_path,
            model_path=tmp_path / "models",
            output_path=absolute_output.resolve(),
            manifest_path=tmp_path / ".colin" / "manifest.json",
        )

        save_project(config_file, config)

        # Reload and verify absolute path is preserved
        reloaded = load_project(config_file)
        assert reloaded.output_path == absolute_output.resolve()
        assert reloaded.output_path.is_absolute()

    def test_save_project_preserves_relative_output_path(self, tmp_path: Path) -> None:
        """Saving project with relative output-path preserves it."""
        config_file = tmp_path / "colin.toml"

        # Create config with relative output path
        config = ProjectConfig(
            name="test-project",
            project_root=tmp_path,
            model_path=tmp_path / "models",
            output_path=tmp_path / "dist",
            manifest_path=tmp_path / ".colin" / "manifest.json",
        )

        save_project(config_file, config)

        # Reload and verify relative path is preserved
        reloaded = load_project(config_file)
        assert reloaded.output_path == tmp_path / "dist"
        # Verify it's saved as relative in TOML
        content = config_file.read_text()
        assert 'output-path = "dist"' in content


class TestGetStaleFiles:
    """Tests for get_stale_files function."""

    def test_no_output_dir_returns_empty(self, tmp_path: Path) -> None:
        """No output directory returns empty list."""
        config_file = tmp_path / "colin.toml"
        config_file.write_text('[project]\nname = "test"')
        config = load_project(config_file)

        result = get_stale_files(config)

        assert result == []

    def test_empty_output_dir_returns_empty(self, tmp_path: Path) -> None:
        """Empty output directory returns empty list."""
        config_file = tmp_path / "colin.toml"
        config_file.write_text('[project]\nname = "test"')
        (tmp_path / "output").mkdir()
        config = load_project(config_file)

        result = get_stale_files(config)

        assert result == []

    def test_identifies_stale_files(self, tmp_path: Path) -> None:
        """Files not in output manifest are identified as stale."""
        import json

        config_file = tmp_path / "colin.toml"
        config_file.write_text('[project]\nname = "test"\nid = "test-abc123"')
        config = load_project(config_file)

        # Create output directory with files
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / "tracked.md").write_text("tracked content")
        (output_dir / "stale.txt").write_text("stale content")

        # Create output manifest that only tracks tracked.md
        output_manifest = {"project_id": "test-abc123", "files": {"tracked.md": "abc123"}}
        (output_dir / ".colin-manifest.json").write_text(json.dumps(output_manifest))

        # Create internal manifest (still needed)
        colin_dir = tmp_path / ".colin"
        colin_dir.mkdir()
        (colin_dir / "manifest.json").write_text(json.dumps({"documents": {}}))

        result = get_stale_files(config)

        assert len(result) == 1
        assert result[0].name == "stale.txt"

    def test_does_not_clean_other_project_files(self, tmp_path: Path) -> None:
        """Files owned by other projects are not considered stale."""
        import json

        config_file = tmp_path / "colin.toml"
        config_file.write_text('[project]\nname = "test"\nid = "test-abc123"')
        config = load_project(config_file)

        # Create output directory with files from another project
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / "other.md").write_text("other project content")

        # Create output manifest owned by a different project
        output_manifest = {"project_id": "other-project-xyz789", "files": {"other.md": "abc123"}}
        (output_dir / ".colin-manifest.json").write_text(json.dumps(output_manifest))

        # Create internal manifest
        colin_dir = tmp_path / ".colin"
        colin_dir.mkdir()
        (colin_dir / "manifest.json").write_text(json.dumps({"documents": {}}))

        result = get_stale_files(config)

        # No stale files - we don't own this directory
        assert result == []

    def test_no_output_manifest_returns_empty(self, tmp_path: Path) -> None:
        """Without output manifest, no files are considered stale in output/."""
        import json

        config_file = tmp_path / "colin.toml"
        config_file.write_text('[project]\nname = "test"\nid = "test-abc123"')
        config = load_project(config_file)

        # Create output directory with files but no manifest
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / "untracked.md").write_text("untracked content")

        # Create internal manifest
        colin_dir = tmp_path / ".colin"
        colin_dir.mkdir()
        (colin_dir / "manifest.json").write_text(json.dumps({"documents": {}}))

        result = get_stale_files(config)

        # No stale files - no output manifest means we don't own anything
        assert result == []

    def test_ignores_compiled_by_default(self, tmp_path: Path) -> None:
        """By default, files in .colin/compiled/ are not considered stale."""
        import json

        config_file = tmp_path / "colin.toml"
        config_file.write_text('[project]\nname = "test"')
        config = load_project(config_file)

        # Create .colin/compiled/ with untracked files
        colin_dir = tmp_path / ".colin"
        compiled_dir = colin_dir / "compiled"
        compiled_dir.mkdir(parents=True)
        (compiled_dir / "untracked.md").write_text("untracked content")

        # Create empty manifest
        manifest = {"documents": {}}
        (colin_dir / "manifest.json").write_text(json.dumps(manifest))

        # Default: only checks output/, not .colin/compiled/
        result = get_stale_files(config)
        assert len(result) == 0

    def test_includes_compiled_when_requested(self, tmp_path: Path) -> None:
        """With include_compiled=True, stale files in .colin/compiled/ are detected."""
        import json

        config_file = tmp_path / "colin.toml"
        config_file.write_text('[project]\nname = "test"')
        config = load_project(config_file)

        # Create .colin/compiled/ with untracked files
        colin_dir = tmp_path / ".colin"
        compiled_dir = colin_dir / "compiled"
        compiled_dir.mkdir(parents=True)
        (compiled_dir / "untracked.md").write_text("untracked content")

        # Create empty manifest
        manifest = {"documents": {}}
        (colin_dir / "manifest.json").write_text(json.dumps(manifest))

        # With include_compiled=True, finds stale files in compiled/
        result = get_stale_files(config, include_compiled=True)
        assert len(result) == 1
        assert result[0].name == "untracked.md"


class TestCleanProject:
    """Tests for clean_project function."""

    def test_clean_removes_stale_files_from_output(self, tmp_path: Path) -> None:
        """clean_project removes stale files from output/."""
        import json

        config_file = tmp_path / "colin.toml"
        config_file.write_text('[project]\nname = "test"\nid = "test-abc123"')
        config = load_project(config_file)

        output_dir = tmp_path / "output"
        output_dir.mkdir()
        tracked_file = output_dir / "tracked.md"
        stale_file = output_dir / "stale.txt"
        tracked_file.write_text("tracked")
        stale_file.write_text("stale")

        # Create output manifest
        output_manifest = {"project_id": "test-abc123", "files": {"tracked.md": "abc123"}}
        (output_dir / ".colin-manifest.json").write_text(json.dumps(output_manifest))

        colin_dir = tmp_path / ".colin"
        colin_dir.mkdir()
        (colin_dir / "manifest.json").write_text(json.dumps({"documents": {}}))

        removed = clean_project(config)

        assert len(removed) == 1
        assert removed[0].name == "stale.txt"
        assert not stale_file.exists()
        assert tracked_file.exists()

    def test_clean_does_not_touch_compiled_directory(self, tmp_path: Path) -> None:
        """clean_project (default) does not remove files from .colin/compiled/."""
        import json

        config_file = tmp_path / "colin.toml"
        config_file.write_text('[project]\nname = "test"\nid = "test-abc123"')
        config = load_project(config_file)

        colin_dir = tmp_path / ".colin"
        compiled_dir = colin_dir / "compiled"
        compiled_dir.mkdir(parents=True)

        compiled_file = compiled_dir / "some_file.md"
        compiled_file.write_text("compiled content")

        manifest = {"documents": {}}
        (colin_dir / "manifest.json").write_text(json.dumps(manifest))

        removed = clean_project(config)

        # Default clean only removes stale files from output/, not .colin/
        assert len(removed) == 0
        assert compiled_file.exists()
        assert (colin_dir / "manifest.json").exists()

    def test_clean_all_removes_stale_from_compiled(self, tmp_path: Path) -> None:
        """clean_project with all=True removes stale files from output/ and .colin/compiled/."""
        import json

        config_file = tmp_path / "colin.toml"
        config_file.write_text('[project]\nname = "test"\nid = "test-abc123"')
        config = load_project(config_file)

        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / "tracked.md").write_text("tracked")
        stale_output = output_dir / "stale.txt"
        stale_output.write_text("stale")

        # Create output manifest
        output_manifest = {"project_id": "test-abc123", "files": {"tracked.md": "abc123"}}
        (output_dir / ".colin-manifest.json").write_text(json.dumps(output_manifest))

        colin_dir = tmp_path / ".colin"
        compiled_dir = colin_dir / "compiled"
        compiled_dir.mkdir(parents=True)
        (compiled_dir / "tracked.md").write_text("tracked compiled")
        stale_compiled = compiled_dir / "stale_compiled.txt"
        stale_compiled.write_text("stale compiled")

        manifest = {
            "documents": {
                "project://tracked.md": {
                    "uri": "project://tracked.md",
                    "source_hash": "abc123",
                    "output_path": "tracked.md",
                    "is_published": True,
                }
            }
        }
        (colin_dir / "manifest.json").write_text(json.dumps(manifest))

        removed = clean_project(config, all=True)

        # Only stale files should be removed (not tracked files or manifest)
        assert len(removed) == 2
        assert not stale_output.exists()
        assert not stale_compiled.exists()
        assert (output_dir / "tracked.md").exists()
        assert (compiled_dir / "tracked.md").exists()
        assert (colin_dir / "manifest.json").exists()


class TestOutputTargets:
    """Tests for output target configuration."""

    def test_create_skill_target(self, tmp_path: Path) -> None:
        """skill target resolves to specified path."""
        target = create_output_target("skill", path="output/skills")

        assert target.resolve_path(tmp_path) == (tmp_path / "output" / "skills").resolve()

    def test_create_claude_skill_target_user_scope(self) -> None:
        """claude-skill target with user scope resolves to ~/.claude/skills."""
        target = create_output_target("claude-skill", scope="user")

        assert target.resolve_path(Path.cwd()) == (Path.home() / ".claude" / "skills").resolve()

    def test_create_unknown_target_raises(self) -> None:
        """Unknown target name raises ValueError."""
        with pytest.raises(ValueError, match="Unknown output target"):
            create_output_target("nonexistent")

    def test_available_targets(self) -> None:
        """Verify expected targets are registered."""
        assert "local" in TARGET_REGISTRY
        assert "skill" in TARGET_REGISTRY
        assert "claude-skill" in TARGET_REGISTRY

    def test_load_project_with_skill_target(self, tmp_path: Path) -> None:
        """Load project with skill target sets output path."""
        config_file = tmp_path / "colin.toml"
        config_file.write_text("""\
[project]
name = "test-project"

[project.output]
target = "skill"
path = "output/skills"
""")

        config = load_project(config_file)

        assert config.output.target == "skill"
        assert config.output_path == (tmp_path / "output" / "skills").resolve()

    def test_load_project_with_claude_skill_target(self, tmp_path: Path) -> None:
        """Load project with claude-skill target."""
        config_file = tmp_path / "colin.toml"
        config_file.write_text("""\
[project]
name = "test-project"

[project.output]
target = "claude-skill"
""")

        config = load_project(config_file)

        assert config.output.target == "claude-skill"
        assert config.output_path == (Path.home() / ".claude" / "skills").resolve()

    def test_load_project_without_output_target(self, tmp_path: Path) -> None:
        """Load project without target uses default output path."""
        config_file = tmp_path / "colin.toml"
        config_file.write_text("""\
[project]
name = "test-project"
output-path = "dist"
""")

        config = load_project(config_file)

        assert config.output.target is None
        assert config.output_path == (tmp_path / "dist").resolve()

    def test_save_project_with_output_target(self, tmp_path: Path) -> None:
        """Save project preserves output target config."""
        from colin.api.project import ProjectOutputConfig

        config_file = tmp_path / "colin.toml"

        config = ProjectConfig(
            name="test-project",
            project_root=tmp_path,
            model_path=tmp_path / "models",
            output_path=tmp_path / "output" / "skills",
            manifest_path=tmp_path / ".colin" / "manifest.json",
            output=ProjectOutputConfig(target="skill", path="output/skills"),
        )

        save_project(config_file, config)

        # Reload and verify
        reloaded = load_project(config_file)
        assert reloaded.output.target == "skill"

    def test_load_project_with_invalid_target_raises(self, tmp_path: Path) -> None:
        """Load project with invalid target raises ValueError."""
        config_file = tmp_path / "colin.toml"
        config_file.write_text("""\
[project]
name = "test-project"

[project.output]
target = "nonexistent-target"
""")

        with pytest.raises(ValueError, match="Unknown output target"):
            load_project(config_file)
