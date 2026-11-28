# Output publication

CompileEngine discovers source documents and parses frontmatter into document
metadata and Colin configuration. TemplateRenderer resolves templates and
providers, and format renderers produce compiled content. Compiled artifacts and
their hashes support dependency resolution and incremental builds.

Publication writes public compiled outputs through the configured Target.
Target.format_content prepares the final content using the output filename and
document metadata. Its default implementation returns the compiled body.
SkillTarget restores discovery metadata for published SKILL.md files, including
when the body comes from cache. ClaudeSkillTarget inherits this behavior.

File-block outputs use their own rendered content. Ownership manifests record
hashes of the published files so target formatting participates in cleanup's
change detection.

See [the publication decision](decisions/001-skill-publication-frontmatter.md)
and [the agent skills guide](running/skills.mdx).
