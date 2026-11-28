# Preserve skill frontmatter at publication

Skill targets need discovery metadata in SKILL.md. The compiler strips source
frontmatter into document metadata, while compiled artifacts provide body content
to references and incremental builds.

Output targets format content at publication through Target.format_content.
SkillTarget restores non-Colin metadata for SKILL.md. Explicit metadata in the
rendered body takes precedence. The default target returns content unchanged.

Keeping this transformation at publication lets existing cached artifacts work
when switching output targets. It also preserves the meaning of referenced
compiled content. Ownership manifests hash the final published bytes.

File-block outputs already carry their own rendered content and are published
without inheriting the parent document's metadata.
