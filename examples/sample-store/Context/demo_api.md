---
date: 2026-01-12
project: demo_api
tags: ["api", "performance"]
type: context
---

# Context: demo_api

Живой контекст проекта. Обновляется автоматически hook'ом после каждой сессии.

#api #performance #context

---

<!-- PROJECT-CARD:START -->
## 🗂 Карточка проекта

**Статус:** cursor pagination shipped; list endpoint p95 down ~6×
**Стек/темы:** performance, database, api, orm, testing, pagination

**🎯 Ключевые решения:**
- **Adopt cursor pagination + eager loading**: Switched /posts from offset to cursor pagination and eager-loaded the author relation. p95 dropped ~6×.

**🔁 Повторяется (recurrence≥2):**
- **Assert query count on hot endpoints** ×2: fail a test if SQL query count exceeds a fixed budget → catches N+1 regressions at PR time.
<!-- PROJECT-CARD:END -->

## 2026-01-12 14:30
Shipped cursor pagination for the posts API; resolved the N+1 latency issue.

Сессия: [[2026-01-12-1430-demo_api-session-a1b2c3d4]]
Решения: [[2026-01-12-demo_api-decision-adopt-cursor-pagination]]
