#!/usr/bin/env python3
"""Conflict-aware merge for the memory vault — concurrent-agent / multi-machine sync (M-11+).

`sync.py` makes cross-machine sync "just git". This closes the one rough edge: when two machines
(or two parallel agents) touch the *same* note before syncing, git raises a merge conflict. But
Anamnesis notes are structured, and the usual collision is **not** a real disagreement — it is two
sides independently bumping a recurrence counter or one side retiring the note via supersession
while the body stays identical. A generic text merge turns that into a manual conflict; this merge
driver resolves it the way the data model already says it should:

  * identical body, only frontmatter diverged → merge field-wise:
      - recurrence  → max (both saw it recur; keep the higher count)
      - status/superseded_by/resolved_by → a *retirement wins* (superseded > resolved > live)
      - tags        → union
      - everything else identical → kept; a genuine scalar disagreement falls through
  * bodies genuinely differ → exit non-zero, leaving git's conflict markers for a human.

No other file-based agent memory does structured auto-merge; this is what makes "your memory is a
git repo you sync across machines" actually painless. Registered as a git merge driver on the
store (see `register`), invoked by git as: driver %O %A %B (base, ours, theirs); result → %A.

    python -m anamnesis.merge --register        # install the driver on the store (idempotent)
    python -m anamnesis.merge <base> <ours> <theirs>   # git calls this; writes merged → <ours>
"""
import subprocess
import sys
from pathlib import Path

_STATUS_RANK = {"": 0, "current": 0, "resolved": 1, "superseded": 2}


def _split(text: str):
    """(frontmatter_dict, body) for a note. Frontmatter is the YAML block between the first two
    `---` fences; everything after is the body. Values are kept as raw strings; a `tags` line is
    parsed into a list. Missing frontmatter → ({}, whole text)."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    fm_block = text[3:end].strip("\n")
    body = text[end + 4:].lstrip("\n")
    fm = {}
    for line in fm_block.splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        fm[k.strip()] = v.strip()
    return fm, body


def _tags(v: str):
    return [t.strip().strip('"').strip("'") for t in v.strip("[]").split(",") if t.strip()]


def _merge_front(base: dict, ours: dict, theirs: dict):
    """Field-wise merge of three frontmatter dicts. Returns (merged_dict, ok): ok is False if a
    non-mergeable scalar genuinely disagrees between the two sides (then the caller bails to git)."""
    keys = set(base) | set(ours) | set(theirs)
    merged, ok = {}, True
    for k in keys:
        o, t = ours.get(k), theirs.get(k)
        if o == t:
            if o is not None:
                merged[k] = o
            continue
        if k == "recurrence":
            def _n(x):
                try:
                    return int((x or "1").strip())
                except ValueError:
                    return 1
            merged[k] = str(max(_n(o), _n(t)))
        elif k == "status":
            merged[k] = o if _STATUS_RANK.get(o, 0) >= _STATUS_RANK.get(t, 0) else t
        elif k in ("superseded_by", "resolved_by"):
            merged[k] = (o or t) if not (o and t) else (o if o >= t else t)   # a retirement wins; tie→later stem
        elif k == "tags":
            merged[k] = '[' + ', '.join(f'"{x}"' for x in dict.fromkeys(_tags(o or "") + _tags(t or ""))) + ']'
        elif o is None or t is None:
            merged[k] = o if o is not None else t              # one side added a field → keep it
        else:
            ok = False                                         # a real scalar disagreement
            merged[k] = o
    return merged, ok


# Frontmatter key order for a stable, diff-friendly re-emit (unknown keys appended, sorted).
_ORDER = ["date", "project", "tags", "type", "status", "recurrence",
          "supersedes", "superseded_by", "resolved_by"]


def _emit(fm: dict, body: str) -> str:
    keys = [k for k in _ORDER if k in fm] + sorted(k for k in fm if k not in _ORDER)
    lines = "\n".join(f"{k}: {fm[k]}" for k in keys)
    return f"---\n{lines}\n---\n\n{body.rstrip()}\n"


def merge_note(base: str, ours: str, theirs: str):
    """Merge three versions of a note. Returns merged text, or None if the bodies genuinely
    differ / a scalar disagrees (let git surface the conflict). Auto-resolves the structured
    frontmatter collisions (recurrence bump, supersession, tag union) that are the common case."""
    fb, bb = _split(base)
    fo, bo = _split(ours)
    ft, bt = _split(theirs)
    if bo.strip() != bt.strip():
        return None                                            # real content divergence → git
    merged_fm, ok = _merge_front(fb, fo, ft)
    if not ok:
        return None
    return _emit(merged_fm, bo)


def _driver(base_path, ours_path, theirs_path) -> int:
    """git merge-driver entry: read the three files, write the merge to `ours_path` (%A). Exit 0
    if resolved, 1 to signal an unresolved conflict (git then writes conflict markers)."""
    def _read(p):
        try:
            return Path(p).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
    merged = merge_note(_read(base_path), _read(ours_path), _read(theirs_path))
    if merged is None:
        return 1
    Path(ours_path).write_text(merged, encoding="utf-8")
    return 0


def register(vault: Path) -> bool:
    """Install the merge driver on the store: a `merge.anamnesis.driver` in .git/config and a
    `*.md merge=anamnesis` rule in the store's .gitattributes. Idempotent; no-op off a git repo."""
    vault = Path(vault)
    if not (vault / ".git").exists():
        return False
    py = sys.executable.replace("\\", "/")
    driver = f'"{py}" -m anamnesis.merge %O %A %B'
    subprocess.run(["git", "-C", str(vault), "config", "merge.anamnesis.name",
                    "Anamnesis structured note merge"], capture_output=True)
    subprocess.run(["git", "-C", str(vault), "config", "merge.anamnesis.driver", driver],
                   capture_output=True)
    ga = vault / ".gitattributes"
    rule = "*.md merge=anamnesis"
    existing = ga.read_text(encoding="utf-8") if ga.exists() else ""
    if rule not in existing:
        ga.write_text((existing.rstrip() + "\n" if existing.strip() else "")
                      + "# Anamnesis: structured auto-merge for note frontmatter (recurrence, "
                      + "supersession, tags)\n" + rule + "\n", encoding="utf-8")
    return True


def main() -> int:
    args = sys.argv[1:]
    if "--register" in args:
        try:
            from . import memory_hook as m
        except ImportError:
            import memory_hook as m
        ok = register(m.VAULT)
        print(f"[merge] driver {'registered on ' + str(m.VAULT) if ok else 'skipped (not a git repo)'}")
        return 0
    if len(args) >= 3:
        return _driver(args[0], args[1], args[2])
    print("usage: python -m anamnesis.merge --register | <base> <ours> <theirs>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
