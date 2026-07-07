"""A simple local web GUI for managing the workspace registry.

`vault gui` serves a one-page control panel (stdlib http.server, no deps) that
shows every object-notation node with its surfaces, live-updating over SSE as
the registry changes, and offers actions — focus a node (iTerm + Chrome),
start a new session — by shelling out to tt / surf. Localhost only.
"""

import json
import subprocess
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import vault

# Whitelisted actions → argv. {node} and {name} are substituted from the request.
_ACTIONS = {
    "focus":      [["tt", "iterm", "focus", "{node}"], ["surf", "focus", "{node}"]],
    "new-task":   [["tt", "iterm", "new-task", "{name}"]],
    "new-tab":    [["tt", "iterm", "tab", "{name}"]],
    "new-tab-cc": [["tt", "iterm", "tab", "{name}", "--claude"]],
}

_HTML = """<!doctype html><meta charset=utf-8>
<title>geno · workspace</title>
<style>
 body{font:14px/1.5 -apple-system,system-ui,sans-serif;margin:0;background:#0f1115;color:#e6e6e6}
 header{padding:14px 20px;background:#171a21;border-bottom:1px solid #262b36;display:flex;gap:10px;align-items:center}
 h1{font-size:15px;margin:0;font-weight:600}h1 small{color:#7d8590;font-weight:400}
 button{font:inherit;background:#2a3140;color:#e6e6e6;border:1px solid #3a4252;border-radius:6px;padding:5px 11px;cursor:pointer}
 button:hover{background:#343d4f}button.act{background:#1f6feb;border-color:#1f6feb}
 .wrap{padding:16px 20px}
 .node{display:flex;align-items:center;gap:10px;padding:9px 12px;border:1px solid #262b36;border-radius:8px;margin:6px 0;background:#141821}
 .path{font-weight:600;min-width:230px}
 .badge{font-size:12px;padding:2px 8px;border-radius:10px;border:1px solid #3a4252;color:#adbac7}
 .iterm{border-color:#2ea043;color:#3fb950}.chrome{border-color:#8957e5;color:#a371f7}
 .group{margin:14px 0}
 .ghead{display:flex;align-items:center;gap:8px;padding:4px 2px;cursor:pointer;font-weight:600;color:#e6e6e6;text-transform:none}
 .ghead:hover{color:#58a6ff}.gcount{font-size:12px;color:#7d8590;font-weight:400}
 .caret{color:#7d8590;width:12px;display:inline-block}
 .members{margin-left:14px}.members.hidden{display:none}
 .path{padding-left:0}
 .spacer{flex:1}#out{white-space:pre-wrap;font:12px ui-monospace,monospace;color:#7d8590;padding:8px 20px}
</style>
<header>
 <h1>geno · workspace <small id=head></small></h1>
 <span id=live style="font-size:12px;color:#7d8590">○ connecting…</span>
 <div class=spacer></div>
 <button class=act onclick=showLaunch()>＋ session</button>
</header>
<div id=launch style="display:none;padding:10px 20px;background:#171a21;border-bottom:1px solid #262b36">
 <form onsubmit="startSession(event)" style="display:flex;gap:8px;align-items:center">
  <span style="color:#7d8590;font-size:13px">name:</span>
  <input id=lname type=text placeholder="program.area (e.g. bluebeam.rf)" required
   style="font:inherit;background:#0f1115;color:#e6e6e6;border:1px solid #3a4252;border-radius:6px;padding:5px 10px;width:260px">
  <select id=ltype style="font:inherit;background:#0f1115;color:#e6e6e6;border:1px solid #3a4252;border-radius:6px;padding:5px 10px">
   <option value=new-task>new task window (+ orchestrator)</option>
   <option value=new-tab-cc>new tab (Claude Code)</option>
   <option value=new-tab>new tab (shell)</option>
  </select>
  <button class=act type=submit>launch</button>
  <button type=button onclick=hideLaunch()>cancel</button>
 </form>
</div>
<div class=wrap id=nodes></div>
<div id=out></div>
<script>
function nodeRow(n){
 let b='';
 if(n.iterm)b+=`<span class="badge iterm">iterm ${n.iterm}</span>`;
 if(n.chrome)b+=`<span class="badge chrome">chrome ${n.chrome}</span>`;
 return `<div class=node><span class=path>${n.path}</span>${b}<span class=spacer></span>`+
  `<button onclick="act('focus','${n.path}')">focus</button></div>`;
}
function toggle(g){document.getElementById('m-'+g).classList.toggle('hidden');
 const c=document.getElementById('c-'+g);c.textContent=c.textContent==='▾'?'▸':'▾';}
function render(d){
 document.getElementById('head').textContent=d.count+' nodes · '+(d.head||'no snapshot');
 const groups={};
 d.nodes.forEach(n=>{const g=n.path.split('.')[0];(groups[g]=groups[g]||[]).push(n)});
 const html=Object.keys(groups).sort().map(g=>
  `<div class=group>`+
   `<div class=ghead onclick="toggle('${g}')"><span class=caret id=c-${g}>▾</span>`+
   `${g} <span class=gcount>${groups[g].length}</span></div>`+
   `<div class=members id=m-${g}>${groups[g].map(nodeRow).join('')}</div></div>`
 ).join('');
 document.getElementById('nodes').innerHTML=html||'<i>registry empty</i>';
}
async function act(action,node){
 document.getElementById('out').textContent='running '+action+(node?' '+node:'')+'…';
 const r=await fetch('/api/action',{method:'POST',headers:{'content-type':'application/json'},
  body:JSON.stringify({action,node})});
 const d=await r.json();document.getElementById('out').textContent=d.output;
 // registry-changing actions (new-task/new-tab*) land via the SSE stream;
 // focus doesn't touch the registry, so nothing to wait for.
}
function showLaunch(){document.getElementById('launch').style.display='block';document.getElementById('lname').focus();}
function hideLaunch(){document.getElementById('launch').style.display='none';}
async function startSession(e){
 e.preventDefault();
 const name=document.getElementById('lname').value.trim();
 const type=document.getElementById('ltype').value;
 if(!name)return;
 hideLaunch();
 document.getElementById('out').textContent='launching '+type+' '+name+'…';
 const r=await fetch('/api/action',{method:'POST',headers:{'content-type':'application/json'},
  body:JSON.stringify({action:type,name})});
 const d=await r.json();document.getElementById('out').textContent=d.output;
}
let es=null, live=false;
function connect(){
 es=new EventSource('/api/events');
 es.onmessage=ev=>{render(JSON.parse(ev.data));setLive(true);};
 es.onerror=()=>setLive(false);
}
function setLive(ok){live=ok;document.getElementById('live').textContent=ok?'● live':'○ reconnecting…';
 document.getElementById('live').style.color=ok?'#3fb950':'#7d8590';}
connect();
</script>"""


def _status() -> dict:
    reg = vault.load_registry().get("nodes", {})
    nodes = []
    for path, n in sorted(reg.items()):
        it = n.get("iterm", {})
        ch = n.get("chrome", {})
        nodes.append({
            "path": path,
            "iterm": (it.get("cwd") or it.get("tty") or "·") if it else "",
            "chrome": (f"{len(ch.get('urls', []))}t/{ch.get('color', '')}") if ch else "",
        })
    head = (vault.log(1) or [""])[0]
    return {"count": len(nodes), "nodes": nodes, "head": head}


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/":
            return self._send(200, _HTML, "text/html; charset=utf-8")
        if self.path == "/api/status":
            return self._send(200, json.dumps(_status()))
        if self.path == "/api/events":
            return self._sse_events()
        self._send(404, b"not found", "text/plain")

    def _sse_events(self):
        """Server-Sent Events: push a fresh /api/status payload whenever the
        registry file's mtime changes (geno-pear's poll pattern), plus a
        keepalive comment every ~15s so the connection doesn't look dead."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        last_mtime = None
        last_ping = time.monotonic()
        try:
            self.wfile.write(f"data: {json.dumps(_status())}\n\n".encode())
            self.wfile.flush()
            while True:
                time.sleep(1)
                cur = vault.REGISTRY.stat().st_mtime if vault.REGISTRY.exists() else None
                if cur != last_mtime:
                    last_mtime = cur
                    self.wfile.write(f"data: {json.dumps(_status())}\n\n".encode())
                    self.wfile.flush()
                    last_ping = time.monotonic()
                elif time.monotonic() - last_ping > 15:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    last_ping = time.monotonic()
        except (BrokenPipeError, ConnectionResetError):
            pass  # client tab closed

    def do_POST(self):
        if self.path != "/api/action":
            return self._send(404, b"not found", "text/plain")
        n = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(n) or b"{}")
        action, node = req.get("action"), req.get("node", "")
        name = req.get("name", node)  # for new-task/new-tab; falls back to node
        cmds = _ACTIONS.get(action)
        if not cmds:
            return self._send(400, json.dumps({"output": f"unknown action {action!r}"}))
        lines = []
        for argv in cmds:
            argv = [a.replace("{node}", node).replace("{name}", name) for a in argv]
            try:
                r = subprocess.run(argv, capture_output=True, text=True, timeout=120)
                lines.append(f"$ {' '.join(argv)}\n{(r.stdout or r.stderr).strip()}")
            except Exception as e:  # noqa: BLE001
                lines.append(f"$ {' '.join(argv)}\n! {e}")
        self._send(200, json.dumps({"output": "\n\n".join(lines)}))


def serve(port: int = 8787, open_browser: bool = True) -> None:
    srv = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"geno workspace GUI → {url}  (Ctrl-C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
        srv.shutdown()
