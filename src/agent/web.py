"""Non-blocking web chat server.

Runs on the same thread as the serial console: main.py polls both this server's
listening socket and stdin, so a single agent instance serves both interfaces
without locking or a second stack.
"""

import gc
import json
import os
import socket

from . import config as _config
from . import settings as _settings

# Raw string: the inline JS carries its own backslash escapes (\d, \s, \x00)
# which Python must pass through untouched.
PAGE = r"""<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ESP32-S3 Agent</title>
<style>
:root{color-scheme:dark;--bg:#000700;--panel:#04140a;--line:#0d4a1e;--fg:#00ff41;--dim:#00a62c;--accent:#00ff41;--code:#03190b;--glow:0 0 5px rgba(0,255,65,.35)}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 ui-monospace,SFMono-Regular,Menlo,Consolas,"Courier New",monospace;display:flex;flex-direction:column;height:100vh;text-shadow:var(--glow)}
::selection{background:var(--accent);color:#000;text-shadow:none}
::-webkit-scrollbar{width:9px;height:9px}
::-webkit-scrollbar-track{background:var(--bg)}
::-webkit-scrollbar-thumb{background:var(--line);border-radius:5px}
::-webkit-scrollbar-thumb:hover{background:var(--dim)}
header{padding:12px 16px;border-bottom:1px solid var(--line);font-weight:700;display:flex;gap:8px;align-items:center;letter-spacing:.14em;text-transform:uppercase;font-size:13px}
header small{color:var(--dim);font-weight:400;letter-spacing:.1em}
header small::after{content:"_";animation:blink 1.1s step-end infinite}
@keyframes blink{50%{opacity:0}}
#log{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:12px}
.msg{max-width:min(680px,90%);padding:10px 13px;border-radius:4px;word-wrap:break-word;overflow-wrap:anywhere}
.user{align-self:flex-end;background:var(--accent);color:#000;font-weight:600;border-bottom-right-radius:0;white-space:pre-wrap;text-shadow:none;box-shadow:0 0 12px rgba(0,255,65,.3)}
.bot{align-self:flex-start;background:var(--panel);border:1px solid var(--line);border-bottom-left-radius:0}
.tool{align-self:flex-start;color:var(--dim);font-size:12px;padding:2px 4px;white-space:pre-wrap;opacity:.85}
.shot{align-self:flex-start;max-width:min(680px,90%);padding:6px}
.shot img{display:block;width:100%;height:auto;border:1px solid var(--line);border-radius:4px}
.shot a{display:block;margin-top:5px;font-size:11px;color:var(--dim);letter-spacing:.06em;text-transform:uppercase;text-decoration:none}
.shot a:hover{color:var(--accent)}
.shot audio{width:100%;display:block;border:1px solid var(--line);border-radius:4px;background:var(--panel)}
.shot .cap{font-size:11px;color:var(--dim);letter-spacing:.06em;text-transform:uppercase;margin-bottom:4px}
.bot>*:first-child{margin-top:0}.bot>*:last-child{margin-bottom:0}
.bot p{margin:.5em 0}
.bot h1,.bot h2,.bot h3,.bot h4{margin:.8em 0 .4em;line-height:1.25}
.bot h1{font-size:1.35em}.bot h2{font-size:1.2em}.bot h3{font-size:1.08em}.bot h4{font-size:1em}
.bot ul,.bot ol{margin:.5em 0;padding-left:1.4em}
.bot li{margin:.2em 0}
.bot h1,.bot h2,.bot h3,.bot h4{text-transform:uppercase;letter-spacing:.06em}
.bot a{color:var(--accent);text-decoration:underline}
.bot strong{color:#7dffa4}
.bot code{background:var(--code);padding:.12em .38em;border-radius:3px;border:1px solid rgba(0,255,65,.16);font-size:.9em}
.bot pre{background:var(--code);padding:10px 12px;border-radius:4px;border:1px solid var(--line);overflow-x:auto;margin:.6em 0}
.bot pre code{background:none;padding:0;border:0;font-size:.88em;line-height:1.45}
.bot hr{border:0;border-top:1px solid var(--line);margin:.8em 0}
.bot blockquote{margin:.5em 0;padding-left:.8em;border-left:3px solid var(--line);color:var(--dim)}
.tw{overflow-x:auto;margin:.6em 0}
.bot table{border-collapse:collapse;font-size:.93em}
.bot th,.bot td{border:1px solid var(--line);padding:5px 9px;text-align:left;white-space:nowrap}
.bot th{background:var(--code);font-weight:700;text-transform:uppercase;letter-spacing:.06em;font-size:.9em}
#nav{margin-left:auto;display:flex;gap:6px}
.tab{background:none;border:1px solid var(--line);color:var(--dim);padding:5px 11px;border-radius:3px;font:inherit;font-size:11px;letter-spacing:.12em;text-transform:uppercase;cursor:pointer;text-shadow:none}
.tab.on{color:#000;background:var(--accent);border-color:var(--accent);font-weight:700}
#cfg{flex:1;overflow-y:auto;padding:16px;display:none}
#cfg.on{display:block}
#log.off{display:none}
form.chat{display:flex;gap:8px;padding:12px;border-top:1px solid var(--line);background:var(--panel)}
form.chat.off{display:none}
fieldset{border:1px solid var(--line);border-radius:4px;margin:0 0 14px;padding:10px 14px 14px;max-width:640px}
legend{color:var(--dim);font-size:11px;letter-spacing:.16em;text-transform:uppercase;padding:0 6px}
.row{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:9px 0}
.row label{flex:0 0 190px;font-size:13px;color:var(--dim)}
.row .in{flex:1;min-width:180px}
.row input[type=text],.row input[type=password],.row input[type=number],.row select,.row textarea{width:100%;padding:7px 10px;border-radius:3px;border:1px solid var(--line);background:#000;color:var(--fg);font:inherit;font-size:13px;text-shadow:var(--glow)}
.row textarea{min-height:64px;resize:vertical}
.row input[type=checkbox]{width:16px;height:16px;accent-color:var(--accent)}
.row .hint{flex-basis:100%;font-size:11px;color:var(--dim);opacity:.75;margin-left:198px}
.row .ro{color:var(--dim);font-size:12px;padding:7px 0;overflow-x:auto;white-space:nowrap}
fieldset .hint{font-size:11px;color:var(--dim);opacity:.75;margin-top:8px}
.row .err{flex-basis:100%;font-size:11px;color:#ff5f56;margin-left:198px;text-shadow:none}
.bar{position:sticky;bottom:0;display:flex;gap:8px;align-items:center;padding:12px 0;background:var(--bg);max-width:640px}
#cfgmsg{font-size:12px;color:var(--dim)}
.ghost{background:none;color:var(--accent);border:1px solid var(--accent);text-shadow:none}
.ghost:hover:not(:disabled){box-shadow:0 0 12px rgba(0,255,65,.35)}
input{flex:1;padding:11px 13px;border-radius:4px;border:1px solid var(--line);background:#000;color:var(--fg);font-size:15px;font-family:inherit;caret-color:var(--accent);text-shadow:var(--glow)}
input::placeholder{color:#0a7a22;text-shadow:none}
input:focus{outline:none;border-color:var(--accent);box-shadow:0 0 10px rgba(0,255,65,.25)}
button{padding:11px 18px;border-radius:4px;border:1px solid var(--accent);background:var(--accent);color:#000;font-weight:700;cursor:pointer;font-family:inherit;letter-spacing:.1em;text-transform:uppercase;text-shadow:none}
button:hover:not(:disabled){box-shadow:0 0 14px rgba(0,255,65,.45)}
button:disabled{opacity:.4;cursor:default}
</style></head><body>
<header>ESP32-S3 Agent <small id="st">ready</small>
<span id="nav"><button class="tab on" id="tchat">Chat</button><button class="tab" id="tcfg">Config</button></span></header>
<div id="log"></div>
<div id="cfg"></div>
<form id="f" class="chat"><input id="i" placeholder="Ask the board something..." autocomplete="off"><button id="b">Send</button></form>
<script>
const log=document.getElementById('log'),inp=document.getElementById('i'),btn=document.getElementById('b'),st=document.getElementById('st');

function esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}

// Inline spans. Code first, so **bold** inside `code` stays literal.
function inl(s){
  const c=[];
  s=s.replace(/`([^`]+)`/g,(m,t)=>{c.push(t);return '\x00C'+(c.length-1)+'\x00'});
  s=s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g,'<a href="$2" target="_blank" rel="noopener">$1</a>')
     // Emphasis may not open or close on whitespace, so arithmetic like
     // "2 * 3 * 4" is not mistaken for italics.
     .replace(/\*\*([^\s*](?:[^*]*[^\s*])?)\*\*/g,'<strong>$1</strong>')
     .replace(/(^|[^*])\*([^\s*](?:[^*]*[^\s*])?)\*/g,'$1<em>$2</em>');
  return s.replace(/\x00C(\d+)\x00/g,(m,i)=>'<code>'+c[+i]+'</code>')
}

function md(src){
  const fence=[];
  src=src.replace(/```[^\n]*\n?([\s\S]*?)```/g,(m,t)=>{fence.push(t.replace(/\n$/,''));return '\x00F'+(fence.length-1)+'\x00'});
  const L=esc(src).split('\n'),o=[];
  let list=null,tbl=0,para=[];
  const flushP=()=>{if(para.length){o.push('<p>'+inl(para.join(' '))+'</p>');para=[]}};
  const endL=()=>{if(list){flushP();o.push('</'+list+'>');list=null}};
  const endT=()=>{if(tbl){o.push('</tbody></table></div>');tbl=0}};
  const close=()=>{flushP();endL();endT()};

  for(let ln of L){
    let m;
    if(m=ln.match(/^\x00F(\d+)\x00\s*$/)){close();o.push('<pre><code>'+esc(fence[+m[1]])+'</code></pre>');continue}
    if(!ln.trim()){flushP();endL();endT();continue}

    if(/^\s*\|.*\|\s*$/.test(ln)){
      const raw=ln.trim().replace(/^\||\|$/g,'');
      if(tbl===1&&/^[\s|:-]+$/.test(raw)){o.push('</thead><tbody>');tbl=2;continue}
      const cells=raw.split('|').map(x=>x.trim());
      if(!tbl){flushP();endL();o.push('<div class="tw"><table><thead><tr>'+cells.map(x=>'<th>'+inl(x)+'</th>').join('')+'</tr>');tbl=1;continue}
      o.push('<tr>'+cells.map(x=>'<td>'+inl(x)+'</td>').join('')+'</tr>');continue
    }
    endT();

    if(m=ln.match(/^(#{1,6})\s+(.*)$/)){close();const n=Math.min(m[1].length,4);o.push('<h'+n+'>'+inl(m[2])+'</h'+n+'>');continue}
    if(/^\s*([-*_])\s*\1\s*\1[\s\-*_]*$/.test(ln)){close();o.push('<hr>');continue}
    // &gt; not >, because esc() has already run over the line.
    if(m=ln.match(/^\s*&gt;\s?(.*)$/)){close();o.push('<blockquote>'+inl(m[1])+'</blockquote>');continue}

    if(m=ln.match(/^\s*[-*+]\s+(.*)$/)){
      flushP();if(list!=='ul'){endL();o.push('<ul>');list='ul'}
      o.push('<li>'+inl(m[1])+'</li>');continue
    }
    if(m=ln.match(/^\s*\d+[.)]\s+(.*)$/)){
      flushP();if(list!=='ol'){endL();o.push('<ol>');list='ol'}
      o.push('<li>'+inl(m[1])+'</li>');continue
    }
    endL();para.push(ln.trim())
  }
  close();
  return o.join('')
}

function add(text,cls){
  const d=document.createElement('div');
  d.className='msg '+cls;
  if(cls==='bot')d.innerHTML=md(text);else d.textContent=text;
  log.appendChild(d);log.scrollTop=log.scrollHeight;return d
}

function showMedia(url,kind){
  const wrap=document.createElement('div');
  wrap.className='shot';
  if(kind==='audio'){
    const cap=document.createElement('div');
    cap.className='cap'; cap.textContent='recording';
    wrap.appendChild(cap);
  }
  const el=document.createElement(kind==='audio'?'audio':'img');
  el.src=url;
  if(kind==='audio'){el.controls=true;el.preload='auto';el.setAttribute('type','audio/wav')}
  else{el.alt='photo from the board';
       // Scroll again once it lands: the image has no height until then.
       el.onload=()=>{log.scrollTop=log.scrollHeight}}
  el.onerror=()=>{wrap.textContent='('+kind+' could not be loaded)'};
  const a=document.createElement('a');
  a.href=url; a.target='_blank'; a.rel='noopener';
  a.textContent=kind==='audio'?'download wav':'open full size';
  wrap.appendChild(el); wrap.appendChild(a);
  log.appendChild(wrap); log.scrollTop=log.scrollHeight;
}

document.getElementById('f').onsubmit=async e=>{
  e.preventDefault();const q=inp.value.trim();if(!q)return;
  inp.value='';add(q,'user');btn.disabled=true;st.textContent='thinking...';
  try{
    const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:q})});
    const j=await r.json();
    (j.events||[]).forEach(t=>add('- '+t,'tool'));
    add(j.reply||j.error||'(no reply)','bot');
    if(j.photo)showMedia(j.photo,'img');
    if(j.audio)showMedia(j.audio,'audio');
  }catch(err){add('Request failed: '+err,'bot')}
  btn.disabled=false;st.textContent='ready';inp.focus();
};
inp.focus();

/* ---------------- config screen ---------------- */
const cfgEl=document.getElementById('cfg'),tChat=document.getElementById('tchat'),tCfg=document.getElementById('tcfg'),frm=document.getElementById('f');
let fields=[];

function show(which){
  const isCfg=which==='cfg';
  cfgEl.classList.toggle('on',isCfg);
  log.classList.toggle('off',isCfg);
  frm.classList.toggle('off',isCfg);
  tCfg.classList.toggle('on',isCfg);
  tChat.classList.toggle('on',!isCfg);
  if(isCfg)loadCfg(); else inp.focus();
}
tChat.onclick=()=>show('chat');
tCfg.onclick=()=>show('cfg');

function field(f){
  const id='f_'+f.key;
  let ctl;
  if(f.type==='bool'){
    ctl='<input type="checkbox" id="'+id+'"'+(f.value?' checked':'')+'>';
  }else if(f.type==='select'){
    ctl='<select id="'+id+'" class="in">'+f.options.map(o=>'<option'+(o===f.value?' selected':'')+'>'+esc(o)+'</option>').join('')+'</select>';
  }else if(f.type==='textarea'){
    ctl='<textarea id="'+id+'" class="in">'+esc(f.value==null?'':String(f.value))+'</textarea>';
  }else if(f.type==='secret'){
    ctl='<input type="password" id="'+id+'" class="in" placeholder="'+(f.isSet?'•••• stored — leave blank to keep':'not set')+'" autocomplete="new-password">';
  }else if(f.type==='int'||f.type==='float'){
    ctl='<input type="number" id="'+id+'" class="in" value="'+(f.value==null?'':f.value)+'"'+
        (f.min!=null?' min="'+f.min+'"':'')+(f.max!=null?' max="'+f.max+'"':'')+
        (f.type==='float'?' step="0.1"':'')+'>';
  }else{
    ctl='<input type="text" id="'+id+'" class="in" value="'+esc(f.value==null?'':String(f.value)).replace(/"/g,'&quot;')+'">';
  }
  return '<div class="row" data-k="'+f.key+'"><label for="'+id+'">'+esc(f.label)+'</label>'+ctl+
         (f.restart?'<div class="hint">requires restart</div>':'')+'</div>';
}

async function loadCfg(){
  cfgEl.innerHTML='<p style="color:var(--dim)">loading...</p>';
  try{
    const r=await fetch('/api/config'),j=await r.json();
    fields=j.fields;
    const groups=[];
    fields.forEach(f=>{if(!groups.includes(f.group))groups.push(f.group)});
    let ro='';
    if(j.extras&&j.extras.length){
      ro='<fieldset><legend>Read-only</legend>'+j.extras.map(e=>
        '<div class="row"><label>'+esc(e.key)+'</label>'+
        '<div class="in ro">'+esc(String(e.value))+'</div></div>').join('')+
        '<div class="hint" style="margin-left:0">Change these by editing config.json and running tools/deploy.sh --config</div></fieldset>';
    }
    cfgEl.innerHTML=groups.map(g=>'<fieldset><legend>'+esc(g)+'</legend>'+
        fields.filter(f=>f.group===g).map(field).join('')+'</fieldset>').join('')+ro+
      '<div class="bar"><button id="save">Save</button>'+
      '<button id="reboot" class="ghost">Restart board</button>'+
      '<span id="cfgmsg"></span></div>';
    document.getElementById('save').onclick=saveCfg;
    document.getElementById('reboot').onclick=reboot;
  }catch(e){cfgEl.innerHTML='<p>could not load config: '+esc(String(e))+'</p>'}
}

function collect(){
  const v={};
  fields.forEach(f=>{
    const el=document.getElementById('f_'+f.key);
    if(!el)return;
    if(f.type==='bool')v[f.key]=el.checked;
    else v[f.key]=el.value;
  });
  return v;
}

async function saveCfg(){
  const msg=document.getElementById('cfgmsg'),btn=document.getElementById('save');
  cfgEl.querySelectorAll('.err').forEach(e=>e.remove());
  btn.disabled=true;msg.textContent='saving...';
  try{
    const r=await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({values:collect()})});
    const j=await r.json();
    if(j.errors){
      Object.keys(j.errors).forEach(k=>{
        const row=cfgEl.querySelector('.row[data-k="'+k+'"]');
        if(row){const d=document.createElement('div');d.className='err';d.textContent=j.errors[k];row.appendChild(d)}
      });
      msg.textContent='fix the errors above';
    }else if(j.ok){
      msg.textContent=j.message||'saved';
      if(j.changed&&j.changed.length)loadCfg().then(()=>{
        const m=document.getElementById('cfgmsg');if(m)m.textContent=j.message||'saved';
      });
    }else{
      msg.textContent=j.error||'save failed';
    }
  }catch(e){msg.textContent='save failed: '+e}
  btn.disabled=false;
}

async function reboot(){
  if(!confirm('Restart the board? The agent will be unreachable for about 20 seconds.'))return;
  const msg=document.getElementById('cfgmsg');
  msg.textContent='restarting...';
  try{await fetch('/api/restart',{method:'POST'})}catch(e){}
  setTimeout(()=>{msg.textContent='reconnecting...';location.reload()},22000);
}
</script></body></html>"""


class WebServer:
    def __init__(self, agent, port=80, on_config_change=None):
        self.agent = agent
        # on_config_change(cfg) lets main.py rebuild the LLM and tool clients
        # so edits apply without a reboot wherever that is possible.
        self.on_config_change = on_config_change
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("0.0.0.0", port))
        self.sock.listen(2)
        self.sock.setblocking(False)

    def fileno(self):
        return self.sock.fileno()

    def _respond(self, conn, status, ctype, body):
        if isinstance(body, str):
            body = body.encode("utf-8")
        head = ("HTTP/1.1 %s\r\nContent-Type: %s\r\nContent-Length: %d\r\n"
                "Connection: close\r\n\r\n" % (status, ctype, len(body)))
        conn.write(head.encode())
        view = memoryview(body)
        for i in range(0, len(view), 1024):
            conn.write(view[i:i + 1024])

    def _serve_media(self, conn, path, prefix, dir_key, dir_default, ctype):
        """Stream a saved photo or recording.

        These files are hundreds of KB to megabytes, so they are streamed in
        chunks rather than read into memory.
        """
        name = path[len(prefix):]
        # Drop the cache-busting query string before touching the filesystem.
        if "?" in name:
            name = name.split("?", 1)[0]
        if not name or "/" in name or ".." in name:
            self._respond(conn, "400 Bad Request", "text/plain", "bad name")
            return
        full = self.agent.cfg.get(dir_key, dir_default).rstrip("/") + "/" + name
        try:
            size = os.stat(full)[6]
        except OSError:
            self._respond(conn, "404 Not Found", "text/plain", "no such photo")
            return

        # no-store because the default filename is reused by every capture.
        conn.write(("HTTP/1.1 200 OK\r\nContent-Type: %s\r\nContent-Length: %d\r\n"
                    "Cache-Control: no-store\r\nConnection: close\r\n\r\n"
                    % (ctype, size)).encode())
        with open(full, "rb") as f:
            while True:
                chunk = f.read(1024)
                if not chunk:
                    break
                conn.write(chunk)

    def _save_config(self, raw):
        try:
            values = json.loads(raw).get("values") or {}
        except Exception as exc:
            return {"ok": False, "error": "bad request: %s" % exc}

        cfg = self.agent.cfg
        changed, errors, needs_restart = _settings.apply(cfg, values)
        if errors:
            return {"ok": False, "errors": errors}

        if not changed:
            return {"ok": True, "changed": [], "message": "No changes."}

        try:
            _config.save(cfg)
        except Exception as exc:
            return {"ok": False, "error": "could not write /config.json: %s" % exc}

        applied_live = False
        if self.on_config_change:
            try:
                self.on_config_change(cfg)
                applied_live = True
            except Exception as exc:
                print("[web] config reload failed: %s" % exc)

        # Secrets are echoed back as names only, never values.
        print("[web] config updated: %s" % ", ".join(changed))

        pending = [k for k in changed if k in _settings.RESTART_REQUIRED]
        live = [k for k in changed if k not in _settings.RESTART_REQUIRED]

        # A mixed batch really does apply its live half immediately, so report
        # the two halves separately rather than calling the whole save pending.
        if pending and live and applied_live:
            message = ("Saved. Applied now: %s. Restart required for: %s."
                       % (", ".join(live), ", ".join(pending)))
        elif pending:
            message = "Saved. Restart required for: %s." % ", ".join(pending)
        elif applied_live:
            message = "Saved and applied."
        else:
            message = "Saved. Restart to apply."

        return {
            "ok": True,
            "changed": changed,
            "restart_required": bool(pending),
            "applied_live": applied_live and bool(live),
            "message": message,
        }

    def poll_once(self):
        """Accept and serve one pending connection, if any."""
        try:
            conn, addr = self.sock.accept()
        except OSError:
            return False

        conn.settimeout(15)
        try:
            request_line = conn.readline() or b""
            parts = request_line.split()
            method = parts[0].decode() if parts else ""
            path = parts[1].decode() if len(parts) > 1 else "/"

            length = 0
            while True:
                line = conn.readline()
                if not line or line in (b"\r\n", b"\n"):
                    break
                low = line.lower()
                if low.startswith(b"content-length:"):
                    length = int(line.split(b":", 1)[1].strip())

            if method == "POST" and path == "/api/chat":
                raw = conn.read(length) if length else b"{}"
                try:
                    message = json.loads(raw).get("message", "")
                except Exception:
                    message = ""

                events = []
                self.agent.on_event = lambda kind, text: events.append("%s: %s" % (kind, text))
                self.agent.registry.last_photo = None
                self.agent.registry.last_audio = None
                try:
                    reply = self.agent.ask(message) if message else "Empty message."
                finally:
                    self.agent.on_event = None

                payload = {"reply": reply, "events": events}
                # Set by take_photo, so the chat can show the image inline
                # without depending on the model formatting a markdown link.
                if self.agent.registry.last_photo:
                    payload["photo"] = self.agent.registry.last_photo
                if self.agent.registry.last_audio:
                    payload["audio"] = self.agent.registry.last_audio
                self._respond(conn, "200 OK", "application/json", json.dumps(payload))
            elif method == "GET" and path == "/api/config":
                self._respond(conn, "200 OK", "application/json", json.dumps(
                    {"fields": _settings.describe(self.agent.cfg),
                     "extras": _settings.extras(self.agent.cfg)}))
            elif method == "POST" and path == "/api/config":
                raw = conn.read(length) if length else b"{}"
                self._respond(conn, "200 OK", "application/json",
                              json.dumps(self._save_config(raw)))
            elif method == "POST" and path == "/api/restart":
                self._respond(conn, "200 OK", "application/json",
                              json.dumps({"ok": True}))
                try:
                    conn.close()
                except Exception:
                    pass
                import machine
                import time as _t
                _t.sleep(1)          # let the response drain first
                machine.reset()
            elif method == "GET" and path.startswith("/photos/"):
                self._serve_media(conn, path, "/photos/", "photo_dir",
                                  "/photos", "image/bmp")
            elif method == "GET" and path.startswith("/audio/"):
                self._serve_media(conn, path, "/audio/", "audio_dir",
                                  "/audio", "audio/wav")
            elif path in ("/", "/index.html"):
                self._respond(conn, "200 OK", "text/html; charset=utf-8", PAGE)
            else:
                self._respond(conn, "404 Not Found", "text/plain", "not found")
        except Exception as exc:
            print("[web] error serving request: %s" % exc)
        finally:
            try:
                conn.close()
            except Exception:
                pass
            gc.collect()
        return True
