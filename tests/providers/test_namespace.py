"""Tests for provider template namespaces."""

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from colin.models import Manifest, RefResult
from colin.providers.base import Provider
from colin.providers.context import ProviderContext
from colin.providers.manager import ProviderManager
from colin.providers.referenceable import Referenceable


class DummyProvider(Provider):
    """Simple provider for namespace tests."""

    def __init__(self, namespace: str, label: str) -> None:
        self.schemes = [namespace]
        self.namespace = namespace
        self._label = label

    async def read(self, uri: str) -> str:
        return f"{self._label}:{uri}"

    def get_functions(self) -> dict[str, Callable[..., Awaitable[object]]]:
        async def read(ctx: ProviderContext, path: str) -> str:
            return f"{self._label}:{path}"

        return {"read": read}


async def _fake_ref(target: str | Referenceable) -> RefResult:
    # In tests, we only pass strings
    uri = target if isinstance(target, str) else target.uri
    return RefResult(
        name="ref",
        description=None,
        content="content",
        template="",
        updated=datetime.now(timezone.utc),
        uri=uri,
    )


async def _fake_extract(content: str, prompt: str, call_id: str | None, model: str | None) -> str:
    return f"{prompt}:{content}:{call_id}:{model}"


def _make_context() -> ProviderContext:
    return ProviderContext(
        manifest=Manifest(),
        document_uri="project://test.md",
        doc_state=None,
        ref=_fake_ref,
        track_ref=lambda _uri: None,
        extract=_fake_extract,
    )


async def test_namespace_default_instance_fallback() -> None:
    """Default instance handles shorthand function calls."""
    manager = ProviderManager()
    # Register default s3 provider (no instance name)
    manager.register(DummyProvider("s3", "default"))
    # Register named instance (same namespace, but instance="dev")
    dev_provider = DummyProvider("s3", "dev")
    dev_provider.schemes = ["s3.dev"]  # Different scheme for routing
    manager.register(dev_provider, instance="dev")

    providers = manager.namespace(_make_context())

    # type: ignore needed - Namespace returns object, but works at runtime
    assert await providers.s3.read("config.json") == "default:config.json"  # type: ignore[attr-defined]
    assert await providers.s3.dev.read("config.json") == "dev:config.json"  # type: ignore[attr-defined]
    assert await providers.s3["default"].read("config.json") == "default:config.json"  # type: ignore[index]
