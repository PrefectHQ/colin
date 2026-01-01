"""Tests for provider template namespaces."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, ClassVar

from colin.models import Address
from colin.providers.addressable import Addressable
from colin.providers.base import Provider
from colin.providers.manager import ProviderManager


@dataclass
class DummyResource(Addressable):
    """Simple Addressable for testing."""

    path: str
    _content: str

    @property
    def content(self) -> str:
        return self._content

    @property
    def last_updated(self) -> datetime:
        return datetime.now(timezone.utc)

    def address(self) -> Address:
        return Address(provider="dummy", instance="", payload={"path": self.path})


class DummyProvider(Provider):
    """Simple provider for namespace tests."""

    namespace: ClassVar[str] = "dummy"
    _label: str = ""

    def __init__(self, namespace_name: str, label: str, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._label = label
        # Override the class-level namespace for this instance
        # Note: We use a workaround since namespace is a ClassVar
        self.__class__ = type(
            f"DummyProvider_{namespace_name}_{label}",
            (DummyProvider,),
            {"namespace": namespace_name},
        )

    async def load_address(self, payload: dict[str, Any]) -> DummyResource:
        path = payload["path"]
        return DummyResource(path=path, _content=f"{self._label}:{path}")

    def get_functions(self) -> dict[str, Callable[..., Awaitable[object]]]:
        label = self._label

        async def read(path: str) -> str:
            return f"{label}:{path}"

        return {"read": read}


async def test_namespace_default_instance_fallback() -> None:
    """Default instance handles shorthand function calls."""
    manager = ProviderManager()
    # Register default s3 provider (no instance name)
    manager.register(DummyProvider("s3", "default"))
    # Register named instance (same namespace, but instance="dev")
    manager.register(DummyProvider("s3", "dev"), instance="dev")

    providers = manager.namespace()

    # type: ignore needed - Namespace returns object, but works at runtime
    assert await providers.s3.read("config.json") == "default:config.json"  # type: ignore[attr-defined]
    assert await providers.s3.dev.read("config.json") == "dev:config.json"  # type: ignore[attr-defined]
    assert await providers.s3["default"].read("config.json") == "default:config.json"  # type: ignore[index]
