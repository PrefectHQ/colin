---
colin:
  output:
    publish: false
---

## Quick Reference

**Providers** fetch from external sources:
- `colin.github.file(repo, path)` - GitHub files
- `colin.linear.issues(team=...)` - Linear issues
- `colin.notion.page(url)` - Notion pages

**References** connect documents:
- `ref('doc.md').content` - include another document's content

**LLM processing** transforms content:
- `ref('doc.md').content | llm_extract('prompt')` - extract specific information
