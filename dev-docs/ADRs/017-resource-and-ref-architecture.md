# ADR 017: The Resource and Ref Architecture

**Status**: Accepted  
**Date**: 2026-01-01

---

## 1. Executive Summary

Colin's compilation model is built on a simple principle:

$$\text{Output} = f(\text{Template}, \text{Refs})$$

A document is **fresh** if its template hasn't changed and none of its refs have a different version. This ADR defines the architecture for tracking refs, detecting staleness, and controlling recompilation.

**Key decisions:**

- **Ref is replay instructions**: A Ref contains a method name and args—everything needed to re-fetch the Resource
- **Provider owns Ref creation**: Resources are dumb; Providers give them their Refs
- **Version determines staleness**: `Resource.version` defaults to `hash(content)`, override for semantics or efficiency
- **Implicit tracking**: Provider calls are tracked automatically; use `watch=False` to opt out

---

## 2. Context and Motivation

### The Problems We're Solving

**1. Wrapper Fatigue**

The original design required explicit wrapping:

```jinja
{{ ref(colin.mcp.github.resource("repo://readme")) }}
```

This was verbose, easy to forget, and created silent staleness bugs.

**2. URI Limitations**

String URIs like `mcp://github/issues?q=bug` can't encode complex payloads (SQL queries, JSON arguments) without brittle escaping.

**3. Dispatch Complexity**

Early designs required mapping serialized payloads back to Resource classes for staleness checks. This led to god methods, TypeAdapter complexity, and tight coupling.

### The Core Insight

**A Ref is just replay instructions.** To check if something changed, re-fetch it and compare. The Ref stores the method name and arguments needed to replay that fetch.

This eliminates dispatch tables, TypeAdapters, and registry mappings. The method name *is* the discriminator.

---

## 3. Core Data Structures

### 3.1 The Ref

A `Ref` stores everything needed to replay a fetch:

```python
class Ref(BaseModel):
    provider: str      # e.g., "s3", "mcp", "project"
    connection: str    # e.g., "prod", "github", ""
    method: str        # The provider method to call
    args: dict         # Arguments to that method
```

Examples:

| Scenario      | Ref                                                                                      |
| ------------- | ---------------------------------------------------------------------------------------- |
| S3 file       | `{provider: "s3", connection: "prod", method: "get", args: {key: "config.json"}}`        |
| Search query  | `{provider: "mcp", connection: "github", method: "search_issues", args: {q: "bug"}}`     |
| Single issue  | `{provider: "mcp", connection: "github", method: "get_issue", args: {uri: "issue/123"}}` |
| Project model | `{provider: "project", connection: "", method: "get", args: {path: "strategy/goals"}}`   |

### 3.2 The Resource

A `Resource` is a dumb container—content plus the Ref it was given:

```python
class Resource:
    _content: str
    _ref: Ref
    
    @property
    def content(self) -> str:
        """What gets rendered in templates."""
        return self._content
    
    def ref(self) -> Ref:
        """Return the Ref this Resource was given."""
        return self._ref
    
    @property
    def version(self) -> str:
        """What to compare for change detection. Override for semantics."""
        return hash_content(self.content)
    
    def __str__(self) -> str:
        """Enable {{ resource }} in templates."""
        return self.content
```

**Key point:** Resource doesn't create its own Ref. The Provider creates the Ref and hands it to the Resource. This eliminates coupling—Resource doesn't need to know the Provider's API.

### 3.3 The Version

`version` is what determines staleness. By default, it's a hash of content:

```python
@property
def version(self) -> str:
    return hash_content(self.content)
```

Override when:

**1. There's a cheaper check (ETag):**

```python
class S3Resource(Resource):
    _etag: str
    
    @property
    def version(self) -> str:
        return self._etag  # Already have it from fetch
```

**2. There are volatile fields to exclude:**

```python
class IssueResource(Resource):
    body: str
    status: str
    last_accessed: datetime  # Changes constantly, not semantic
    
    @property
    def version(self) -> str:
        # Exclude last_accessed
        return hash_content(json.dumps({
            "body": self.body,
            "status": self.status,
        }, sort_keys=True))
```

**3. There's a native version concept:**

```python
class DatabaseRow(Resource):
    _row_version: int  # Optimistic concurrency field
    
    @property
    def version(self) -> str:
        return str(self._row_version)
```

---

## 4. The Staleness Protocol

### 4.1 The Core Algorithm

Staleness checking is just replay:

```python
async def is_stale(ref: Ref, old_version: str) -> bool:
    provider = get_provider(ref.provider, ref.connection)
    resource = await provider.replay(ref)
    return resource.version != old_version
```

No dispatch tables. No TypeAdapter mapping. The method name in the Ref tells us what to call.

### 4.2 Provider Replay

```python
class Provider:
    async def replay(self, ref: Ref) -> Resource:
        """Re-execute the method that created this Ref."""
        if not hasattr(self, ref.method):
            raise RefError(f"Unknown method: {ref.method}")
        method = getattr(self, ref.method)
        return await method(**ref.args, watch=False)
```

### 4.3 Argument Serialization

Since Refs are stored in JSON manifests, **provider method arguments must be JSON-serializable**.

Provider methods use Pydantic's `@validate_call` decorator. This serves two purposes:

1. **On initial call:** Validates arguments match type hints
2. **On replay:** Deserializes JSON args back to proper types

```python
from pydantic import validate_call

class MCPProvider(Provider):
    @validate_call
    async def search_issues(self, q: str, labels: list[str] | None = None, watch: bool = True) -> IssueCollection:
        ...
```

At call time: `search_issues(q="bug", labels=["critical"])`
Ref stores: `{"q": "bug", "labels": ["critical"]}`
On replay: `@validate_call` parses JSON back to `str` and `list[str]`

For complex types, use Pydantic models:

```python
class SearchFilters(BaseModel):
    author: str | None = None
    since: datetime | None = None

class MCPProvider(Provider):
    @validate_call
    async def search(self, filters: SearchFilters, watch: bool = True) -> ResultCollection:
        ...
```

Ref stores: `{"filters": {"author": "alice", "since": "2024-01-01T00:00:00Z"}}`
On replay: `@validate_call` deserializes to `SearchFilters` instance.

### 4.4 Optimization Hook

Providers can override `replay` or add a `get_ref_version` for cheap checks:

```python
class S3Provider(Provider):
    async def get_ref_version(self, ref: Ref) -> str:
        """Optimization: HEAD request instead of full GET."""
        if ref.method == "get":
            return await self._head_etag(ref.args["key"])
        # Fall back to full replay
        resource = await self.replay(ref)
        return resource.version
```

The engine tries `get_ref_version` first, falls back to `replay` + `.version`.

---

## 5. Provider Implementation

### 5.1 The Provider's Job

Providers do three things:

1. **Fetch data** — Call external services
2. **Create Resources** — Wrap data with a Ref
3. **Track Refs** — Register with compile context when `watch=True`

```python
class MCPProvider(Provider):
    namespace = "mcp"
    
    def __init__(self, connection: str, **config):
        self._connection = connection
        self._config = config
    
    async def search_issues(self, q: str, watch: bool = True) -> IssueCollection:
        """Search for issues."""
        results = await self._search(q)
        
        # Provider creates ref for each item
        items = [
            IssueResource(
                _content=r["body"],
                _ref=Ref(
                    provider=self.namespace,
                    connection=self._connection,
                    method="get_issue",  # Must exist!
                    args={"uri": r["uri"]},
                ),
            )
            for r in results
        ]
        
        # Provider creates ref for the collection
        collection = IssueCollection(
            items=items,
            _ref=Ref(
                provider=self.namespace,
                connection=self._connection,
                method="search_issues",
                args={"q": q},
            ),
        )
        
        if watch:
            ctx = get_compile_context()
            if ctx:
                ctx.track(collection.ref())
        
        return collection
    
    async def get_issue(self, uri: str, watch: bool = True) -> IssueResource:
        """Fetch a single issue. Required for item-level tracking."""
        data = await self._fetch_issue(uri)
        
        resource = IssueResource(
            _content=data["body"],
            _ref=Ref(
                provider=self.namespace,
                connection=self._connection,
                method="get_issue",
                args={"uri": uri},
            ),
        )
        
        if watch:
            ctx = get_compile_context()
            if ctx:
                ctx.track(resource.ref())
        
        return resource
```

### 5.2 The Item-Level Tracking Constraint

For `ref(item)` to work on collection items, the Provider must have a method to fetch that item individually. The item's Ref points to that method.

**If you can't fetch items individually:**

Three options:

1. **Don't support item promotion** — `ref(item)` raises "This provider doesn't support item-level tracking"

2. **Item ref = collection ref** — Coarse-grained but safe. Any item change triggers collection re-check.

3. **Synthetic identity method** — Provider creates `_fetch_by_id` that filters.

Option 1 is cleanest. Item tracking is a capability, not a requirement.

### 5.3 Default `watch` by Provider Category

Providers define sensible defaults:

| Category                         | Default       | Rationale                      |
| -------------------------------- | ------------- | ------------------------------ |
| **Managed State** (`s3`, `file`) | `watch=True`  | Definitive sources of truth    |
| **MCP Resources**                | `watch=True`  | Explicit data fetch            |
| **MCP Queries**                  | `watch=True`  | Query results are dependencies |
| **Volatile** (`http`)            | `watch=False` | Web is noisy                   |
| **Side Effects** (`mcp.tool`)    | `watch=False` | Actions shouldn't re-run       |

---

## 6. Implicit Dependency Tracking

### 6.1 The Default: Auto-Track

Provider functions automatically register refs when called:

```jinja
{# Auto-tracked: changes trigger recompilation #}
{{ colin.s3.prod.get("config.json") }}

{# Auto-tracked: query changes trigger recompilation #}
{% for issue in colin.mcp.github.search_issues("bug") %}
  {{ issue }}
{% endfor %}
```

No wrapper required.

### 6.2 The `watch` Parameter

Control tracking per-call:

```jinja
{# Not tracked #}
{{ colin.http.get("https://api.example.com/volatile", watch=False) }}

{# Override default to track #}
{{ colin.http.get("https://config.internal/stable.json", watch=True) }}
```

### 6.3 The Logical Dependency Argument

Why auto-track by default? Consider:

```jinja
{% set neighbors = colin.kg.neighbors("node-123") %}
{% for n in neighbors %}
  {% if n.score > 0.9 %}
    {{ ref(n) }}
  {% endif %}
{% endfor %}
```

If `n.score` is 0.2 today (excluded) but 0.95 tomorrow (should be included), the document is **wrong** until recompiled.

You read `n.score` to decide exclusion. That's a logical dependency—you depend on the score being low even though the item was filtered out.

**Auto-tracking the query ensures correctness.** The query's version changes because the result (including scores) changed.

---

## 7. The `ref()` Function

The template `ref()` function serves two purposes:

### 7.1 Project Model References

```jinja
{{ ref("strategy/goals") }}
```

Loads and tracks another Colin model.

### 7.2 Selective Promotion

When you fetch an untracked collection but want to depend on specific items:

```jinja
{% set issues = colin.mcp.github.search_issues("bug", watch=False) %}
{% for issue in issues %}
  {% if issue.priority == "critical" %}
    {{ ref(issue) }}
  {% endif %}
{% endfor %}
```

`ref(issue)` calls `issue.ref()`, registering that item's Ref (not the collection's).

### 7.3 What `ref()` Accepts

| Input      | Behavior                             |
| ---------- | ------------------------------------ |
| `str`      | Project path lookup and registration |
| `Resource` | Calls `.ref()`, registers it         |

### 7.4 The Naming

- `Ref` — the data structure (method + args)
- `Resource` — the runtime object (content + ref + version)
- `ref()` — the template function to register dependencies

Yes, `Ref` and `ref()` overlap. Context disambiguates:

- "the resource's ref" (data)
- "call ref on it" (function)

The symmetry is intentional and worth the brief collision.

---

## 8. The Manifest

### 8.1 What Gets Stored

After each compilation:

```python
class ManifestEntry(BaseModel):
    refs: list[Ref]              # What refs were used
    versions: dict[str, str]     # ref_key → version at compile time
    output_hash: str             # Hash of compiled output
    compiled_at: datetime        # When compilation occurred
```

### 8.2 The Staleness Check

```python
async def is_stale(model: Model, manifest: ManifestEntry) -> bool:
    for ref in manifest.refs:
        provider = get_provider(ref.provider, ref.connection)
        
        # Try cheap version check first
        if hasattr(provider, 'get_ref_version'):
            current = await provider.get_ref_version(ref)
        else:
            resource = await provider.replay(ref)
            current = resource.version
        
        if current != manifest.versions[ref_key(ref)]:
            return True
    
    return False
```

### 8.3 Empirical Tracking

The manifest stores what was *actually used*, not what *might be used*:

```
Compile 1:
  - classify(doc) → "bug"
  - search_issues("bug") → [A, B, C]
  - Manifest: [search_issues("bug")]

Compile 2 check:
  - search_issues("bug") version changed? YES → recompile
  
Compile 2 execution:
  - classify(doc) → "feature"
  - search_issues("feature") → [X, Y, Z]
  - Manifest: [search_issues("feature")]
```

Old refs aren't checked once any ref triggers a rebuild. Manifest updates to current state.

### 8.4 Ref Key Canonicalization

`ref_key(ref)` must produce deterministic keys for manifest lookup:

```python
def ref_key(ref: Ref) -> str:
    # Explicit about identity fields—future Ref fields (timestamps, hints) won't affect key
    return json.dumps({
        "provider": ref.provider,
        "connection": ref.connection,
        "method": ref.method,
        "args": ref.args,
    }, sort_keys=True)
```

---

## 9. Run-Scoped Caching

### 9.1 The Problem

Staleness check and compilation may call the same method:

```python
# Staleness check
resource = await provider.search_issues("bug", watch=False)
current_version = resource.version

# Compilation (if stale)
resource = await provider.search_issues("bug", watch=True)  # Same call!
```

Without caching, we fetch twice.

### 9.2 The Solution

Separate caching from tracking. Cache the fetch; track on every call:

```python
async def search_issues(self, q: str, watch: bool = True) -> IssueCollection:
    # Cached fetch—same args = same result within run
    collection = await self._search_issues_cached(q)

    # Tracking happens on every call, even cache hits
    if watch:
        ctx = get_compile_context()
        if ctx:
            ctx.track(collection.ref())

    return collection

@cached(scope="run")
async def _search_issues_cached(self, q: str) -> IssueCollection:
    # Actual fetch logic
    ...
```

**Key insight:** Cache key must NOT include `watch`. Both `search_issues("bug", watch=False)` and `search_issues("bug", watch=True)` should hit the same cache entry—they fetch the same data, they just differ in whether to track it.

---

## 10. Refresh Policies

### 10.1 The Problem

Staleness detection assumes refs capture all inputs. This breaks when:

- Refs have dynamic inputs from non-ref sources (LLM classification → search)
- Document has no refs (purely generative)
- You want time-based refresh regardless of staleness

### 10.2 The Structure

```yaml
# Shorthand
refresh: always | stale | manual

# Full form
refresh:
  policy: always | stale | manual
  max_age: <duration>  # e.g., "1d", "1h", "1w"
```

### 10.3 Policies

| Policy   | Behavior                                         |
| -------- | ------------------------------------------------ |
| `always` | Recompile every run                              |
| `stale`  | Recompile when any ref version changed (default) |
| `manual` | Only recompile with `--force`                    |

### 10.4 The `max_age` Modifier

`max_age` is orthogonal—applies to any policy:

| Config                           | Recompiles when...              |
| -------------------------------- | ------------------------------- |
| `policy: stale`                  | ref version changed             |
| `policy: stale` + `max_age: 1d`  | ref version changed OR age > 1d |
| `policy: manual`                 | `--force` only                  |
| `policy: manual` + `max_age: 1d` | `--force` OR age > 1d           |

### 10.5 Evaluation Order

```python
async def should_recompile(model: Model, manifest: ManifestEntry | None) -> bool:
    config = model.refresh_config
    
    # Never compiled
    if manifest is None:
        return True
    
    # Policy: always
    if config.policy == "always":
        return True
    
    # max_age check
    if config.max_age:
        age = now() - manifest.compiled_at
        if age > config.max_age:
            return True
    
    # Policy: manual
    if config.policy == "manual":
        return False
    
    # Policy: stale
    return await is_stale(model, manifest)
```

---

## 11. Handling Volatility

### 11.1 Patterns

| Situation                          | Solution          |
| ---------------------------------- | ----------------- |
| Volatile data you don't care about | `watch=False`     |
| Volatile data you do care about    | `refresh: always` |
| Expensive stable content           | `refresh: manual` |
| Time-based refresh                 | `max_age: 1d`     |

### 11.2 The Intermediary Model Pattern

To isolate volatility:

```
models/
  sources/
    raw_search.md      ← refresh: always
  context/
    final_report.md    ← refs raw_search
```

`raw_search.md` recompiles every time. But if its output version matches yesterday's, `final_report.md` sees unchanged ref and skips.

---

## 12. Error Handling

### 12.1 During Staleness Check

| Error                | Behavior                                   |
| -------------------- | ------------------------------------------ |
| Method doesn't exist | Error—Ref is malformed                     |
| Network failure      | Error—don't silently mark fresh            |
| Resource deleted     | Stale—recompile will fail with clear error |
| Auth failure         | Error                                      |

### 12.2 Principle

When in doubt, error out. False freshness (serving stale content) is worse than a failed staleness check.

---

## 13. Worked Example

### 13.1 Template

```jinja
---
colin:
  refresh: stale
---

## Open Issues

{% set issues = colin.mcp.github.search_issues("label:bug", watch=True) %}
{% for issue in issues %}
- [{{ issue.title }}]({{ issue.url }}): {{ issue.summary }}
{% endfor %}

## Critical Issue Details

{% set critical = colin.mcp.github.search_issues("label:critical", watch=False) %}
{% for issue in critical %}
{% if issue.priority == "P0" %}
### {{ issue.title }}

{{ ref(issue) }}
{% endif %}
{% endfor %}
```

### 13.2 Compilation

1. `search_issues("label:bug")` executes
   - Returns `IssueCollection` with 5 items
   - Collection ref registered: `{method: "search_issues", args: {q: "label:bug"}}`

2. `search_issues("label:critical", watch=False)` executes
   - Returns `IssueCollection` with 2 items
   - NOT tracked (watch=False)

3. Loop finds 1 P0 issue, calls `ref(issue)`
   - Item ref registered: `{method: "get_issue", args: {uri: "issue/42"}}`

4. Manifest stores:
   - `search_issues("label:bug")` → version (hash of 5-item list)
   - `get_issue("issue/42")` → version (hash of issue content)

### 13.3 Next Run Staleness Check

1. Replay `search_issues("label:bug")`
   - Returns 6 items now (new bug filed)
   - Version differs → **stale**

2. Skip checking `get_issue("issue/42")` — already stale

3. Recompile

### 13.4 Alternative: Only Issue 42 Changed

1. Replay `search_issues("label:bug")`
   - Same 5 items
   - Version matches → **fresh**

2. Replay `get_issue("issue/42")`
   - Body edited
   - Version differs → **stale**

3. Recompile

---

## 14. Discarded Approaches

### 14.1 String URIs

Rejected. Can't encode complex payloads (SQL, JSON) without brittle parsing.

### 14.2 Resource-Owned Ref Creation

Early design had Resources create their own Refs:

```python
class IssueResource(Resource):
    def ref(self) -> Ref:
        return Ref(method="get_issue", args={"uri": self._uri}, ...)
```

Rejected. Couples Resource to Provider API. What if there's no `get_issue` method?

**Solution:** Provider creates Ref, hands it to Resource.

### 14.3 TypeAdapter Dispatch

Early design used Pydantic discriminated unions to route payloads to Resource classes:

```python
async def get_resource_hash(self, ref: Ref) -> str:
    adapter = TypeAdapter(IssueResource | IssueCollection | RepoResource)
    resource_cls = type(adapter.validate_python(ref.payload))
    return await resource_cls.get_current_hash(ref, self)
```

Rejected. Requires mapping from payload to Resource class. God method in disguise.

**Solution:** Ref stores method name. Replay is just `getattr(provider, ref.method)`.

### 14.4 `kind` Discriminator

Early design had `kind: "call" | "resource"` for framework dispatch.

Rejected. Framework doesn't need to know the difference. Provider handles it via method implementation.

### 14.5 `Address` Naming

Considered keeping `Address` for the serializable structure.

Rejected. `Address` implies location. `Ref` is "how to replay"—closer to the actual semantics.

The `Ref`/`ref()` overlap is acceptable. Context disambiguates.

---

## 15. Summary

| Concept               | Decision                                                          |
| --------------------- | ----------------------------------------------------------------- |
| Serializable identity | `Ref` with provider/connection/method/args                        |
| Runtime object        | `Resource` with content/ref/version                               |
| Version semantics     | Defaults to `hash(content)`, override for efficiency or semantics |
| Staleness check       | Replay ref, compare version                                       |
| Ref creation          | Provider creates, hands to Resource                               |
| Tracking default      | Implicit (auto-track)                                             |
| Opt-out               | `watch=False` parameter                                           |
| Template function     | `ref()` for project paths and selective promotion                 |
| Manifest              | Stores refs + versions from last compilation                      |
| Refresh policies      | `always` \| `stale` \| `manual` + optional `max_age`              |
