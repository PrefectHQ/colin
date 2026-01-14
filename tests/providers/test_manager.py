"""Tests for provider manager."""

from unittest.mock import MagicMock, patch

import pytest

from colin.api.project import ProviderInstanceConfig
from colin.providers.manager import _get_provider_class, create_provider


class TestGetProviderClass:
    """Tests for _get_provider_class()."""

    def test_returns_builtin_provider(self) -> None:
        """Returns built-in provider class directly."""
        cls = _get_provider_class("http")

        from colin.providers.http import HTTPProvider

        assert cls is HTTPProvider

    def test_returns_file_provider(self) -> None:
        """Returns FileProvider class directly."""
        cls = _get_provider_class("file")

        from colin.providers.file import FileProvider

        assert cls is FileProvider

    def test_lazy_imports_s3_provider(self) -> None:
        """Lazy imports S3 provider when requested."""
        # This test assumes aioboto3 is available (or mocked)
        # In real scenario, if aioboto3 is missing, ImportError bubbles up
        try:
            cls = _get_provider_class("s3")

            from colin.providers.s3 import S3Provider

            assert cls is S3Provider
        except ImportError:
            # If aioboto3 not installed, that's expected
            pytest.skip("aioboto3 not installed")

    def test_caches_lazy_imported_class(self) -> None:
        """Caches lazy imported class after first load."""
        try:
            cls1 = _get_provider_class("s3")
            cls2 = _get_provider_class("s3")

            assert cls1 is cls2
        except ImportError:
            pytest.skip("aioboto3 not installed")

    def test_raises_on_unknown_provider(self) -> None:
        """Raises ValueError for unknown provider type."""
        with pytest.raises(ValueError, match="Unknown provider type"):
            _get_provider_class("unknown")


class TestCreateProviderLazyImport:
    """Tests for create_provider() with lazy imports."""

    def test_creates_s3_provider(self) -> None:
        """Creates S3 provider with config."""
        config = ProviderInstanceConfig(
            provider_type="s3", name=None, config={"region": "us-west-2"}
        )
        provider = create_provider(config)

        from colin.providers.s3 import S3Provider

        assert isinstance(provider, S3Provider)
        assert provider.region == "us-west-2"

    @patch("colin.providers.manager.importlib.import_module")
    def test_lazy_import_failure_propagates_error(self, mock_import_module: MagicMock) -> None:
        """Lazy import failure propagates the ImportError."""
        from colin.providers import manager

        # Reset the cached class to force a new import
        original = manager._PROVIDER_CLASSES["s3"]
        manager._PROVIDER_CLASSES["s3"] = "colin.providers.s3:S3Provider"

        try:
            mock_import_module.side_effect = ImportError("Module not found")
            config = ProviderInstanceConfig(provider_type="s3", name=None, config={})

            with pytest.raises(ImportError, match="Module not found"):
                create_provider(config)
        finally:
            manager._PROVIDER_CLASSES["s3"] = original

    def test_unknown_provider_type_error(self) -> None:
        """Unknown provider type gives clear error with available list."""
        config = ProviderInstanceConfig(provider_type="unknown", name=None, config={})

        with pytest.raises(ValueError, match="Unknown provider type 'unknown'"):
            create_provider(config)

        # Verify error message includes available providers
        try:
            create_provider(config)
        except ValueError as e:
            error_msg = str(e)
            assert "Available:" in error_msg
            assert "http" in error_msg or "https" in error_msg
