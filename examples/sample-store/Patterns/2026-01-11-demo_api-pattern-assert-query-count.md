---
date: 2026-01-11
project: demo_api
tags: ["testing", "performance", "database"]
type: pattern
recurrence: 2
---

# ✅ Assert query count on hot endpoints

Wrap list/detail endpoints in a test that fails if the SQL query count exceeds a
fixed budget. Catches N+1 regressions at PR time instead of in production.

**Как избежать:** keep the budget tight (e.g. ≤ 4) so an accidental lazy-load
trips it immediately.

**Проект:** [[demo_api]]
**Дата:** 2026-01-11

## Связанные заметки
- [[2026-01-10-demo_api-mistake-n-plus-one-queries]]

#testing #performance #database #project/demo_api #pattern
