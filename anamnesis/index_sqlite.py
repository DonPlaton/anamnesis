#!/usr/bin/env python3
"""SQLite scale-index for the retrieval hot path (P-7, audit C2/C3).

The markdown files remain the single source of truth and the JSON embedding
cache remains the rebuild source; this is a *derived, rebuildable* accelerator.
The round-1 version was a dead standalone CLI nothing called (audit C3), while
the live `retrieve_relevant` parsed the whole 63 MB JSON cache on EVERY prompt
(audit C2). Now the hook keeps this index current (incremental upsert on write,
delete on supersede/archive) and the retrieval paths read candidates straight
from it — project-filtered IN SQL, so only the relevant subset's vectors are
unpacked instead of re-parsing the entire cache per prompt.

FTS5 lexical + packed float32 vector BLOBs, zero dependencies (stdlib `sqlite3`
+ `array`). Never replaces the markdown; delete the `.sqlite` file and nothing
is lost — the next write rebuilds it from the cache.

    python index_sqlite.py build                 # (re)build from the cache
    python index_sqlite.py "cuda oom" myproject  # query it
"""
import math
import os
import sqlite3
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from . import memory_hook as m
except ImportError:
    import memory_hook as m

SIM_FLOOR = m.RETRIEVAL_NEAR_FLOOR   # shared nearest-neighbour floor, not a private 0.15 (audit)
# columns selected for ranking candidates — kept in one place so the SQL and the
# row→record mapping never drift apart
_CAND_COLS = ("stem", "project", "ntype", "title", "descr", "prevention",
              "recurrence", "resolved", "confidence", "vec")


def db_path() -> Path:
    return m.VAULT / ".index.sqlite"


# Default pack: struct half-float (float16) — half the index size of float32 with
# cosine-negligible precision loss (improvement P3). The `array` module has no
# float16, so vectors are packed via `struct`.
#
# Opt-in 1-bit quantization (improvement A2, launch round): ANAMNESIS_EMBED_QUANT=binary
# packs sign-bit codes — 16x smaller than float16, 32x smaller than the float32 cache.
# The ranker cosines the float query against the unpacked {-1,+1} doc, so a binary
# candidate scores as ASYMMETRIC binary cosine, measured ~lossless on LongMemEval
# (R@5 0.802 → 0.796, R@1 0.550 → 0.548; research/QUANTIZATION.md). Default OFF; the
# JSON cache stays float32 (the rebuild source), so flipping the env just rebuilds the
# index in the new format — vec_format below stamps it, and a mismatch self-migrates.
_BINARY = os.environ.get("ANAMNESIS_EMBED_QUANT", "").strip().lower() in ("binary", "bin", "1bit")
VEC_FORMAT = "b1" if _BINARY else "e"   # "e"=float16 (default); "b1"=sign-bit binary
_VEC_SIZE = 0 if _BINARY else struct.calcsize(VEC_FORMAT)


def _pack(vec) -> bytes:
    if _BINARY:
        d = len(vec)
        bits = bytearray((d + 7) // 8)
        for i, x in enumerate(vec):
            if x >= 0.0:                          # 1-bit sign code (1 = non-negative)
                bits[i >> 3] |= 1 << (i & 7)
        return struct.pack("<H", d) + bytes(bits)   # 2-byte dim header → self-describing unpack
    return struct.pack(f"<{len(vec)}{VEC_FORMAT}", *vec)


def _unpack(b: bytes) -> list:
    if _BINARY:
        if len(b) < 2:
            return []
        (d,) = struct.unpack_from("<H", b, 0)
        bits = b[2:]
        if len(bits) < (d + 7) // 8:        # truncated/corrupt code → no signal, never IndexError
            return []
        return [1.0 if (bits[i >> 3] >> (i & 7)) & 1 else -1.0 for i in range(d)]
    if not b or _VEC_SIZE == 0:             # empty blob (text-only) or mis-set size → no vector
        return []
    try:
        return list(struct.unpack(f"<{len(b) // _VEC_SIZE}{VEC_FORMAT}", b))
    except struct.error:                    # stale-format / truncated blob → no signal, never raise
        return []


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(db_path())
    # WAL lets lock-free retrieval read while the hook upserts under the vault
    # lock; busy_timeout absorbs the brief overlap instead of erroring.
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA busy_timeout=2000")
    except sqlite3.Error:
        pass
    return con


def _fts_ok(con: sqlite3.Connection) -> bool:
    try:
        con.execute("CREATE VIRTUAL TABLE _fts_probe USING fts5(x)")
        con.execute("DROP TABLE _fts_probe")
        return True
    except sqlite3.Error:        # any FTS-less build, not just OperationalError (audit A11)
        return False


def _has_fts(con: sqlite3.Connection) -> bool:
    try:
        con.execute("SELECT 1 FROM notes_fts LIMIT 1")
        return True
    except sqlite3.OperationalError:
        return False


def _conf(r: dict):
    c = m._coerce_confidence(r.get("confidence")) if hasattr(m, "_coerce_confidence") \
        else (r.get("confidence") if isinstance(r.get("confidence"), (int, float)) else None)
    return c


def _row(stem: str, r: dict) -> tuple:
    """A note record → a `notes` table row (column order = the CREATE below)."""
    vec = r.get("vec") or []
    return (stem, r.get("project"), r.get("ntype"), r.get("title"),
            r.get("desc", ""), r.get("prevention", ""),
            int(r.get("recurrence", 1) or 1),
            1 if r.get("resolved") else 0, _conf(r),
            len(vec), _pack(vec))


def _fts_text(r: dict, stem: str) -> str:
    return f"{r.get('title','')} {r.get('desc','')} {r.get('prevention','')} {stem}"


def _create_schema(con: sqlite3.Connection) -> bool:
    cur = con.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS notes(
        stem TEXT PRIMARY KEY, project TEXT, ntype TEXT, title TEXT,
        descr TEXT, prevention TEXT, recurrence INTEGER, resolved INTEGER,
        confidence REAL, dim INTEGER, vec BLOB)""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_notes_project ON notes(project)")
    cur.execute("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT)")
    fts = _fts_ok(con)
    if fts:
        cur.execute("CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(stem, text)")
    return fts


def index_exists() -> bool:
    """True if a usable index file with the `notes` table is present."""
    if not db_path().exists():
        return False
    try:
        con = _connect()
        try:
            con.execute("SELECT 1 FROM notes LIMIT 1")
            return True
        finally:
            con.close()
    except sqlite3.Error:
        return False


def index_meta() -> dict:
    """The embed model + vector dim the index was built with (audit A5). Empty
    for no index or a legacy/unstamped one — the caller treats that as 'current'
    so an upgrade doesn't force an immediate rebuild."""
    if not db_path().exists():
        return {}
    try:
        con = _connect()
        try:
            return {k: v for k, v in con.execute("SELECT key, value FROM meta")}
        except sqlite3.Error:
            return {}
        finally:
            con.close()
    except sqlite3.Error:
        return {}


def build(verbose: bool = False) -> int:
    """(Re)build the index from the embedding cache. Returns the note count.
    Stamps the embed model + vector dim into `meta` so retrieval can refuse a
    stale-model index instead of silently ranking against incompatible vectors
    (audit A5); a single garbage vector skips its row instead of aborting the
    whole build and leaving the accelerator permanently unbuilt (audit A10).
    Atomic: the content swap is one transaction (DELETE + re-insert, NOT DROP
    TABLE), so a concurrent lock-free reader — retrieval takes no vault lock —
    keeps the OLD complete index until COMMIT and never sees an empty/partial
    table mid-rebuild (which silently returned zero hits). A crash mid-build rolls
    back, leaving the previous index intact (critic round 3)."""
    cache = m.load_embed_cache()
    con = _connect()
    con.isolation_level = None       # manual transaction control for the atomic swap
    try:
        cur = con.cursor()
        fts = _create_schema(con)    # CREATE IF NOT EXISTS (autocommitted; tables persist)
        cur.execute("BEGIN IMMEDIATE")
        cur.execute("DELETE FROM notes")
        if fts:
            cur.execute("DELETE FROM notes_fts")
        cur.execute("DELETE FROM meta")
        n = dim = 0
        for stem, r in cache.items():
            if not isinstance(r, dict):
                continue
            v = r.get("vec")
            if v is not None and not isinstance(v, list):
                continue        # malformed vec field — drop the row
            try:
                # vec=None → empty blob / dim 0: a text-only entry, FTS-indexed for
                # lexical recall but skipped by the semantic scan (no-embedder, #32)
                row = _row(stem, r)
            except (TypeError, ValueError, OverflowError, struct.error):
                continue        # poisoned vector (bad type / out of range) — drop the row
            cur.execute(f"INSERT OR REPLACE INTO notes VALUES ({','.join('?' * 11)})", row)
            if fts:
                cur.execute("INSERT INTO notes_fts (stem, text) VALUES (?, ?)",
                            (stem, _fts_text(r, stem)))
            dim = dim or row[9]
            n += 1
        model = (m.load_embed_meta() or {}).get("model") or m.embed_signature()
        cur.execute("INSERT OR REPLACE INTO meta VALUES ('model', ?)", (str(model),))
        cur.execute("INSERT OR REPLACE INTO meta VALUES ('dim', ?)", (str(dim),))
        cur.execute("INSERT OR REPLACE INTO meta VALUES ('vec_format', ?)", (VEC_FORMAT,))
        cur.execute("COMMIT")
        if verbose:
            print(f"[index] built {db_path().name}: {n} notes (fts={fts}, model={model})",
                  file=sys.stderr)
        return n
    finally:
        con.close()


def upsert(records: dict) -> int:
    """Insert/replace `records` (stem -> cache record) into an existing index —
    the incremental write path the hook calls after embedding new notes."""
    if not records:
        return 0
    con = _connect()
    try:
        cur = con.cursor()
        fts = _has_fts(con)
        n = 0
        for stem, r in records.items():
            if not isinstance(r, dict):
                continue
            v = r.get("vec")
            if v is not None and not isinstance(v, list):
                continue
            try:
                row = _row(stem, r)   # vec=None → text-only FTS row (no-embedder, #32)
            except (TypeError, ValueError, OverflowError, struct.error):
                continue        # poisoned/out-of-range vector — skip the row, not the
                                # whole batch (mirror build()'s A10 guard; P3 struct.pack
                                # raises OverflowError where the old array('f') never did)
            cur.execute(f"INSERT OR REPLACE INTO notes VALUES ({','.join('?' * 11)})", row)
            if fts:
                cur.execute("DELETE FROM notes_fts WHERE stem = ?", (stem,))
                cur.execute("INSERT INTO notes_fts (stem, text) VALUES (?, ?)",
                            (stem, _fts_text(r, stem)))
            n += 1
        con.commit()
        return n
    finally:
        con.close()


def delete(stems) -> int:
    """Drop notes from the index (supersede / archive / forget keep it in sync)."""
    if not stems:
        return 0
    con = _connect()
    try:
        cur = con.cursor()
        fts = _has_fts(con)
        n = 0
        for stem in stems:
            cur.execute("DELETE FROM notes WHERE stem = ?", (stem,))
            n += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
            if fts:
                cur.execute("DELETE FROM notes_fts WHERE stem = ?", (stem,))
        con.commit()
        return n
    finally:
        con.close()


def _where(cross: bool, alias: str = "") -> str:
    """The project filter, optionally table-qualified (for the FTS JOIN)."""
    p = f"{alias}." if alias else ""
    return (f"{p}project IS NOT NULL AND {p}project <> '' AND {p}project <> ?" if cross
            else f"{p}project = ?")


def _rows_to_cands(rows) -> list:
    """Rows in `_CAND_COLS` order → [(stem, record)] shaped like embed-cache entries
    so the retrieval ranker is identical to the JSON path."""
    out = []
    for (stem, proj, nt, title, descr, prev, rec, resolved, conf, vec) in rows:
        r = {"vec": _unpack(vec), "ntype": nt, "project": proj, "title": title,
             "desc": descr or "", "prevention": prev or "",
             "recurrence": rec or 1, "resolved": bool(resolved)}
        if conf is not None:
            r["confidence"] = conf
        out.append((stem, r))
    return out


def candidate_count(project: str, cross: bool = False) -> int:
    """How many candidates the project filter selects — lets the caller decide
    whether to FTS-prefilter (improvement P1) without unpacking a single vector."""
    con = _connect()
    try:
        return con.execute(f"SELECT COUNT(*) FROM notes WHERE {_where(cross)}",
                           (project,)).fetchone()[0]
    except sqlite3.Error:
        return 0
    finally:
        con.close()


def iter_candidates(project: str, cross: bool = False,
                    query: str | None = None, limit: int | None = None) -> list:
    """[(stem, rec)] candidate notes for ranking, rec shaped exactly like an
    embed-cache record so the retrieval code is identical to the JSON path.
    Project filtering happens IN SQL (audit C2). When `query`+`limit` are given and
    FTS5 is present, only the top-`limit` lexical (bm25) matches are unpacked as
    cosine candidates (improvement P1), so per-prompt cost is bounded by `limit`
    instead of the project's full size. Recall tradeoff: a purely-semantic hit with
    no shared query token is excluded — the caller only enables this once a project
    is large enough that a full scan would stall the prompt. Without FTS, `limit` is
    ignored and a full (correct, slower) scan runs."""
    cols = ", ".join(_CAND_COLS)
    con = _connect()      # busy_timeout: ride out a concurrent write, don't error (audit A9)
    try:
        has_fts = bool(query and limit) and _has_fts(con)
        if has_fts:
            colsn = ", ".join("n." + c for c in _CAND_COLS)
            terms = " OR ".join(_safe_terms(query)) or '""'
            sql = (f"SELECT {colsn} FROM notes_fts JOIN notes n ON n.stem = notes_fts.stem "
                   f"WHERE notes_fts MATCH ? AND {_where(cross, 'n')} "
                   f"ORDER BY bm25(notes_fts) LIMIT ?")
            try:
                rows = con.execute(sql, (terms, project, limit)).fetchall()
            except sqlite3.Error:
                rows = []
            if rows:
                return _rows_to_cands(rows)
            # query had no lexical match → bounded, deterministic fallback (most
            # recurring first) instead of an arbitrary cap or a full scan
            rows = con.execute(
                f"SELECT {cols} FROM notes WHERE {_where(cross)} "
                "ORDER BY recurrence DESC LIMIT ?", (project, limit)).fetchall()
            return _rows_to_cands(rows)
        rows = con.execute(f"SELECT {cols} FROM notes WHERE {_where(cross)}",
                           (project,)).fetchall()
    finally:
        con.close()
    return _rows_to_cands(rows)


def _hit(row, score):
    return {"score": round(score, 3), "stem": row[0], "project": row[1],
            "ntype": row[2], "title": row[3], "description": row[4],
            "prevention": row[5]}


def search(query: str, project: str | None = None, k: int = 10):
    """Semantic (cosine over project-filtered BLOBs) with an FTS5 lexical
    fallback when the embedder is unavailable. Mirrors memory_search.search_core,
    backed by SQLite. Returns (results, mode). The CLI/diagnostic entry point;
    the hook's hot path uses iter_candidates() + the shared ranker instead."""
    if not index_exists():
        return [], "no-index"
    # Self-migrate a stale-format index before _unpack reads it (CLI path) — but only
    # when the cache can repopulate it; never rebuild to empty and throw away working
    # lexical (FTS) data. If we can't migrate, skip the (garbage) semantic branch and
    # let the format-independent FTS lexical fallback answer (critic round 3).
    stale = (index_meta() or {}).get("vec_format") != VEC_FORMAT
    if stale and m.load_embed_cache():
        build()
        stale = False
    qvec = (m.embed_text(query, kind=m.query_embed_kind())
            if (not stale and m.embed_cache_usable() and m.embedder_available(2)) else None)
    con = _connect()      # busy_timeout, and the semantic branch is guarded (audit A9)
    try:
        if qvec:
            try:
                sql = ("SELECT stem, project, ntype, title, descr, prevention, "
                       "recurrence, confidence, vec FROM notes")
                params = ()
                if project:
                    sql += " WHERE project = ?"
                    params = (project,)
                sims = [(m.cosine(qvec, _unpack(r[8])), r) for r in con.execute(sql, params)]
                amb = m._ambiguity(sorted((s for s, _ in sims), reverse=True))  # adaptive recurrence
                scored = []
                for sim, row in sims:
                    if sim > SIM_FLOOR:
                        boost = 0.0003 * math.log(max(1, int(row[6] or 1))) * amb  # log prior × ambiguity
                        conf = row[7]
                        mult = 1.0 if conf is None else (0.6 + 0.4 * max(0.0, min(1.0, conf)))
                        scored.append(((sim + boost) * mult, row))
                scored.sort(key=lambda x: -x[0])
                return [_hit(r, s) for s, r in scored[:k]], "semantic"
            except sqlite3.Error:
                return [], "semantic-unavailable"
        # lexical fallback via FTS5
        try:
            terms = " OR ".join(t for t in _safe_terms(query)) or '""'
            sql = ("SELECT n.stem, n.project, n.ntype, n.title, n.descr, n.prevention, "
                   "n.recurrence, bm25(notes_fts) FROM notes_fts "
                   "JOIN notes n ON n.stem = notes_fts.stem "
                   "WHERE notes_fts MATCH ?")
            params = [terms]
            if project:
                sql += " AND n.project = ?"
                params.append(project)
            sql += " ORDER BY bm25(notes_fts) LIMIT ?"
            params.append(k)
            rows = con.execute(sql, params).fetchall()
            return [_hit(r, -float(r[7])) for r in rows], "lexical(fts)"
        except sqlite3.Error:        # any FTS error (incl. an edge build choking on '""'), not just Operational
            return [], "lexical-unavailable"
    finally:
        con.close()


def _safe_terms(query: str):
    """Alphanumeric tokens for an FTS5 MATCH (avoids syntax errors on punctuation)."""
    return list(m._tokens(query))[:24]      # m._tokens is always defined (dropped dead fallback, audit)


def main() -> int:
    args = sys.argv[1:]
    if args and args[0] == "build":
        build(verbose=True)
        return 0
    if not args:
        print('usage: index_sqlite.py build | index_sqlite.py "<query>" [project]',
              file=sys.stderr)
        return 1
    query = args[0]
    project = args[1] if len(args) > 1 else None
    results, mode = search(query, project)
    if mode == "no-index":
        print("[index] no .index.sqlite — run: python index_sqlite.py build", file=sys.stderr)
        return 1
    print(f"{len(results)} hit(s) for {query!r} ({mode}):")
    for r in results:
        print(f"  {r['score']:6.3f} [{r['project']}/{r['ntype']}] {r['title']}  ({r['stem']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
