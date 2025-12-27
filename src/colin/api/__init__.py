"""Programmatic API for Colin operations."""

from colin.api.compile import CompileResult, compile_project
from colin.api.manifest import load_manifest, save_manifest
from colin.api.project import (
    ProjectConfig,
    clean_project,
    create_project,
    find_project_file,
    get_project_status,
    load_project,
    save_project,
)

__all__ = [
    "CompileResult",
    "compile_project",
    "load_manifest",
    "save_manifest",
    "ProjectConfig",
    "find_project_file",
    "load_project",
    "create_project",
    "save_project",
    "get_project_status",
    "clean_project",
]
