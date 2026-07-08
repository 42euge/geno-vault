"""A simple local web GUI for managing the workspace registry.

`geno-vault gui` serves a one-page control panel (stdlib http.server, no deps) that
shows every object-notation node with its surfaces, live-updating over SSE as
the registry changes, and offers actions — focus a node (iTerm + Chrome),
start a new session — by shelling out to tt / surf. Localhost only.
"""

import json
import re
import shutil
import subprocess
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import vault

_AUTO_PULL_INTERVAL = 45  # seconds — keeps the registry from going stale after iTerm/Chrome restarts

# Whitelisted actions → argv. {node} and {name} are substituted from the request.
_ACTIONS = {
    "focus":      [["tt", "iterm", "focus", "{node}"], ["surf", "focus", "{node}"]],
    "new-task":   [["tt", "iterm", "new-task", "{name}"]],
    "new-tab":    [["tt", "iterm", "tab", "{name}"]],
    "new-tab-cc": [["tt", "iterm", "tab", "{name}", "--claude"]],
    "fork":       [["tt", "iterm", "fork", "--node", "{node}", "--new"]],
}

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _strip_ansi(s: str) -> str:
    """tt/surf colorize their terminal output; strip the escape codes so the
    GUI's shell pane (a <pre>, not a real terminal) doesn't show raw \\x1b[2m."""
    return _ANSI_RE.sub("", s)

_HTML = """<!doctype html><meta charset=utf-8>
<title>geno · workspace</title>
<style>
 html,body{height:100%}
 body{font:14px/1.5 -apple-system,system-ui,sans-serif;margin:0;background:#0b0d11;color:#e6e6e6;
  display:flex;flex-direction:column;overflow:hidden}
 header{padding:14px 20px;background:#171a21;border-bottom:1px solid #262b36;display:flex;gap:10px;align-items:center;flex:none}
 h1{font-size:15px;margin:0;font-weight:600}h1 small{color:#7d8590;font-weight:400}
 button{font:inherit;background:#2a3140;color:#e6e6e6;border:1px solid #3a4252;border-radius:6px;padding:5px 11px;cursor:pointer}
 button:hover{background:#343d4f}button.act{background:#1f6feb;border-color:#1f6feb}
 button:disabled{background:#171a21;color:#4d5566;border-color:#262b36;cursor:not-allowed}
 button:disabled:hover{background:#171a21}
 .spacer{flex:1}
 #search{font:inherit;background:#0f1115;color:#e6e6e6;border:1px solid #3a4252;border-radius:6px;padding:5px 10px;width:200px}

 /* main is a horizontal split: left column (tree + shell) | right detail card, both real flex children */
 main{flex:1;display:flex;min-height:0}
 #left{flex:1;display:flex;flex-direction:column;min-width:0;min-height:0}
 #scroll{flex:1;overflow-y:auto}

 /* tier 1 — program cards. Pinned "manager" card first, then the rest alphabetical
    so reading order is unambiguous. */
 .grid{display:flex;flex-direction:column;gap:12px;padding:16px 20px;max-width:760px}
 .card{background:#12151b;border:1px solid #262b36;border-radius:10px;overflow:hidden}
 .chead{display:flex;align-items:center;gap:8px;padding:10px 14px;background:#171a21;border-bottom:1px solid #262b36;cursor:pointer}
 .chead:hover{background:#1b1f28}
 .cname{font-weight:700;letter-spacing:.2px}
 .ccount{font-size:12px;color:#7d8590;font-weight:400}
 .cbody{padding:8px 6px}
 .cbody.hidden{display:none}
 .cadd{margin-left:auto;background:none;border:none;color:#7d8590;font-size:16px;padding:0 4px;line-height:1}
 .cadd:hover{color:#58a6ff;background:none}

 /* the manager card: the ecosystem's own control session — visually set apart, not just another program */
 .card.pinned{border-color:#3d4a63;box-shadow:0 0 0 1px #1f6feb22}
 .card.pinned .chead{background:linear-gradient(180deg,#182236,#161c28);border-bottom-color:#2a3a56}
 .card.pinned .cname::before{content:"★ ";color:#58a6ff}

 /* tier 2 — object-notation tree: path + connector lines only, nothing else competing for the line */
 .tree{font:12.5px ui-monospace,SFMono-Regular,Menlo,monospace}
 .branch{white-space:pre;color:#4d5566}
 .seg{color:#adbac7;font-weight:600;font-family:-apple-system,sans-serif;font-size:13px}
 .leaf{display:flex;align-items:center;padding:3px 6px;border-radius:6px;cursor:pointer}
 .leaf:hover{background:#1a1e26}
 .leaf.sel{background:#16324d;box-shadow:inset 2px 0 0 #58a6ff}
 .dot{width:7px;height:7px;border-radius:50%;flex:none;margin:0 4px 0 6px;background:#3a4252}
 .rollup{font-size:11px;color:#4d5566;margin-left:8px;white-space:nowrap}

 /* launch modal */
 #overlay{display:none;position:fixed;inset:0;background:#000a;align-items:center;justify-content:center;z-index:10}
 #launch{background:#171a21;border:1px solid #3a4252;border-radius:10px;padding:20px;width:360px}
 #launch h2{margin:0 0 14px;font-size:14px;color:#e6e6e6}
 #launch label{display:block;font-size:12px;color:#7d8590;margin:10px 0 4px}
 #launch input,#launch select{font:inherit;width:100%;box-sizing:border-box;background:#0f1115;color:#e6e6e6;border:1px solid #3a4252;border-radius:6px;padding:7px 10px}
 #launch .row{display:flex;gap:8px;margin-top:16px;justify-content:flex-end}

 /* detail — a large floating card, same visual language as the tree cards, not an edge-docked strip */
 #detail{flex:none;width:0;overflow:hidden;transition:width .16s ease,opacity .16s ease;opacity:0}
 #detail.open{width:440px;opacity:1;padding:16px 16px 16px 0}
 #detail .dcard{background:#12151b;border:1px solid #262b36;border-radius:12px;height:100%;
  display:flex;flex-direction:column;overflow-y:auto;box-shadow:0 8px 28px #0006}
 #detail .dhead{display:flex;align-items:center;gap:10px;padding:18px 22px;border-bottom:1px solid #262b36;flex:none}
 #detail .dpath{font-weight:700;font-size:18px;word-break:break-all}
 #detail .dclose{margin-left:auto;background:none;border:none;color:#7d8590;font-size:20px;padding:0 4px}
 #detail .dclose:hover{color:#e6e6e6;background:none}
 #detail .dsection{padding:18px 22px;border-bottom:1px solid #1c2029}
 #detail .dlabel{font-size:12px;color:#7d8590;text-transform:uppercase;letter-spacing:.5px;margin-bottom:10px;display:flex;align-items:center;gap:6px}
 #detail .dswatch{width:10px;height:10px;border-radius:50%;flex:none}
 #detail .drow{display:flex;gap:8px;font:13.5px ui-monospace,monospace;color:#c9d1d9;word-break:break-all;padding:3px 0}
 #detail .drow b{color:#7d8590;font-weight:400;flex:none;width:60px}
 #detail .durl{display:block;color:#a371f7;text-decoration:none;font-size:13px;padding:3px 0;word-break:break-all}
 #detail .durl:hover{text-decoration:underline}
 #detail .dempty{color:#4d5566;font-style:italic;font-size:13px}
 #detail .dactions{padding:18px 22px;display:flex;gap:8px;margin-top:auto}

 /* shell pane — separate fixed strip at the bottom, not inline with the tree */
 #shell{flex:none;height:170px;display:flex;flex-direction:column;background:#0d0f13;border-top:1px solid #262b36}
 #shell .shead{flex:none;display:flex;align-items:center;gap:8px;padding:6px 14px;color:#7d8590;font-size:11px;
  text-transform:uppercase;letter-spacing:.5px;border-bottom:1px solid #1c2029}
 #shell .sclear{margin-left:auto;background:none;border:none;color:#4d5566;font-size:11px;padding:0;text-transform:none;letter-spacing:0}
 #shell .sclear:hover{color:#e6e6e6;background:none}
 #out{flex:1;overflow-y:auto;white-space:pre-wrap;font:12px ui-monospace,monospace;color:#7d8590;padding:8px 14px;margin:0}
</style>
<header>
 <h1>geno · workspace <small id=head></small></h1>
 <span id=live style="font-size:12px;color:#7d8590">○ connecting…</span>
 <div class=spacer></div>
 <input id=search placeholder="filter…" oninput=applyFilter()>
 <button class=act onclick="showLaunch('')">＋ session</button>
</header>
<main>
 <div id=left>
  <div id=scroll><div class=grid id=nodes></div></div>
  <div id=shell>
   <div class=shead>shell<button class=sclear onclick="document.getElementById('out').textContent=''">clear</button></div>
   <pre id=out></pre>
  </div>
 </div>
 <div id=detail>
  <div class=dcard>
   <div class=dhead>
    <span class=dpath id=dpath></span>
    <button class=dclose onclick=closeDetail()>✕</button>
   </div>
   <div id=dbody></div>
   <div class=dactions id=dactions></div>
  </div>
 </div>
</main>

<div id=overlay onclick="if(event.target===this)hideLaunch()">
 <div id=launch>
  <h2>start a session</h2>
  <form onsubmit="startSession(event)">
   <label>object-notation name</label>
   <input id=lname type=text placeholder="program.area.aspect" required autocomplete=off>
   <label>type</label>
   <select id=ltype>
    <option value=new-task>new task window (+ orchestrator)</option>
    <option value=new-tab-cc>new tab (Claude Code)</option>
    <option value=new-tab>new tab (shell)</option>
   </select>
   <div class=row>
    <button type=button onclick=hideLaunch()>cancel</button>
    <button class=act type=submit>launch</button>
   </div>
  </form>
 </div>
</div>

<script>
const CHROME_COLORS={grey:'#5f6368',blue:'#1a73e8',red:'#d93025',yellow:'#f9ab00',
 green:'#1e8e3e',pink:'#d01884',purple:'#a142f4',cyan:'#12b5cb',orange:'#fa903e'};

function buildTree(nodes){
 const root={children:{}};
 nodes.forEach(n=>{
  const parts=n.path.split('.');
  let cur=root, acc=[];
  parts.forEach((p,i)=>{
   acc.push(p);
   cur.children=cur.children||{};
   cur.children[p]=cur.children[p]||{name:p,path:acc.join('.'),children:null};
   cur=cur.children[p];
   if(i===parts.length-1)cur.leaf=n;
  });
 });
 return root;
}
function leafCount(t){
 let c=t.leaf?1:0;
 if(t.children)for(const k in t.children)c+=leafCount(t.children[k]);
 return c;
}
function rollup(t){
 // sum iterm/chrome attachment counts across every leaf under this subtree
 let iterm=0,chrome=0,tabs=0;
 if(t.leaf){if(t.leaf.iterm)iterm++;if(t.leaf.chrome){chrome++;tabs+=t.leaf.chrome.tabs;}}
 if(t.children)for(const k in t.children){const r=rollup(t.children[k]);iterm+=r.iterm;chrome+=r.chrome;tabs+=r.tabs;}
 return {iterm,chrome,tabs};
}
function renderChildren(children,prefix){
 const entries=Object.entries(children).sort((a,b)=>a[0].localeCompare(b[0]));
 return entries.map(([name,child],i)=>{
  const last=i===entries.length-1;
  const connector=last?'└─':'├─';
  const childPrefix=prefix+(last?'   ':'│  ');
  const color=child.leaf&&child.leaf.chrome?CHROME_COLORS[child.leaf.chrome.color]||'#3a4252':null;
  const r=!child.leaf?rollup(child):null;
  let html=`<div class="leaf${child.leaf?'':' nonleaf'}" onclick="openDetail('${child.path}')" data-leaf="${child.path}">`+
   `<span class=branch>${prefix}${connector} </span><span class=seg>${name}</span>`+
   `<span class=spacer></span>`+
   (color?`<span class=dot style="background:${color}"></span>`:'')+
   (r?`<span class=rollup>${r.iterm}⌁ ${r.tabs}⧉</span>`:'')+
   `</div>`;
  if(child.children)html+=renderChildren(child.children,childPrefix);
  return html;
 }).join('');
}
function toggle(g){document.getElementById('b-'+g).classList.toggle('hidden');
 const c=document.getElementById('c-'+g);c.textContent=c.textContent==='▾'?'▸':'▾';}
let lastData=null, selectedPath=null;
function render(d){
 lastData=d;
 document.getElementById('head').textContent=d.count+' nodes · '+(d.head||'no snapshot');
 const tree=buildTree(d.nodes);
 const groups=Object.entries(tree.children||{}).sort((a,b)=>{
  if(a[0]==='manager')return -1;
  if(b[0]==='manager')return 1;
  return a[0].localeCompare(b[0]);
 });
 document.getElementById('nodes').innerHTML=groups.map(([g,sub])=>
  `<div class="card${g==='manager'?' pinned':''}" data-group="${g}">`+
   `<div class=chead>`+
    `<span class=caret id=c-${g} onclick="toggle('${g}')">▾</span>`+
    `<span class=cname onclick="openDetail('${g}')" style="cursor:pointer">${g}</span>`+
    `<span class=ccount>${leafCount(sub)}</span>`+
    `<button class=cadd title="new session under ${g}" onclick="event.stopPropagation();showLaunch('${g}.')">＋</button>`+
   `</div>`+
   `<div class="cbody tree" id=b-${g}>${renderChildren(sub.children,'')}</div>`+
  `</div>`
 ).join('') || '<i style="padding:0 20px">registry empty</i>';
 applyFilter();
 markSelected();
 if(selectedPath)openDetail(selectedPath);  // refresh panel content if it's open
}
function markSelected(){
 document.querySelectorAll('.leaf.sel').forEach(el=>el.classList.remove('sel'));
 if(selectedPath){
  const el=document.querySelector(`.leaf[data-leaf="${selectedPath}"]`);
  if(el)el.classList.add('sel');
 }
}
function applyFilter(){
 const q=document.getElementById('search').value.trim().toLowerCase();
 document.querySelectorAll('.card').forEach(card=>{
  const hit=!q||card.dataset.group.toLowerCase().includes(q)||card.textContent.toLowerCase().includes(q);
  card.style.display=hit?'':'none';
 });
}
function openDetail(path){
 const leaf=(lastData.nodes||[]).find(x=>x.path===path);
 selectedPath=path;
 markSelected();
 document.getElementById('dpath').textContent=path;
 if(leaf)renderLeafDetail(path,leaf); else renderBranchDetail(path);
 document.getElementById('detail').classList.add('open');
}
function renderLeafDetail(path,n){
 const it=n.iterm, ch=n.chrome;
 const itHtml=it?
  `<div class=drow><b>tty</b>${it.tty||'—'}</div>`+
  `<div class=drow><b>cwd</b>${it.cwd||'—'}</div>`+
  `<div class=drow><b>window</b>${it.window_id||'—'}</div>`
  :`<div class=dempty>no iTerm tab attached</div>`;
 const swatch=ch?`<span class=dswatch style="background:${CHROME_COLORS[ch.color]||'#3a4252'}"></span>`:'';
 const chHtml=ch?
  `<div class=drow><b>group</b>${ch.group||'—'}</div>`+
  `<div class=drow><b>color</b>${ch.color||'—'}</div>`+
  (ch.urls&&ch.urls.length?ch.urls.map(u=>`<a class=durl href="${u}" target=_blank>${u}</a>`).join(''):`<div class=dempty>no tabs</div>`)
  :`<div class=dempty>no Chrome tab group attached</div>`;
 document.getElementById('dbody').innerHTML=
  `<div class=dsection><div class=dlabel>⌁ iterm</div>${itHtml}</div>`+
  `<div class=dsection><div class=dlabel>${swatch}⧉ chrome</div>${chHtml}</div>`;
 const noSurfaces=!it&&!ch;
 document.getElementById('dactions').innerHTML=
  `<button class=act ${noSurfaces?'disabled title="no live iTerm or Chrome tab to focus"':''} onclick="act('focus','${path}')">focus</button>`+
  `<button ${!it?'disabled title="no live iTerm tab to fork"':''} onclick="act('fork','${path}')">⑂ fork</button>`+
  `<button onclick="showLaunch('${path}.')">+ tab here</button>`;
}
function renderBranchDetail(path){
 // a group/branch node: no surfaces of its own — show the rollup + the leaves under it
 const under=(lastData.nodes||[]).filter(x=>x.path===path||x.path.startsWith(path+'.'));
 const r=under.reduce((a,n)=>({iterm:a.iterm+(n.iterm?1:0),chrome:a.chrome+(n.chrome?1:0),
  tabs:a.tabs+(n.chrome?n.chrome.tabs:0)}),{iterm:0,chrome:0,tabs:0});
 const rows=under.map(n=>{
  const color=n.chrome?CHROME_COLORS[n.chrome.color]||'#3a4252':null;
  return `<div class=leaf onclick="openDetail('${n.path}')" data-leaf="${n.path}" style="cursor:pointer">`+
   `<span class=seg>${n.path.slice(path.length+1)||n.path}</span><span class=spacer></span>`+
   (n.iterm?'<span class="chip on" style="font-size:11px">⌁</span>':'')+
   (color?`<span class=dot style="background:${color}"></span>`:'')+
   `</div>`;
 }).join('')||'<div class=dempty>no nodes under this branch</div>';
 document.getElementById('dbody').innerHTML=
  `<div class=dsection><div class=dlabel>rollup</div>`+
   `<div class=drow><b>nodes</b>${under.length}</div>`+
   `<div class=drow><b>iterm</b>${r.iterm} tab${r.iterm===1?'':'s'} attached</div>`+
   `<div class=drow><b>chrome</b>${r.chrome} group${r.chrome===1?'':'s'} · ${r.tabs} tab${r.tabs===1?'':'s'}</div>`+
  `</div>`+
  `<div class=dsection><div class=dlabel>nodes</div>${rows}</div>`;
 document.getElementById('dactions').innerHTML=
  `<button class=act onclick="showLaunch('${path}.')">+ session under ${path}</button>`;
}
function closeDetail(){
 selectedPath=null;
 document.getElementById('detail').classList.remove('open');
 markSelected();
}
async function act(action,node){
 const out=document.getElementById('out');
 out.textContent+=(out.textContent?'\\n\\n':'')+'$ '+action+(node?' '+node:'')+'…';
 out.scrollTop=out.scrollHeight;
 const r=await fetch('/api/action',{method:'POST',headers:{'content-type':'application/json'},
  body:JSON.stringify({action,node})});
 const d=await r.json();
 out.textContent+='\\n'+d.output;
 out.scrollTop=out.scrollHeight;
 // registry-changing actions (new-task/new-tab*) land via the SSE stream;
 // focus doesn't touch the registry, so nothing to wait for.
}
function showLaunch(prefix){
 document.getElementById('overlay').style.display='flex';
 const f=document.getElementById('lname');f.value=prefix||'';f.focus();
 f.setSelectionRange(f.value.length,f.value.length);
}
function hideLaunch(){document.getElementById('overlay').style.display='none';}
async function startSession(e){
 e.preventDefault();
 const name=document.getElementById('lname').value.trim();
 const type=document.getElementById('ltype').value;
 if(!name)return;
 hideLaunch();
 await act(type,name);
}
let es=null;
function connect(){
 es=new EventSource('/api/events');
 es.onmessage=ev=>{render(JSON.parse(ev.data));setLive(true);};
 es.onerror=()=>setLive(false);
}
function setLive(ok){document.getElementById('live').textContent=ok?'● live':'○ reconnecting…';
 document.getElementById('live').style.color=ok?'#3fb950':'#7d8590';}
document.addEventListener('keydown',e=>{if(e.key==='Escape'){hideLaunch();closeDetail();}});
connect();
</script>"""


def _status() -> dict:
    reg = vault.load_registry().get("nodes", {})
    nodes = []
    for path, n in sorted(reg.items()):
        it = n.get("iterm")
        ch = n.get("chrome")
        nodes.append({
            "path": path,
            "iterm": {
                "loc": it.get("cwd") or it.get("tty") or "",
                "tty": it.get("tty", ""), "cwd": it.get("cwd", ""),
                "window_id": it.get("window_id", ""),
            } if it else None,
            "chrome": {
                "tabs": len(ch.get("urls", [])), "color": ch.get("color", ""),
                "group": ch.get("group", ""), "urls": ch.get("urls", []),
            } if ch else None,
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
                out = _strip_ansi((r.stdout or r.stderr).strip())
                lines.append(f"$ {' '.join(argv)}\n{out}")
            except Exception as e:  # noqa: BLE001
                lines.append(f"$ {' '.join(argv)}\n! {e}")
        self._send(200, json.dumps({"output": "\n\n".join(lines)}))


def _auto_pull_loop(stop: threading.Event) -> None:
    """Background heartbeat: re-pull tt/surf into the registry on an interval so
    stale ttys/tab groups (from a restarted iTerm or closed Chromium) self-heal
    without a manual `vault sync`. Each puller is independent and silent on
    failure — surf being down (Chromium not running) must not block tt's pull."""
    while not stop.wait(_AUTO_PULL_INTERVAL):
        for cmd in (["tt", "iterm", "reg", "pull"], ["surf", "reg", "pull"]):
            if not shutil.which(cmd[0]):
                continue
            try:
                subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            except Exception:  # noqa: BLE001 — heartbeat must never crash the server
                pass


def _open_bg(url: str) -> None:
    """Open url in the background — no focus steal. Falls back to webbrowser."""
    try:
        subprocess.run(["open", "-g", url], check=False)
    except OSError:
        webbrowser.open(url)


def serve(port: int = 8787, open_browser: bool = True) -> None:
    srv = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    url = f"http://127.0.0.1:{port}/"
    stop = threading.Event()
    threading.Thread(target=_auto_pull_loop, args=(stop,), daemon=True).start()
    print(f"geno workspace GUI → {url}  (Ctrl-C to stop)")
    if open_browser:
        _open_bg(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
        stop.set()
        srv.shutdown()
