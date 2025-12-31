# Everything Example

This example demonstrates all Colin features with a realistic multi-level dependency graph.

## Dependency Graph

```
Level 0 (base):     data.md          goals.md
                       \                /
Level 1:            analysis.md    goal_status.md
                          \          /
Level 2:              recommendations.md
                              |
Level 3:              executive_brief.md
```

## Features Demonstrated

| Feature | File | Usage |
|---------|------|-------|
| `ref()` | all | Reference other documents |
| `ref().content` | goal_status, executive_brief | Access compiled content |
| `| llm_extract()` | analysis, recommendations, executive_brief | LLM extraction filter |
| `{% llm %}` | goal_status, recommendations | LLM generation blocks |
| Frontmatter | all | Document metadata |
| Multi-level deps | executive_brief | 3 levels of dependencies |

## Running

```bash
cd examples/everything
colin run
```

## Parallel Compilation

With our DAG-based parallel compilation:
- Level 0: `data.md` and `goals.md` compile in parallel
- Level 1: `analysis.md` and `goal_status.md` compile in parallel
- Level 2: `recommendations.md` compiles
- Level 3: `executive_brief.md` compiles
