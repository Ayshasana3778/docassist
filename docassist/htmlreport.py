"""Render a docassist analysis as a single self-contained HTML page (no external assets)."""

from __future__ import annotations

import html
import re
from datetime import datetime

_CSS = """
:root{--bg:#f6f7fb;--card:#fff;--ink:#1b1f2a;--muted:#5d6577;--line:#e3e6ef;--brand:#4f46e5;
--add-bg:#e6f6ec;--add-ink:#14532d;--del-bg:#fde8e8;--del-ink:#7f1d1d;--hunk:#eef0ff;--code:#f0f2f8;
--b-renamed:#2563eb;--b-removed:#dc2626;--b-modified:#d97706;--b-added:#059669}
@media(prefers-color-scheme:dark){:root{--bg:#0f1220;--card:#181c2e;--ink:#e8eaf3;--muted:#98a0b6;--line:#2a3050;
--brand:#8b85ff;--add-bg:#12301f;--add-ink:#9be7b4;--del-bg:#3a1618;--del-ink:#ffb4b4;--hunk:#1d2240;--code:#232842}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:980px;margin:0 auto;padding:32px 16px 64px}
header{margin-bottom:24px}
.eyebrow{font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:var(--brand);font-weight:700}
h1{margin:4px 0 6px;font-size:30px;line-height:1.2}
.sub{color:var(--muted);margin:0}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin:24px 0}
.stat{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px}
.stat b{display:block;font-size:32px;line-height:1.1}
.stat span{color:var(--muted);font-size:14px}
h2{font-size:19px;margin:32px 0 12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px;margin-bottom:16px}
.where{font-weight:650;word-break:break-word}
.where small{color:var(--muted);font-weight:500}
.badges{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0}
.badge{font-size:13px;font-weight:600;color:#fff;border-radius:999px;padding:2px 10px}
.renamed{background:var(--b-renamed)}.removed{background:var(--b-removed)}
.modified{background:var(--b-modified)}.added{background:var(--b-added)}
.why{margin:6px 0 12px;color:var(--muted)}
code{background:var(--code);border-radius:5px;padding:1px 6px;font:14px ui-monospace,Consolas,monospace}
pre{margin:0;overflow-x:auto;border:1px solid var(--line);border-radius:10px;
font:13px/1.5 ui-monospace,Consolas,monospace;background:var(--card)}
pre div{padding:0 12px;white-space:pre-wrap;word-break:break-word}
.a{background:var(--add-bg);color:var(--add-ink)}.d{background:var(--del-bg);color:var(--del-ink)}
.h{background:var(--hunk);color:var(--muted)}.f{color:var(--muted)}
.empty{background:var(--card);border:1px dashed var(--line);border-radius:14px;padding:24px;color:var(--muted);text-align:center}
ul.plain{margin:0;padding-left:20px}
footer{margin-top:40px;color:var(--muted);font-size:13px}
@media(max-width:520px){h1{font-size:24px}.stat b{font-size:26px}}
"""


def _e(s: str) -> str:
    return html.escape(s, quote=False)


def _inline(s: str) -> str:
    """Escape, then turn `backticks` into <code>."""
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", _e(s))


def _diff_html(diff: str) -> str:
    rows = []
    for line in diff.rstrip("\n").split("\n"):
        if line.startswith(("---", "+++")):
            cls = "f"
        elif line.startswith("@@"):
            cls = "h"
        elif line.startswith("+"):
            cls = "a"
        elif line.startswith("-"):
            cls = "d"
        else:
            cls = ""
        rows.append(f'<div class="{cls}">{_e(line) or "&nbsp;"}</div>')
    return "<pre>" + "".join(rows) + "</pre>"


def _badge(change) -> str:
    label = f"{change.name} → {change.new_name}" if change.kind == "renamed" and change.new_name else change.name
    return f'<span class="badge {change.kind}">{_e(change.kind)}: {_e(label)}</span>'


def render_html(changes, findings, proposals, missing, title: str = "docassist report") -> str:
    cards = []
    for p in proposals:
        sec = p.finding.section
        badges = "".join(_badge(c) for c in p.finding.changes)
        diff = _diff_html(p.unified_diff()) if p.changed else ""
        cards.append(
            f'<section class="card"><div class="where">{_e(sec.path)} '
            f'<small>› {_e(sec.heading)}</small></div>'
            f'<div class="badges">{badges}</div>'
            f'<p class="why">{_inline(p.note)}</p>{diff}</section>')
    body = "".join(cards) or '<div class="empty">No existing documentation references the changed symbols.</div>'

    if missing:
        items = "".join(f"<li><code>{_e(c.name)}</code> in <code>{_e(c.path)}</code></li>" for c in missing)
        extra = f'<h2>Possibly undocumented additions</h2><div class="card"><ul class="plain">{items}</ul></div>'
    else:
        extra = ""

    stamp = datetime.now().strftime("%d %b %Y, %H:%M")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(title)}</title><style>{_CSS}</style></head>
<body><div class="wrap">
<header><div class="eyebrow">docassist</div><h1>Documentation impact report</h1>
<p class="sub">Which docs a code change may have made stale, and the proposed fixes.</p></header>
<div class="stats">
<div class="stat"><b>{len(changes)}</b><span>symbol changes detected</span></div>
<div class="stat"><b>{len(findings)}</b><span>doc sections may be stale</span></div>
<div class="stat"><b>{len(missing)}</b><span>possibly undocumented additions</span></div>
</div>
<h2>Affected documentation</h2>{body}{extra}
<footer>Generated {stamp}. Proposed edits are suggestions: review before applying.</footer>
</div></body></html>"""
