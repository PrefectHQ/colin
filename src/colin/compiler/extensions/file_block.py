"""File block extension for Jinja - creates additional output files."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from jinja2 import nodes
from jinja2.exceptions import TemplateSyntaxError
from jinja2.ext import Extension

if TYPE_CHECKING:
    from jinja2 import Environment
    from jinja2.parser import Parser


@dataclass
class FileOutput:
    """Content and metadata for a file created via {% file %} block."""

    content: str
    publish: bool | None = None  # None = inherit from source document
    format: str = "markdown"  # renderer to apply
    sections: dict[str, str] = field(default_factory=dict)  # scoped sections
    output_hash: str | None = None  # content hash for staleness tracking


class FileBlockExtension(Extension):
    """Jinja extension for {% file %}...{% endfile %} blocks.

    Creates additional output files from a single source template.
    Arguments mirror OutputConfig: path (required), format, publish.

    Usage:
        {% file "data.json" format="json" %}
        {% item %}
        ## Name
        Alice
        {% enditem %}
        {% endfile %}

        {% file "config.yaml" format="yaml" publish=true %}
        name: {{ vars.name }}
        {% endfile %}

        {% file "notes.md" %}
        Just some markdown content.
        {% endfile %}

    Sections inside file blocks are scoped to that file only:
        {% file "output.md" %}
        {% section summary %}
        This section belongs to output.md, not the parent document.
        {% endsection %}
        {% endfile %}

    Access via: ref("output.md").sections.summary
    """

    tags = {"file"}

    def __init__(self, environment: Environment) -> None:
        """Initialize the extension."""
        super().__init__(environment)

    def parse(self, parser: Parser) -> nodes.Node:
        """Parse the {% file "path" %} block."""
        lineno = next(parser.stream).lineno

        # Parse required path argument (any expression, typically string or concatenation)
        path = parser.parse_expression()

        # Parse optional keyword arguments: format, publish
        kwargs: list[nodes.Keyword] = []

        while parser.stream.current.test("name"):
            key = parser.stream.current.value
            if key not in ("format", "publish"):
                raise TemplateSyntaxError(
                    f"{{% file %}} got unexpected keyword argument '{key}'. "
                    "Valid options: format, publish",
                    lineno=lineno,
                )
            parser.stream.skip()
            parser.stream.expect("assign")
            value = parser.parse_expression()
            kwargs.append(nodes.Keyword(key, value, lineno=lineno))

            # Handle optional comma between kwargs
            if parser.stream.current.test("comma"):
                parser.stream.skip()

        # Parse body until {% endfile %}
        body = parser.parse_statements(("name:endfile",), drop_needle=True)

        # Return CallBlock that invokes _render_file with path and kwargs
        return nodes.CallBlock(
            self.call_method("_render_file", [path], kwargs),
            [],
            [],
            body,
        ).set_lineno(lineno)

    async def _render_file(
        self,
        file_path: str,
        format: str = "markdown",  # noqa: A002 - matches OutputConfig field name
        publish: bool | None = None,
        caller: object = None,
    ) -> str:
        """Called during template rendering.

        Renders the body, applies format rendering, extracts sections,
        and stores the result in the compile context.

        Args:
            file_path: Relative path for the output file.
            format: Output format (json, yaml, markdown). Default "markdown".
            publish: Whether to publish to output/. None = inherit from source.
            caller: Async callable that renders the block body.

        Returns:
            Empty string (file content doesn't appear in main output).
        """
        if caller is None:
            raise RuntimeError("No caller provided to file block")

        # Validate path
        self._validate_path(file_path)

        # Get compile context
        from colin.compiler.cache import get_compile_context

        context = get_compile_context()
        if context is None:
            # No context (shouldn't happen in normal compilation)
            raise RuntimeError("No compile context available for {% file %} block")

        # Check for duplicate path
        if file_path in context.file_outputs:
            raise ValueError(
                f"Duplicate file output path: '{file_path}'. "
                "Each {% file %} block must have a unique path."
            )

        # Render the body content
        body_content = await caller()

        # Extract sections and remove section/defer markers BEFORE format rendering
        # (JSON/YAML renderers can't parse content with section markers)
        # Keep item markers - the renderer needs them to detect arrays
        from colin.compiler.section_parser import (
            parse_sections,
            remove_section_and_defer_markers,
        )

        sections = parse_sections(body_content)
        clean_body = remove_section_and_defer_markers(body_content)

        # Apply format renderer
        from colin.renders import get_renderer

        renderer = get_renderer(format)

        # Create a minimal output config for the renderer
        from colin.models import OutputConfig

        output_config = OutputConfig(format=format, path=file_path)

        # Render through the format renderer
        # Use a synthetic URI for error messages
        render_result = renderer.render(clean_body, f"file://{file_path}", output_config)

        # Final content (renderer may have transformed it)
        clean_content = render_result.content

        # Compute content hash for staleness tracking
        import hashlib

        output_hash = hashlib.sha256(clean_content.encode()).hexdigest()[:16]

        # Store in context
        context.file_outputs[file_path] = FileOutput(
            content=clean_content,
            publish=publish,
            format=format,
            sections=sections,
            output_hash=output_hash,
        )

        # Track file output in state for progress display
        if context.doc_state is not None:
            from colin.compiler.state import Status

            op = context.doc_state.child("file", detail=file_path)
            op.status = Status.DONE

        # Return empty string - file content doesn't appear in main output
        return ""

    def _validate_path(self, path: str) -> None:
        """Validate file path is safe.

        Args:
            path: The path to validate.

        Raises:
            ValueError: If path is invalid.
        """
        p = Path(path)

        # Reject absolute paths
        if p.is_absolute():
            raise ValueError(f"{{% file %}} path must be relative, got absolute path: {path}")

        # Reject paths that escape via ..
        if ".." in p.parts:
            raise ValueError(f"{{% file %}} path cannot contain '..': {path}")

        # Reject empty path
        if not path or path.isspace():
            raise ValueError("{% file %} path cannot be empty")
