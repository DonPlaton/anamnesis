---
date: 2026-01-12
project: demo_api
tags: ["api", "pagination", "performance"]
type: decision
resolves: 2026-01-10-demo_api-mistake-n-plus-one-queries
---

# 🎯 Adopt cursor pagination + eager loading

Switched `/posts` from offset to cursor pagination and eager-loaded the author
relation. p95 dropped ~6×. Offset pagination also drifted on concurrent writes.

**Проект:** [[demo_api]]
**Дата:** 2026-01-12

_Решает: [[2026-01-10-demo_api-mistake-n-plus-one-queries]]_

#api #pagination #performance #project/demo_api #decision
