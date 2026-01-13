"""Tests for provider template namespaces."""

from collections.abc import Awaitable, Callable
from typing import Any, ClassVar

from colin.compiler.namespace import MCPNamespace, Namespace
from colin.models import Ref
from colin.providers.base import Provider
from colin.providers.manager import ProviderManager
from colin.resources import Resource


class DummyResource(Resource):
    """Simple Resource for testing."""

    def __init__(self, content: str, ref: Ref, path: str) -> None:
        super().__init__(content, ref)
        self.path = path


class DummyProvider(Provider):
    """Simple provider for namespace tests."""

    namespace: ClassVar[str] = "dummy"
    _label: str = ""
    _connection: str = ""

    def __init__(self, namespace_name: str, label: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._label = label
        # Override the class-level namespace for this instance
        # Note: We use a workaround since namespace is a ClassVar
        self.__class__ = type(
            f"DummyProvider_{namespace_name}_{label}",
            (DummyProvider,),
            {"namespace": namespace_name},
        )

    async def get(self, path: str, watch: bool = True) -> DummyResource:
        ref = Ref(
            provider=self.namespace,
            connection=self._connection,
            method="get",
            args={"path": path},
        )
        return DummyResource(
            content=f"{self._label}:{path}",
            ref=ref,
            path=path,
        )

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


class TestMCPNamespace:
    """Tests for MCPNamespace with list_servers() support."""

    def test_list_servers_returns_instance_names(self) -> None:
        """list_servers() returns all configured server names."""
        type_map = {
            "github": Namespace({"resource": lambda: None}, name="mcp.github"),
            "stripe": Namespace({"resource": lambda: None}, name="mcp.stripe"),
            "linear": Namespace({"resource": lambda: None}, name="mcp.linear"),
        }
        mcp_ns = MCPNamespace(type_map, name="mcp")

        result = mcp_ns.list_servers()

        assert result == ["github", "linear", "stripe"]

    def test_list_servers_excludes_internal_keys(self) -> None:
        """list_servers() excludes keys starting with underscore."""
        type_map = {
            "github": Namespace({}, name="mcp.github"),
            "__default__": Namespace({}, name="mcp"),
            "_internal": Namespace({}, name="mcp._internal"),
        }
        mcp_ns = MCPNamespace(type_map, name="mcp")

        result = mcp_ns.list_servers()

        assert result == ["github"]

    def test_list_servers_empty(self) -> None:
        """list_servers() returns empty list when no servers configured."""
        mcp_ns = MCPNamespace({}, name="mcp")

        result = mcp_ns.list_servers()

        assert result == []

    def test_getitem_access(self) -> None:
        """Servers can be accessed via [] syntax."""
        github_ns = Namespace({"resource": "fake"}, name="mcp.github")
        type_map = {"github": github_ns}
        mcp_ns = MCPNamespace(type_map, name="mcp")

        result = mcp_ns["github"]

        assert result is github_ns

    def test_dot_access(self) -> None:
        """Servers can be accessed via dot syntax."""
        github_ns = Namespace({"resource": "fake"}, name="mcp.github")
        type_map = {"github": github_ns}
        mcp_ns = MCPNamespace(type_map, name="mcp")

        result = mcp_ns.github  # type: ignore[attr-defined]

        assert result is github_ns

    def test_list_servers_accessible_as_attribute(self) -> None:
        """list_servers is accessible as an attribute."""
        mcp_ns = MCPNamespace({"github": Namespace({}, name="mcp.github")}, name="mcp")

        assert callable(mcp_ns.list_servers)
        assert mcp_ns.list_servers() == ["github"]


def test_mcp_namespace_in_manager() -> None:
    """MCP provider uses MCPNamespace in manager."""
    manager = ProviderManager()
    manager.register(DummyProvider("mcp", "github"), instance="github")
    manager.register(DummyProvider("mcp", "stripe"), instance="stripe")

    providers = manager.namespace()

    # MCP namespace should have list_servers
    mcp_ns = providers.mcp  # type: ignore[attr-defined]
    assert isinstance(mcp_ns, MCPNamespace)
    assert mcp_ns.list_servers() == ["github", "stripe"]
