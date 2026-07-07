"""A simple local web GUI for managing the workspace registry.

`vault gui` serves a one-page control panel (stdlib http.server, no deps) that
shows every object-notation node with its surfaces and offers actions —
focus a node (iTerm + Chrome), sync/apply the registry — by shelling out to
tt / surf / vault. Localhost only.
"""

import json
import subprocess
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import vault

# Whitelisted actions → argv. {node} is substituted from the request.
_ACTIONS = {
    "sync":  [["vault", "sync"]],
    "apply": [["vault", "apply"]],
    "focus": [["tt", "iterm", "focus", "{node}"], ["surf", "focus", "{node}"]],
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
 <div class=spacer></div>
 <button class=act onclick=act('sync')>⤓ sync</button>
 <button class=act onclick=act('apply')>⤒ apply</button>
 <button onclick=load()>↻</button>
</header>
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
async function load(){
 const r=await fetch('/api/status');const d=await r.json();
 document.getElementById('head').textContent=d.count+' nodes · '+(d.head||'no snapshot');
 const groups={};
 d.nodes.forEach(n=>{const g=n.path.split('.')[0];(groups[g]=groups[g]||[]).push(n)});
 const html=Object.keys(groups).sort().map(g=>
  `<div class=group>`+
   `<div class=ghead onclick="toggle('${g}')"><span class=caret id=c-${g}>▾</span>`+
   `${g} <span class=gcount>${groups[g].length}</span></div>`+
   `<div class=members id=m-${g}>${groups[g].map(nodeRow).join('')}</div></div>`
 ).join('');
 document.getElementById('nodes').innerHTML=html||'<i>registry empty — run sync</i>';
}
async function act(action,node){
 document.getElementById('out').textContent='running '+action+(node?' '+node:'')+'…';
 const r=await fetch('/api/action',{method:'POST',headers:{'content-type':'application/json'},
  body:JSON.stringify({action,node})});
 const d=await r.json();document.getElementById('out').textContent=d.output;
 if(action!=='focus')load();
}
load();
</script>"""


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
            return self._send(200, json.dumps({"count": len(nodes), "nodes": nodes, "head": head}))
        self._send(404, b"not found", "text/plain")

    def do_POST(self):
        if self.path != "/api/action":
            return self._send(404, b"not found", "text/plain")
        n = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(n) or b"{}")
        action, node = req.get("action"), req.get("node", "")
        cmds = _ACTIONS.get(action)
        if not cmds:
            return self._send(400, json.dumps({"output": f"unknown action {action!r}"}))
        lines = []
        for argv in cmds:
            argv = [a.replace("{node}", node) for a in argv]
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
