#!/usr/bin/env python3
"""Cross-machine / multi-agent sync for the memory store (M-11).

The store is a git repo, so syncing it across your machines (or merging memories
written by parallel agents) is just git. This wraps the safe sequence:

    git add -A && commit (if dirty) → pull --rebase --autostash → push

Markdown notes rarely conflict (one file per fact); when they do, git surfaces it
like any other repo. Derived & machine-local files (Index.md, graph.json, the
embedding cache, the SQLite index, User/profile.md, the processed-sessions DB) are
gitignored, so sync merges ONLY real memory and never thrashes on regenerated
files (audit H4). Run on each machine, or from a scheduled task.

    python sync.py            # commit local changes, rebase on remote, push
    python sync.py --no-push  # pull/rebase only (e.g. read-only mirror)

Requires a configured `origin` remote on the store. No-op (clean exit) if the
store isn't a git repo or has no remote.
"""
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from . import memory_hook as m
except ImportError:
    import memory_hook as m


def _git(*args, check=False):
    return subprocess.run(["git", "-C", str(m.VAULT), *args],
                          capture_output=True, text=True, check=check)


def main() -> int:
    if not (m.VAULT / ".git").exists():
        print(f"[sync] {m.VAULT} is not a git repo — nothing to sync.", file=sys.stderr)
        return 0
    if not (_git("remote").stdout or "").strip():
        print("[sync] no git remote configured (add one: git remote add origin <url>).",
              file=sys.stderr)
        return 0

    # 1) commit local changes (if any)
    if (_git("status", "--porcelain").stdout or "").strip():
        _git("add", "-A")
        msg = f"sync: memory snapshot {datetime.now():%Y-%m-%d %H:%M}"
        _git("commit", "-m", msg)
        print(f"[sync] committed local changes: {msg}")

    # 2) rebase on remote (autostash keeps any leftover state out of the way)
    pull = _git("pull", "--rebase", "--autostash")
    if pull.returncode != 0:
        print("[sync] pull --rebase failed (conflict?). Resolve manually:\n"
              + (pull.stderr or pull.stdout), file=sys.stderr)
        return 1
    print("[sync] rebased on origin")

    # 3) push
    if "--no-push" not in sys.argv:
        push = _git("push")
        if push.returncode != 0:
            print("[sync] push failed:\n" + (push.stderr or push.stdout), file=sys.stderr)
            return 1
        print("[sync] pushed to origin")
    print("[sync] done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
