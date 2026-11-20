"""A small local web app: paste a code diff, review proposed doc fixes, apply the ones you accept.

Run:  python -m docassist serve --docs README.md docs
Everything runs on your own machine (127.0.0.1); nothing is uploaded anywhere.
"""

from __future__ import annotations

import json
import secrets
import threading
import webbrowser
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .diff import analyze_diff
from .docs import load_docs
from .htmlreport import _CSS
from .matcher import find_affected, undocumented
from .proposer import propose

MAX_BODY = 2_000_000


class App:
    """State + logic, kept separate from HTTP so it can be tested directly."""

    def __init__(self) -> None:
        self.token = secrets.token_urlsafe(24)
        self.proposals: dict = {}
        self.lock = threading.Lock()

    def analyze(self, diff_text: str, docs: list[str]) -> dict:
        if not diff_text.strip():
            raise ValueError("Paste a code diff first (the output of `git diff`).")
        docs = [d.strip() for d in docs if d.strip()]
        changes = analyze_diff(diff_text)
        sections = load_docs(docs)
        if not sections:
            raise ValueError("No markdown files found in: " + ", ".join(docs or ["(nothing)"]))
        findings = find_affected(changes, sections)
        proposals = propose(findings, "auto")

        store, items = {}, []
        for i, p in enumerate(proposals):
            pid = str(i)
            store[pid] = p
            sec = p.finding.section
            kinds = {c.kind for c in p.finding.changes}
            items.append({
                "id": pid, "path": sec.path, "heading": sec.heading, "note": p.note,
                "changed": p.changed, "safe": kinds == {"renamed"},
                "changes": [{"kind": c.kind, "name": c.name, "new_name": c.new_name} for c in p.finding.changes],
                "diff": p.unified_diff(),
            })
        with self.lock:
            self.proposals = store
        missing = [{"name": c.name, "path": c.path} for c in undocumented(changes, sections)]
        return {"summary": {"changes": len(changes), "flagged": len(items), "missing": len(missing)},
                "items": items, "missing": missing}

    def apply(self, ids: list[str]) -> dict:
        with self.lock:
            chosen = [self.proposals[i] for i in ids if i in self.proposals]
        by_file: dict[str, list] = defaultdict(list)
        for p in chosen:
            if p.changed:
                by_file[p.finding.section.path].append(p)
        applied, conflicts = 0, []
        for path, props in by_file.items():
            lines = Path(path).read_text(encoding="utf-8").split("\n")
            for p in sorted(props, key=lambda x: x.finding.section.start, reverse=True):
                s = p.finding.section
                if lines[s.start:s.end] != s.lines:  # file edited since analysis: do not guess
                    conflicts.append(f"{path} › {s.heading}: the file changed since the analysis, re-run it")
                    continue
                lines[s.start:s.end] = p.new_lines
                applied += 1
            Path(path).write_text("\n".join(lines), encoding="utf-8")
        with self.lock:
            self.proposals = {}  # line numbers are stale after any edit
        return {"applied": applied, "conflicts": conflicts}


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>docassist</title><style>__CSS__
label.f{display:block;font-weight:600;margin:14px 0 6px}
textarea,input[type=text]{width:100%;border:1px solid var(--line);border-radius:10px;background:var(--bg);color:var(--ink);
padding:10px 12px;font:14px/1.5 ui-monospace,Consolas,monospace}
textarea{min-height:170px;resize:vertical}
button{font:600 15px system-ui,sans-serif;border:0;border-radius:10px;padding:10px 18px;cursor:pointer;
background:var(--brand);color:#fff}
button.ghost{background:transparent;color:var(--brand);border:1px solid var(--line)}
button:disabled{opacity:.5;cursor:default}
.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:14px}
.err{background:var(--del-bg);color:var(--del-ink);border-radius:10px;padding:10px 14px;margin-top:14px}
.ok{background:var(--add-bg);color:var(--add-ink);border-radius:10px;padding:10px 14px;margin-bottom:16px}
.pick{display:flex;align-items:center;gap:8px;margin-top:12px;font-weight:600}
.pick input{width:18px;height:18px}
.tag{font-size:12px;font-weight:600;color:var(--muted);border:1px solid var(--line);border-radius:999px;padding:1px 8px}
.bar{position:sticky;bottom:0;background:var(--card);border:1px solid var(--line);border-radius:14px;
padding:12px 16px;margin-top:16px;display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}
</style></head><body><div class="wrap">
<header><div class="eyebrow">docassist</div><h1>Find stale docs, fix them in one click</h1>
<p class="sub">Paste a code change. docassist shows which documentation it may have made stale. You choose which fixes to apply.</p></header>
<div class="card">
<label class="f" for="diff">Code diff (output of <code>git diff</code>)</label>
<textarea id="diff" spellcheck="false" placeholder="diff --git a/app.py b/app.py ..."></textarea>
<label class="f" for="docs">Documentation files or folders (one per line)</label>
<textarea id="docs" spellcheck="false" style="min-height:64px"></textarea>
<div class="row"><button id="go">Analyze</button><span class="sub" id="busy"></span></div>
<div id="err"></div></div>
<div id="out"></div>
</div>
<script>
const TOKEN="__TOKEN__", INIT=__INIT__;
const $=s=>document.querySelector(s);
const el=(t,c,x)=>{const e=document.createElement(t);if(c)e.className=c;if(x!==undefined)e.textContent=x;return e};
$("#diff").value=INIT.diff||""; $("#docs").value=(INIT.docs||[]).join("\\n");
async function api(path,body){
  const r=await fetch(path,{method:"POST",headers:{"Content-Type":"application/json","X-Token":TOKEN},body:JSON.stringify(body)});
  const j=await r.json(); if(!r.ok) throw new Error(j.error||r.statusText); return j;
}
function diffView(text){
  const pre=el("pre");
  text.replace(/\\n$/,"").split("\\n").forEach(l=>{
    const c=/^(---|\\+\\+\\+)/.test(l)?"f":l.startsWith("@@")?"h":l.startsWith("+")?"a":l.startsWith("-")?"d":"";
    pre.appendChild(el("div",c,l||" "));
  });
  return pre;
}
function render(data,banner){
  const out=$("#out"); out.textContent="";
  if(banner) out.appendChild(el("div","ok",banner));
  const s=data.summary, stats=el("div","stats");
  [[s.changes,"symbol changes detected"],[s.flagged,"doc sections may be stale"],[s.missing,"possibly undocumented additions"]]
    .forEach(([n,t])=>{const d=el("div","stat");d.appendChild(el("b","",n));d.appendChild(el("span","",t));stats.appendChild(d)});
  out.appendChild(stats);
  out.appendChild(el("h2","","Affected documentation"));
  if(!data.items.length) out.appendChild(el("div","empty","No existing documentation references the changed symbols."));
  data.items.forEach(it=>{
    const card=el("section","card"), w=el("div","where",it.path+" "); w.appendChild(el("small","","› "+it.heading));
    card.appendChild(w);
    const b=el("div","badges");
    it.changes.forEach(c=>b.appendChild(el("span","badge "+c.kind,c.kind+": "+(c.new_name?c.name+" → "+c.new_name:c.name))));
    card.appendChild(b); card.appendChild(el("p","why",it.note.replace(/`/g,"")));
    if(it.changed) card.appendChild(diffView(it.diff));
    if(it.changed){
      const p=el("label","pick"), cb=el("input"); cb.type="checkbox"; cb.dataset.id=it.id; cb.checked=it.safe;
      p.appendChild(cb); p.appendChild(el("span","",it.safe?"Apply this fix":"Add this review note to the doc"));
      if(it.safe) p.appendChild(el("span","tag","safe rename"));
      card.appendChild(p);
    }
    out.appendChild(card);
  });
  if(data.missing.length){
    out.appendChild(el("h2","","Possibly undocumented additions"));
    const c=el("div","card"), ul=el("ul","plain");
    data.missing.forEach(m=>{const li=el("li");li.appendChild(el("code","",m.name));li.appendChild(document.createTextNode(" in "));li.appendChild(el("code","",m.path));ul.appendChild(li)});
    c.appendChild(ul); out.appendChild(c);
  }
  if(data.items.some(i=>i.changed)){
    const bar=el("div","bar"), n=el("span","sub"), btn=el("button","","Apply selected fixes");
    const upd=()=>{const k=out.querySelectorAll("input[type=checkbox]:checked").length;n.textContent=k+" selected";btn.disabled=!k};
    out.addEventListener("change",upd); upd();
    btn.onclick=async()=>{
      const ids=[...out.querySelectorAll("input[type=checkbox]:checked")].map(x=>x.dataset.id);
      btn.disabled=true;
      try{
        const r=await api("/api/apply",{ids});
        let msg="Applied "+r.applied+" fix"+(r.applied===1?"":"es")+" to your documentation files.";
        if(r.conflicts.length) msg+=" Skipped: "+r.conflicts.join("; ");
        await analyze(msg);
      }catch(e){$("#err").textContent="";$("#err").appendChild(el("div","err",e.message))}
    };
    bar.appendChild(n); bar.appendChild(btn); out.appendChild(bar);
  }
}
async function analyze(banner){
  $("#err").textContent=""; $("#busy").textContent="Analyzing...";
  try{
    const data=await api("/api/analyze",{diff:$("#diff").value,docs:$("#docs").value.split("\\n")});
    render(data,banner);
  }catch(e){$("#out").textContent="";$("#err").appendChild(el("div","err",e.message))}
  $("#busy").textContent="";
}
$("#go").onclick=()=>analyze();
</script></body></html>"""


def make_handler(app: App, init: dict, port: int):
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # keep the terminal quiet
            pass

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj: dict) -> None:
            self._send(code, json.dumps(obj).encode("utf-8"), "application/json")

        def do_GET(self):  # noqa: N802
            if self.headers.get("Host") not in allowed_hosts or self.path.split("?")[0] != "/":
                return self._json(404, {"error": "not found"})
            init_json = json.dumps(init).replace("</", "<\\/")
            page = (PAGE.replace("__CSS__", _CSS).replace("__TOKEN__", app.token)
                    .replace("__INIT__", init_json))
            self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")

        def do_POST(self):  # noqa: N802
            if self.headers.get("Host") not in allowed_hosts or self.headers.get("X-Token") != app.token:
                return self._json(403, {"error": "forbidden"})
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size > MAX_BODY:
                    return self._json(413, {"error": "diff is too large"})
                payload = json.loads(self.rfile.read(size) or b"{}")
                if self.path == "/api/analyze":
                    return self._json(200, app.analyze(str(payload.get("diff", "")), list(payload.get("docs", []))))
                if self.path == "/api/apply":
                    return self._json(200, app.apply([str(i) for i in payload.get("ids", [])]))
                return self._json(404, {"error": "not found"})
            except ValueError as e:
                return self._json(400, {"error": str(e)})
            except Exception as e:  # never crash the server on one bad request
                return self._json(500, {"error": f"{type(e).__name__}: {e}"})

    return Handler


def serve(docs: list[str], diff_file: str | None = None, port: int = 8765, open_browser: bool = True) -> int:
    init = {"docs": docs, "diff": Path(diff_file).read_text(encoding="utf-8") if diff_file else ""}
    app = App()
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app, init, port))
    url = f"http://127.0.0.1:{port}/"
    print(f"docassist is running at {url}  (press Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return 0
