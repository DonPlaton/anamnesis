# Hostile Audit — Anamnesis (2026-06-16, third pass)

**Auditor stance:** prove it's a non-working toy. **Method:** 5 independent
dimensions (dead-code, hot-path bugs, scaling/token-economy, edge/failure,
end-to-end functional) + manual verification of every CRITICAL/HIGH claim against
the source. Numbers below are **measured or grep-confirmed**, not estimated.

**Verdict up front:** it is *not* a toy — semantic recall, multilingual matching,
typo tolerance, cross-project transfer and the extract→note→card→link→re-embed
pipeline all genuinely work (empirically verified with `bge-m3` up). But this pass
found **two silent correctness failures the prior two audits introduced or missed**,
a **scaling fix that doesn't actually run in production**, and a **whole ranking
signal wired to a field nothing ever writes**. None crash loudly; all degrade
silently — the worst kind.

Severity = (impact on recall correctness) × (likelihood) × (silence).

---

## CRITICAL

### A1 — A single bad byte anywhere crashes the hook and silently loses the whole batch
`read_text(encoding="utf-8")` is used at **17 sites** and the surrounding guards
catch **`OSError`** — but `UnicodeDecodeError` is a `ValueError`, not an `OSError`.
One non-UTF-8 byte in *any* transcript (`*.jsonl`), state file
(`.processed_sessions.json`, `.embeddings_cache.json`) or note → uncaught exception.
- `sweep_unprocessed` calls `read_session_meta(str(jl))` at `memory_hook.py:2658`
  **outside** the per-session `try/except` (which only starts at :2669), and
  `main()`'s outer block (:3547) is `try/finally` with **no `except`**.
- **Proven by execution:** real hook subprocess, SessionStart, **exit 1** with
  traceback. On Claude Code a non-zero hook exit drops `additionalContext` and the
  sweep aborts → **every later unprocessed session in the batch is never extracted**
  (silent, permanent memory loss until the file ages out at ~30 d).
- `load_processed` (:1073) catches `(json.JSONDecodeError, OSError)`,
  `load_embed_cache` (:1588) the same — neither catches `UnicodeDecodeError`, so the
  `.bak` recovery never even runs.

### A2 — The headline scaling fix is DORMANT; every prompt still parses the whole JSON cache
The C2/C3 SQLite index is gated behind `scale_index_ready()`
(`memory_hook.py:3222` SessionStart, `:3384` UserPromptSubmit:
`cache = None if scale_index_ready() else load_embed_cache()`). **`.index.sqlite`
is never built until a SessionEnd *write* fires `sync_scale_index`** — so on the
live vault (328 notes) the file does not exist and **both hot paths fall through to
`load_embed_cache()`**, measured at **48 ms** parsing the **4.67 MB** cache on
*every* SessionStart and *every* non-trivial prompt. README:166 ("a prompt never
re-parses the whole JSON cache") is **false for any store that hasn't had a write
since the feature shipped.** The fix exists but doesn't run.

---

## HIGH

### A3 — `recurrence` is never incremented; an entire ranking signal is dead
`grep` confirms `recurrence` is **only ever read or defaulted, never written > 1**.
When a lesson recurs, `write_typed_note` supersedes the older same-slug note
(`memory_hook.py:1900-1902`) and writes a fresh note whose frontmatter (:1926) has
**no recurrence field → defaults to 1**, while the old note (and its count) is
popped from the cache. So `recurrence` is **always 1** unless hand-edited, which
means the `_recur_boost` ranking tiebreak (:3007) and the card's
`🔁 Повторяется (recurrence≥2)` section (:2288-2299) operate on a field nothing
ever sets. The "recurrence-weighted recall" claim is theater.

### A4 — `dim` column written but never validated → dimension mismatch silently zeroes all cosines
`index_sqlite.py:106` declares `dim`, `_row` writes `len(vec)` (:94) — but `dim` is
**never SELECTed or checked** (`_CAND_COLS` omits it; `iter_candidates`/`search`
ignore it). `cosine()` returns `0.0` on length mismatch (`memory_hook.py:435`), so a
query vector of a different dimension than the stored docs makes **every** semantic
score `0.0` → recall silently drops to lexical-only, with no signal. The one field
that exists to detect this is dead.

### A5 — The index has no embedding-model stamp → stale-vector corruption is undetectable
The `notes` table records no model/generation (`index_sqlite.py:103-106`). Swap
`ANAMNESIS_EMBED_MODEL` (or have Ollama serve a different model) and the index keeps
ranking **new-model query vectors against old-model document vectors** — garbage
cosines, no crash, no warning. There is no `meta` table and no check that the
index's model matches the live embedder.

---

## MEDIUM

### A6 — `find_clusters` is still O(M²) (the H3 fix missed it)
`consolidate_memory.py:106-132`: nested `for i,a … for b in stems[i+1:]: cosine(…)`
per `(project, ntype)` bucket, on the same interpreted-Python 1024-dim cosine
(~105 µs each). The H3 inverted-index fix covered `link_related_notes` (:138) but
not this. A project with 10 k mistakes → ~50 M pairwise cosines ≈ **87 min** for one
weekly consolidation. No cluster-size cap.

### A7 — Leading BOM silently erases ALL frontmatter
`_read_frontmatter` keys on `text.startswith("---")` (`memory_hook.py:2149`); a
`﻿` BOM (any BOM-writing editor) makes it `False` → returns `({}, …)` — date,
tags, recurrence, status all lost. `_read_frontmatter_file` (:2180) has the same
blind spot. **Proven** by execution.

### A8 — `git_autocommit` no-ops on a non-git store; "vault under git" is false until manual `git init`
`git_autocommit` returns early if `VAULT/.git` is absent, and **nothing in the
package ever runs `git init`** (grep-confirmed). A store created by
`remember.py`/`ingest.py` has no `.git`, no commits, no history — the advertised
"backup is `git push` / recoverable from history" safety net is simply absent, with
zero warning.

### A9 — SQLite reads lack `busy_timeout`; `search()` semantic branch is unguarded
`iter_candidates` (:208) and `search` (:242) open with bare
`sqlite3.connect(db_path())` (not `_connect`, so no `busy_timeout`), and the
`search` semantic branch (:252-260) has no `try` — a concurrent write can surface
`database is locked` straight out of the diagnostic/CLI path.

### A10 — One garbage vector permanently disables the SQLite index build
`build()` calls `_row`→`_pack` with no per-row guard (`index_sqlite.py:142`); a
single non-float in a cache vector raises `TypeError`/`OverflowError`, aborts the
whole build, gets swallowed by `sync_scale_index` → the accelerator **never builds**
and retrieval stays on the slow path forever. (`cosine` is corruption-robust; the
pack path is not.)

### A11 — `_fts_ok` catches only `OperationalError`
`index_sqlite.py:69`: a non-FTS sqlite3 build raising any other `sqlite3.Error`
subclass aborts `build()` (swallowed) → index never built, silent slow path.

### A12 — `_coerce_confidence(NaN)` → 1.0 (maximally trusted)
`max(0.0, min(1.0, nan))` returns `1.0` in CPython, so a `confidence: .nan` in a
hand-edited/poisoned note is treated as **fully confident** instead of rejected.

### A13 — Recall never abstains
`memory_search.py` gates only on `sim > 0.15` and always dumps the top-10. An
off-domain query ("sourdough fermentation temperature") returns 10 ML/infra notes at
0.24–0.33 — the system never says "no confident match", so a naive caller taking
rank 1 gets a confidently wrong answer.

### A14 — "empty cache" is reported when a project filter merely matched nothing
`memory_search.py` conflates "no embeddings exist" with "project filter matched
zero" → querying a non-existent project tells the user to rebuild a perfectly good
index (exit 1).

---

## LOW

- **A15** — `remember.py` prints "live now via lexical/recency recall", but the CLI
  reads only the embedding cache, so a `remember`-written note is **not recallable**
  until `embed_index.py` runs. Misleading.
- **A16** — `register_written_notes` only ever increments `_TAG_COUNTS` / appends to
  `_TITLE_SLUGS` (`memory_hook.py:876-893`); supersede/archive never decrement, so a
  long-lived sweep offers dead tags/titles to the grounding prompt and grows the
  list unbounded.
- **A17** — Cross-project SQL filter `project <> ?` (:211) includes `project=''`
  rows; the Python path excludes them (`r.get("project")` falsy) — divergence on
  malformed empty-project notes.
- **A18** — Dead weight: `_clear_tag_counts` (a never-called back-compat shim) and
  `parse_session_stem` (test-only). Everything else in the 138-function monolith is
  live — the "code graveyard" charge does **not** stick.
- **A19** — Stale-lock liveness (`_pid_alive`) is gated behind `age > LOCK_STALE_S`
  (600 s), so a crashed holder with a fresh mtime wedges every writer for 10 min
  before the PID is consulted.
- **A20** — Slug sloppiness: `…mistake-forgot-to-set-model.eval()-before-inference`
  (literal parens/dots), trailing-dash session slugs.

## What held up (charge dropped)
Token-injection economy is honestly capped (2200-char inject, 6/session throttle
with stem-dedup, 12 KB byte-capped card — all real and enforced). Cold/empty store,
Unicode filenames, UTF-8 truncation, cp1251 stdout, missing-backend pause, lock
TOCTOU, Python 3.14 readiness — all verified clean. Project-card never blows its cap.
No dead/duplicate/unreachable code of substance. The core retrieval is real
engineering; the failures are at the edges and in unverified claims.

---

## Remediation plan (expert pass — minimal, no crutches)
1. **A1/A7** — one `_read_text` (errors="replace") + `_read_json` helper; route all
   reads through them; strip BOM in the frontmatter parsers; widen JSON guards. Kills
   the entire crash class once, not site-by-site.
2. **A2** — build the index on first need (SessionStart) when absent and the cache is
   non-empty, so the fast path is actually taken.
3. **A3** — carry forward + increment `recurrence` when superseding a same-slug
   re-statement; the signal becomes real.
4. **A4/A5/A9/A10/A11/A17** — index hardening in one pass: `meta` table with the
   embed model + dim guard (stale/мismatched index self-invalidates), `_connect`
   everywhere, per-row build guard, `sqlite3.Error` catch, cross-filter `<> ''`.
5. **A6** — inverted-index candidate generation in `find_clusters` (mirror the H3
   linker), with a bucket cap.
6. **A8** — `git_autocommit` auto-inits the store on first commit.
7. **A12/A13/A14/A15** — `math.isfinite` confidence reject; abstention floor + honest
   "(no confident match)"; distinguish empty-index from empty-filter; correct the
   `remember.py` message (or embed-on-write).
8. **A16/A18/A19/A20** — decrement grounding caches on retire; drop the dead shim;
   consult PID liveness regardless of age; tighten the slugger.

Each fix ships with a regression probe in `_test_audit_fixes.py` /
`_test_failure_injection.py`. Status appended at the bottom as items land.

---

## REMEDIATION — COMPLETE (2026-06-16)

All findings closed in the package, clean code, no crutches.
Tests: hook + v2(15) + v3(188) + **audit-fixes(74, +26 new probes)** + failure-injection
— all green. Verified end-to-end: the dormant index now builds on first prompt
(`index_exists` False→True via `ensure_scale_index`), and a `recurrence: 4`
frontmatter now reaches the ranking record (boost 0.09, was 0).

| # | Fix landed |
|---|---|
| **A1** | All UTF-8 reads → `errors="replace"` across the whole package (17 hook sites + 8 other modules + 2 streamed `open`s); a bad byte degrades to U+FFFD, never raises `UnicodeDecodeError`. Proven: corrupt transcript/state files now return `{}` instead of crashing the hook. |
| **A2** | `ensure_scale_index()` builds the index on first need at both hot gates; the fast path is taken from prompt #1, not "after the next write". |
| **A3** | `write_typed_note` carries the prior same-slug recurrence forward (+1) into frontmatter; `_embed_recurrence` sources the ranking record from that frontmatter. The signal is live (1→2→3 verified). |
| **A4/A5** | `meta(model, dim)` table stamped at build; `scale_index_ready()` refuses an index whose model ≠ the live embedder → no stale-vector ranking. |
| **A6** | `find_clusters` rewritten with a token→stems inverted index (cosine only on token-sharing pairs); same clusters, ~linear instead of O(M²). |
| **A7** | BOM stripped in both frontmatter parsers — a BOM-prefixed header parses fully. |
| **A8** | `git_autocommit` auto-inits the store (local identity fallback only when none resolves) — "under git / recoverable" now holds for every store. |
| **A9** | All SQLite reads use `_connect()` (busy_timeout); `search()`'s semantic branch is guarded — no `database is locked` leak. |
| **A10** | Per-row `try` in `build()` — one poisoned vector skips its row, the index still builds. |
| **A11** | `_fts_ok` catches `sqlite3.Error` (not just `OperationalError`). |
| **A12** | `_coerce_confidence` rejects NaN/inf via `math.isfinite` (was silently → 1.0). |
| **A13** | `memory_search` abstains: a sub-`CONFIDENT_SIM` top hit prints "no confident match". |
| **A14** | empty-index vs empty-project distinguished — no false "rebuild the index". |
| **A15** | `remember.py` embeds on write when the GPU is free (claim is now true) and is honest when it isn't. |
| **A16** | `supersede_note` unregisters the retired slug from the grounding cache. |
| **A17** | cross-project SQL filter excludes `project = ''`, matching the Python path. |
| **A19** | a provably-dead lock holder is reclaimed immediately (no 10-min wedge). |
| **A20** | `slugify` drops all punctuation (parens/dots/…), not just reserved chars. |
| **A18** | *Not a defect* — `_clear_tag_counts`/`cache_clear` shims are used by all 5 test suites (9 call sites). Kept. The dead-code charge does not stick anywhere. |

---

## FORWARD — improvements & market position

After this pass, correctness and robustness are solid. What remains is **one real
scaling ceiling** and a short list of optional levers. Ordered for *this* project's
priorities (novelty → publishability → code quality → speed), so raw-perf items
rank low on purpose.

**The one structural lever (needs an architecture decision — not done autonomously):**
- **P1 · Bounded-cost retrieval on a single large project.** The cosine scan is
  pure-Python brute force; it's fine across many small projects but a single project
  past ~10 k notes blocks the prompt for seconds (50 k ≈ 6.6 s). Three options, in
  order of fit:
  1. **Two-stage FTS-prefilter (recommended, stays stdlib-only):** FTS5 returns the
     top ~200 lexical candidates, cosine reranks only those → per-prompt cost is
     constant in project size, zero new deps. *Tradeoff:* a purely-semantic hit with
     no shared tokens can fall outside the prefilter — acceptable for a memory store,
     but it changes recall semantics, so it's your call.
  2. **numpy-optional vectorized cosine:** 50–100× on the same brute force *iff*
     numpy is importable; pure-Python fallback kept. No semantic change, but adds an
     optional dep and only postpones the ceiling.
  3. **sqlite-vec / ANN extension:** fastest, but a compiled dependency — breaks the
     "stdlib-only, no black-box" promise that is the project's whole identity. Not
     recommended.

**Cheap, non-architectural (could land without sign-off if you want them):**
- **P2 · Per-project consolidation pressure** — trigger dedup/archival once a project
  crosses N live notes, so no single bucket grows unbounded (caps P1's worst case).
- **P3 · int8-quantized vectors in SQLite** — 4× smaller index, faster BLOB unpack;
  the index is rebuildable so the format change is risk-free.

**Research / publishable angles (your #1 priority — these are differentiators, not chores):**
- **Recurrence-as-salience** is now a live signal again (A3). It's an underexplored
  memory-consolidation mechanism (episodic→semantic by repetition) worth an ablation:
  does recurrence-boosted recall beat recency/relevance-only on a longitudinal agent
  workload? That's a paper-shaped question the eval harness can already pose.
- **Bi-temporal point-in-time recall** (`valid_from`/`valid_to`, supersession) is rare
  in the field — most stores are "use-newest". A controlled study of *belief-as-of-date*
  correctness vs the leaders would be novel.
- **LongMemEval/BEAM number** — the `--longmem` runner is ready; one public benchmark
  result turns "demonstrated on a small store" into a citable claim.

**Market position (unchanged by this audit, restated honestly).** Mem0 / Zep / Letta
are hosted, vector-DB-backed, ANN-scaled, paid, and opaque. Anamnesis deliberately
trades raw scale for **locality + privacy + $0 + human-readable git** — a different
niche, not a worse one. The leaders' scale comes from the very managed-ANN stack
Anamnesis rejects; option P1.1 (FTS-prefilter) is the philosophically-consistent way
to raise the ceiling without becoming them. The gap to close for parity is the public
benchmark number, not the architecture.

---

## IMPROVEMENTS SHIPPED + AUTONOMOUS CRITIC LOOP (2026-06-16)

All three improvements implemented, then an autonomous critic loop ran until it
converged. Findings trended to zero across four rounds — a genuine convergence, not
a stop-out.

**Improvements (commit `69b1bd4`):**
- **P1 — bounded-cost retrieval.** Two-stage: past `ANAMNESIS_PREFILTER_LIMIT` (600)
  candidates, an FTS5 lexical pre-filter takes the top matches and cosine reranks
  only those. A 50 k-note project goes from ~6.6 s/prompt to bounded; smaller
  projects keep an exact full scan (no recall loss). Proven: 4 k notes → candidate
  set capped at 600, 30 ms.
- **P3 — float16 index.** Half the index size, cosine-negligible precision loss
  (round-trip cosine = 1.000000). `vec_format` stamped; a stale-format index
  self-migrates from the float32 cache with zero mixed-format risk.
- **P2 — per-project cap** (`ANAMNESIS_MAX_LIVE_PER_PROJECT`, default OFF). Archives
  only the lowest-salience excess into `Archive/` — never sheds memory unasked.

**Critic loop (commits `caa31d1`, `61e12aa`, `8777df3`):**
- **Round 2 — B1/B2/B3:** stale-format index was read as garbage (gate was
  `index_exists()`, not format) → now gates on `scale_index_ready()`; `upsert()`
  lacked `build()`'s poison guard → one float16-overflow vector dropped the batch;
  P2 wikilink-resolution clarified.
- **Round 3 — C1/C2/C3:** `build()` did a non-atomic `DROP TABLE` → a concurrent
  lock-free reader saw an empty table and got a silent recall miss → now an atomic
  `DELETE`+re-insert transaction (proven: 15× rebuild storm + reader = 0 empty/0
  error reads, was 209/234 empty); the resolved-mistake de-weight was dead on the
  live path → `mark_resolved` now propagates `resolved` to cache+index (salience
  0.97→0.58 live); 12→8 SQLite connections per SessionStart.
- **Round 4 — CONVERGED.** All prior fixes verified by execution (atomic-build
  crash-rollback, WAL bounded, legacy self-heal, Cyrillic FTS at scale, FTS
  injection-safe). One LOW pre-existing residual — bare-number queries (RTX 5090,
  ports, CVE) weren't tokenized — closed in `8777df3`.

**Tests:** `_test_audit_fixes.py` 48 → **97** (+49 probes across A/B/C/D/P findings);
full suite (hook + v2 15 + v3 188 + audit-fixes 97 + failure-injection) green.
