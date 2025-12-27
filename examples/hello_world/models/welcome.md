---
name: Welcome Message
description: Demonstrates ref() to include other documents
---

# Welcome

{{ ref('greeting').content }}

---

You just saw an example of `ref()` pulling in content from another document.
Colin automatically compiles documents in the right order based on their dependencies.
