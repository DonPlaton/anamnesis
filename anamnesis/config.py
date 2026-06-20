"""Central configuration for Anamnesis — de-personalized and cross-platform.

Every path and tunable resolves from an environment variable with a sensible
default, so the same code runs unchanged on any machine. `ANAMNESIS_*` overrides
its default; the legacy `CLAUDE_MEMORY_*` names are still read for back-compat,
so an existing install keeps working after the rename.

The memory store is plain markdown + JSON under git. Obsidian can open it for a
graph/backlinks GUI, but nothing here requires Obsidian — it is fully optional.
"""
import os
from pathlib import Path


def env(name: str, default: str | None = None) -> str | None:
    """Read ANAMNESIS_<name>, then legacy CLAUDE_MEMORY_<name>, then default."""
    return os.environ.get(f"ANAMNESIS_{name}",
                          os.environ.get(f"CLAUDE_MEMORY_{name}", default))


def _expand(p: str) -> Path:
    return Path(os.path.expanduser(os.path.expandvars(p)))


# ── Core paths (cross-platform defaults under the user's home) ────────
# The memory store. Default: ~/.anamnesis. Override with ANAMNESIS_HOME (or the
# legacy ANAMNESIS_VAULT / CLAUDE_MEMORY_VAULT).
VAULT = _expand(env("VAULT") or os.environ.get("ANAMNESIS_HOME")
                or str(Path.home() / ".anamnesis"))

# Where the host agent keeps session transcripts, for the catch-up sweep. Claude
# Code uses ~/.claude/projects. Other agents push via ingest.py / the MCP server
# and don't need this at all.
PROJECTS_ROOT = _expand(os.environ.get("ANAMNESIS_PROJECTS_ROOT")
                        or os.environ.get("CLAUDE_PROJECTS_ROOT")
                        or str(Path.home() / ".claude" / "projects"))


def load_dotenv() -> None:
    """Load KEY=VALUE pairs from a .env so cloud API keys stay out of git/code.
    Searched (FIXED, trusted locations only): $ANAMNESIS_ENV_FILE, then .env /
    .secrets.env next to the package and at the repo root (where .env.example says to
    put it). Never overrides an already-set var.

    Deliberately NOT the current working directory: the hook and the --dir sweep often
    run with cwd inside an untrusted repo, where a planted `./.env` could inject an
    attacker's API key / relay endpoint and observe what gets sent (audit 2026-06-18).
    Point ANAMNESIS_ENV_FILE at a custom location if you need one elsewhere."""
    here = Path(__file__).resolve().parent
    candidates = []
    custom = os.environ.get("ANAMNESIS_ENV_FILE")
    if custom:
        candidates.append(Path(custom))
    candidates += [here / ".env", here / ".secrets.env",
                   here.parent / ".env", here.parent / ".secrets.env"]
    for fp in candidates:
        try:
            if not fp.is_file():
                continue
            for ln in fp.read_text(encoding="utf-8", errors="replace").splitlines():
                ln = ln.strip()
                if ln and not ln.startswith("#") and "=" in ln:
                    k, v = ln.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        except OSError:
            pass
