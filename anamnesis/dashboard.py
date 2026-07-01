#!/usr/bin/env python3
"""Anamnesis — a serverless, single-file HTML dashboard for the memory store.

The deliberate non-answer to "where's the web UI?". A hosted dashboard (a `serve`
process, a localhost port, an account) would contradict the whole premise — no server,
no daemon, your data in plain files you own — and would duplicate Obsidian, which already
renders the vault. So this is the opposite: one command writes **one self-contained
`.html` file** (inline CSS, no JS framework, no external asset, no network) that you open
in a browser. It is a snapshot you can mail, commit, or read offline on any machine — the
file IS the UI, exactly as the notes ARE the database.

    python -m anamnesis.dashboard                      # → memory_dashboard.html (+ tries to open it)
    python -m anamnesis.dashboard --project myproj --days 30
    python -m anamnesis.dashboard --out ~/report.html --no-open

Pure frontmatter scan (reuses digest.compute_digest / compute_conflicts) — no embedder,
no LLM, no network. `anamnesis.api.dashboard()` returns the HTML string for embedding.
"""
import html
import json
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import memory_hook as m          # noqa: E402
import digest as _digest         # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Brand palette (matches the v1.1 green branding); a dark theme so a 2000-note store reads
# calmly. All inline — the file must render with zero external requests.
_CSS = """
:root{--bg:#0d1117;--panel:#161b22;--border:#21262d;--fg:#e6edf3;--muted:#8b949e;
--accent:#2ea043;--accent2:#3fb950;--warn:#d29922;--chip:#1f6feb22}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
a{color:var(--accent2);text-decoration:none}
.wrap{max-width:1040px;margin:0 auto;padding:32px 20px 64px}
header{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;margin-bottom:6px}
header h1{margin:0;font-size:22px;font-weight:700}
header h1 .a{color:var(--accent2)}
.sub{color:var(--muted);font-size:13px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:22px 0}
.card{background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:14px 16px}
.card .n{font-size:26px;font-weight:700;color:var(--accent2)}
.card .l{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.04em}
h2{font-size:15px;margin:30px 0 10px;border-bottom:1px solid var(--border);padding-bottom:7px;
color:var(--fg)}
h2 .c{color:var(--muted);font-weight:400;font-size:13px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;color:var(--muted);font-weight:600;padding:6px 8px;border-bottom:1px solid var(--border)}
td{padding:6px 8px;border-bottom:1px solid var(--border);vertical-align:top}
tr:hover td{background:#ffffff06}
.bar{height:7px;border-radius:4px;background:var(--accent);display:inline-block;min-width:2px;vertical-align:middle}
.chip{display:inline-block;background:var(--chip);color:#79c0ff;border-radius:20px;
padding:1px 9px;margin:2px 3px 2px 0;font-size:12px}
.t-mistake{color:#f85149}.t-pattern{color:var(--accent2)}.t-decision{color:#d2a8ff}
.evo{color:var(--warn);font-size:12px}
.muted{color:var(--muted)}
.arrow{color:var(--muted)}
footer{margin-top:40px;color:var(--muted);font-size:12px;text-align:center}
"""


def _e(s) -> str:
    return html.escape(str(s if s is not None else ""))


def _type_class(nt: str) -> str:
    return {"mistake": "t-mistake", "pattern": "t-pattern", "decision": "t-decision"}.get(nt, "")


def build_html(project=None, days=30, conflicts_limit=40) -> str:
    """Render the whole dashboard to one self-contained HTML string."""
    d = _digest.compute_digest(project, days=days, top_entities=20, recent_n=20)
    conflicts = _digest.compute_conflicts(m.slug_project(project) if project else None,
                                          limit=conflicts_limit)
    t = d["totals"]
    scope = d["project"]
    parts = [f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Anamnesis — memory dashboard ({_e(scope)})</title><style>{_CSS}</style></head>
<body><div class="wrap">
<header><h1><span class="a">Anamnesis</span> memory dashboard</h1>
<span class="sub">{_e(scope)} · generated {_e(d['generated'])} · last {days} days</span></header>"""]

    # ── stat cards ──
    parts.append('<div class="cards">')
    for n, lbl in ((t["live_notes"], "live notes"), (t["projects"], "projects"),
                   (t["superseded_notes"], "superseded"),
                   (t["added_in_window"], f"added · {days}d"),
                   (t["revised_in_window"], f"revised · {days}d")):
        parts.append(f'<div class="card"><div class="n">{n}</div><div class="l">{_e(lbl)}</div></div>')
    parts.append("</div>")

    # ── per-project table (bar = share of the largest) ──
    bp = d["by_project"]
    if bp:
        mx = max((v["total"] for v in bp.values()), default=1) or 1
        parts.append(f'<h2>By project <span class="c">— {len(bp)}</span></h2>'
                     '<table><tr><th>project</th><th>notes</th><th></th>'
                     '<th>+added</th><th>~revised</th><th>types</th></tr>')
        for p, v in sorted(bp.items(), key=lambda kv: -kv[1]["total"]):
            w = int(240 * v["total"] / mx)
            kinds = " ".join(f'<span class="{_type_class(k)}">{_e(k)}:{c}</span>'
                             for k, c in sorted(v["by_type"].items()))
            parts.append(f'<tr><td>{_e(p)}</td><td>{v["total"]}</td>'
                         f'<td><span class="bar" style="width:{w}px"></span></td>'
                         f'<td class="muted">+{v["added"]}</td><td class="muted">{v["superseded"]}</td>'
                         f'<td>{kinds}</td></tr>')
        parts.append("</table>")

    # ── top entities ──
    if d["top_entities"]:
        parts.append('<h2>Most-connected entities</h2><div>')
        for e in d["top_entities"]:
            parts.append(f'<span class="chip">{_e(e["entity"])} · {e["notes"]}</span>')
        parts.append("</div>")

    # ── recently added ──
    if d["recent"]:
        parts.append(f'<h2>Recently added <span class="c">— {len(d["recent"])}</span></h2>'
                     '<table><tr><th>date</th><th>project</th><th>type</th><th>title</th></tr>')
        for n in d["recent"]:
            parts.append(f'<tr><td class="muted">{_e(n["date"])}</td><td>{_e(n["project"])}</td>'
                         f'<td class="{_type_class(n["ntype"])}">{_e(n["ntype"])}</td>'
                         f'<td>{_e(n["title"])}</td></tr>')
        parts.append("</table>")

    # ── conflicts / supersession ledger ──
    parts.append(f'<h2>Contradiction ledger <span class="c">— {len(conflicts)} revised, '
                 f'write-time supersession</span></h2>')
    if conflicts:
        parts.append('<table><tr><th>date</th><th>project</th><th>was → now</th><th></th></tr>')
        for c in conflicts:
            evo = '<span class="evo">still evolving</span>' if not c["resolved"] else ""
            nowt = _e(c["new_title"]) if c["new_stem"] else '<span class="muted">(archived)</span>'
            parts.append(f'<tr><td class="muted">{_e(c["new_date"] or c["old_date"])}</td>'
                         f'<td>{_e(c["project"])}</td>'
                         f'<td>{_e(c["old_title"])} <span class="arrow">→</span> {nowt}</td>'
                         f'<td>{evo}</td></tr>')
        parts.append("</table>")
    else:
        parts.append('<p class="muted">Nothing superseded yet — no contradictions on record.</p>')

    parts.append('<footer>Generated by Anamnesis · plain files, no server · '
                 '<a href="https://github.com/DonPlaton/anamnesis">github.com/DonPlaton/anamnesis</a>'
                 '</footer></div></body></html>')
    return "\n".join(parts)


def main():
    argv = sys.argv[1:]
    project = next((a.split("=", 1)[1] for a in argv if a.startswith("--project=")), None)
    days = int(next((a.split("=", 1)[1] for a in argv if a.startswith("--days=")), "30"))
    out = next((a.split("=", 1)[1] for a in argv if a.startswith("--out=")), "memory_dashboard.html")
    no_open = "--no-open" in argv
    htmls = build_html(project, days=days)
    p = Path(out).expanduser().resolve()
    p.write_text(htmls, encoding="utf-8")
    print(f"[dashboard] wrote {p}  ({len(htmls)//1024} KB, self-contained, no server)")
    if not no_open:
        try:
            webbrowser.open(p.as_uri())
        except Exception:
            pass


if __name__ == "__main__":
    main()
