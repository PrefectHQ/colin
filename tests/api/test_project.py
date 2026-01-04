"""Tests for project configuration parsing."""

from pathlib import Path

import pytest

from colin.api.project import ProjectConfig, _parse_providers, load_project, save_project


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


class TestLoadProject:
    """Tests for load_project function."""

    def test_load_basic_project(self, tmp_path: Path) -> None:
        """Load a basic project config."""
        config_file = tmp_path / "colin.toml"
        config_file.write_text("""\
[project]
name = "test-project"
model-path = "src/models"
target-path = "dist"
""")

        config = load_project(config_file)

        assert config.name == "test-project"
        assert config.project_root == tmp_path
        assert config.model_path == tmp_path / "src/models"
        assert config.target_path == tmp_path / "dist"
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
        assert config.target_path == tmp_path / "target"
        assert config.manifest_path == tmp_path / ".colin" / "manifest.json"
        assert config.project_storage.provider == "file"
        assert config.artifacts_storage is None
        assert config.providers == {}

    def test_load_project_with_absolute_target_path(self, tmp_path: Path) -> None:
        """Load project with absolute target-path."""
        absolute_target = tmp_path / "absolute_output"
        config_file = tmp_path / "colin.toml"
        config_file.write_text(f"""\
[project]
name = "test-project"
target-path = "{absolute_target}"
""")

        config = load_project(config_file)

        assert config.name == "test-project"
        assert config.project_root == tmp_path
        assert config.target_path == absolute_target.resolve()
        assert config.target_path.is_absolute()
        assert config.manifest_path == tmp_path / ".colin" / "manifest.json"

    def test_save_project_preserves_absolute_target_path(self, tmp_path: Path) -> None:
        """Saving project with absolute target-path preserves it."""
        absolute_target = tmp_path / "absolute_output"
        config_file = tmp_path / "colin.toml"

        # Create config with absolute target path
        config = ProjectConfig(
            name="test-project",
            project_root=tmp_path,
            model_path=tmp_path / "models",
            target_path=absolute_target.resolve(),
            manifest_path=tmp_path / ".colin" / "manifest.json",
        )

        save_project(config_file, config)

        # Reload and verify absolute path is preserved
        reloaded = load_project(config_file)
        assert reloaded.target_path == absolute_target.resolve()
        assert reloaded.target_path.is_absolute()

    def test_save_project_preserves_relative_target_path(self, tmp_path: Path) -> None:
        """Saving project with relative target-path preserves it."""
        config_file = tmp_path / "colin.toml"

        # Create config with relative target path
        config = ProjectConfig(
            name="test-project",
            project_root=tmp_path,
            model_path=tmp_path / "models",
            target_path=tmp_path / "dist",
            manifest_path=tmp_path / ".colin" / "manifest.json",
        )

        save_project(config_file, config)

        # Reload and verify relative path is preserved
        reloaded = load_project(config_file)
        assert reloaded.target_path == tmp_path / "dist"
        # Verify it's saved as relative in TOML
        content = config_file.read_text()
        assert 'target-path = "dist"' in content
