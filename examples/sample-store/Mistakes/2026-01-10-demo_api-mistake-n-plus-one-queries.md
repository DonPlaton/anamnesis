---
date: 2026-01-10
project: demo_api
tags: ["orm", "performance", "database"]
type: mistake
status: resolved
resolved_by: 2026-01-12-demo_api-decision-adopt-cursor-pagination
---

# ⚠️ N+1 queries on the list endpoint

Serializing each item fetched its author with a separate query, so `/posts` fired
1 + N queries and p95 latency exploded under load. Mistaken for a DB capacity issue.

**Как избежать:** eager-load relations the serializer touches (`select_related` /
`joinedload`); assert query count in a test for hot endpoints.

**Проект:** [[demo_api]]
**Дата:** 2026-01-10

#orm #performance #database #project/demo_api #mistake
