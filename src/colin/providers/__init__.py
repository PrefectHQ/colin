"""Provider architecture for Colin.

Providers are URI handlers:
- Provider: Base class, reads URIs (can be used for refs)
- Storage: Extends Provider, adds write (can be used for project/artifact storage)

Providers live in providers/*.py (read-only) or providers/storage/*.py (read+write).
Renderers live in renders/*.py (content transformation, separate concern).
"""
