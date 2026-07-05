"""Phone-friendly machine dashboard: big-number status cards, recent
events, and ask-the-machine — served tiny and fast for mobile browsers.

Run: python -m pip2va.mobile  (port 6081; PIP2VA_REDIS_URL for redis).
The full desktop GUI stream stays on :6080 (noVNC); this page is the
glanceable companion.
"""
from __future__ import annotations

import json
import os

import numpy as np
import redis
from flask import Flask, jsonify, request

from pip2va.common import codec, keys

app = Flask(__name__)
R = redis.Redis.from_url(
    os.environ.get("PIP2VA_REDIS_URL", "redis://localhost:6379/0"))

PAGE = """<!doctype html><html><head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PIP-II VA</title><style>
body{background:#0d1117;color:#e6edf3;font-family:-apple-system,Segoe UI,
Roboto,sans-serif;margin:0;padding:12px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.card{background:#161b22;border-radius:12px;padding:12px;text-align:center}
.card .v{font-size:26px;font-weight:700}.card .l{font-size:12px;color:#8b96a5}
.ok{color:#2ecc71}.bad{color:#e74c3c}
#permit{grid-column:1/3;font-size:20px;font-weight:800;padding:14px}
#events{background:#161b22;border-radius:12px;padding:10px;margin-top:10px;
font-size:12px;color:#9fb0c3;white-space:pre-wrap}
#ask{width:100%;box-sizing:border-box;padding:12px;border-radius:10px;
border:1px solid #30363d;background:#0d1117;color:#e6edf3;font-size:16px;
margin-top:12px}
#ans{background:#161b22;border-radius:12px;padding:12px;margin-top:8px;
font-size:14px;display:none;line-height:1.45}
button{width:100%;padding:12px;margin-top:8px;border-radius:10px;border:0;
background:#1f6feb;color:#fff;font-size:16px;font-weight:600}
a{color:#4fc3f7}</style></head><body>
<div class="grid">
<div class="card" id="permit">…</div>
<div class="card"><div class="v" id="w">…</div><div class="l">MeV</div></div>
<div class="card"><div class="v" id="t">…</div><div class="l">transmission</div></div>
<div class="card"><div class="v" id="i">…</div><div class="l">mA delivered</div></div>
<div class="card"><div class="v" id="loss">…</div><div class="l" id="lossat">worst BLM</div></div>
</div>
<div id="events">…</div>
<input id="ask" placeholder="Ask the machine…" autocomplete="off">
<button onclick="ask()">Ask</button>
<div id="ans"></div>
<p style="text-align:center"><a href="/room">open full control room →</a></p>
<script>
async function tick(){try{
 const s=await (await fetch('/api/status')).json();
 permit.innerHTML=s.permit?'BEAM PERMIT: ENABLED':'BEAM PERMIT: INHIBITED';
 permit.className='card '+(s.permit?'ok':'bad');
 w.textContent=s.w.toFixed(1); t.textContent=(100*s.t).toFixed(2)+'%';
 i.textContent=s.i.toFixed(3); loss.textContent=s.worst.toFixed(1)+' W/m';
 lossat.textContent=s.worst_at;
 loss.className='v '+(s.worst<s.warn?'ok':'bad');
 events.textContent=s.events.join('\\n');
}catch(e){permit.textContent='link lost';permit.className='card bad'}}
setInterval(tick,2000);tick();
async function ask(){const q=document.getElementById('ask').value;if(!q)return;
 ans.style.display='block';ans.textContent='thinking…';
 const r=await fetch('/api/ask',{method:'POST',
  headers:{'Content-Type':'application/json'},body:JSON.stringify({q})});
 ans.textContent=(await r.json()).answer;}
</script></body></html>"""


@app.get("/")
def index():
    return PAGE


ROOM = """<!doctype html><html><head>
<meta name="viewport"
 content="width=device-width, initial-scale=1, user-scalable=no">
<title>PIP-II control room</title><style>
html,body{margin:0;height:100%;background:#000;overflow:hidden;
font-family:-apple-system,Segoe UI,Roboto,sans-serif}
#bar{position:fixed;top:0;left:0;right:0;z-index:10;display:flex;gap:6px;
padding:6px;background:#0d1117cc;backdrop-filter:blur(6px)}
#bar button,#bar a{flex:1;padding:10px 0;border-radius:8px;border:0;
font-size:14px;font-weight:600;text-align:center;text-decoration:none}
.on{background:#1f6feb;color:#fff}.off{background:#21262d;color:#8b96a5}
#wrap{position:absolute;top:46px;left:0;right:0;bottom:0;overflow:hidden}
#frame{width:1920px;height:1080px;border:0;transform-origin:0 0;
position:absolute;left:0;top:0}
#pad{position:absolute;inset:0;z-index:5;display:none;touch-action:none}
</style></head><body>
<div id="bar">
 <button id="bi" class="on" onclick="mode(1)">Interact</button>
 <button id="bp" class="off" onclick="mode(0)">Pan/Zoom</button>
 <button class="off" onclick="zoom(1.25)">+</button>
 <button class="off" onclick="zoom(0.8)">&minus;</button>
 <button class="off" onclick="fit()">Fit</button>
 <a class="off" href="/">&larr; status</a>
</div>
<div id="wrap"><iframe id="frame"></iframe><div id="pad"></div></div>
<script>
const f=document.getElementById('frame'),pad=document.getElementById('pad'),
 wrap=document.getElementById('wrap');
f.src=location.protocol+'//'+location.hostname
 +':6080/vnc.html?autoconnect=true&resize=off';
let s=1,ox=0,oy=0;
function apply(){f.style.transform=`translate(${ox}px,${oy}px) scale(${s})`}
function fit(){s=Math.min(wrap.clientWidth/1920,wrap.clientHeight/1080);
 ox=0;oy=0;apply()}
function zoom(k){s=Math.max(0.15,Math.min(3,s*k));apply()}
function mode(interact){pad.style.display=interact?'none':'block';
 bi.className=interact?'on':'off';bp.className=interact?'off':'on'}
let touches={};
pad.addEventListener('touchstart',e=>{
 for(const t of e.changedTouches)touches[t.identifier]=[t.clientX,t.clientY];
 e.preventDefault()},{passive:false});
pad.addEventListener('touchmove',e=>{
 const ids=Object.keys(touches);
 if(e.touches.length===1&&ids.length){
  const t=e.touches[0],p=touches[t.identifier]||[t.clientX,t.clientY];
  ox+=t.clientX-p[0];oy+=t.clientY-p[1];
  touches[t.identifier]=[t.clientX,t.clientY];apply();
 }else if(e.touches.length===2){
  const a=e.touches[0],b=e.touches[1];
  const pa=touches[a.identifier]||[a.clientX,a.clientY];
  const pb=touches[b.identifier]||[b.clientX,b.clientY];
  const d0=Math.hypot(pa[0]-pb[0],pa[1]-pb[1]);
  const d1=Math.hypot(a.clientX-b.clientX,a.clientY-b.clientY);
  if(d0>0){const k=d1/d0,cx=(a.clientX+b.clientX)/2,
   cy=(a.clientY+b.clientY)/2-46;
   const ns=Math.max(0.15,Math.min(3,s*k));
   ox=cx-(cx-ox)*(ns/s);oy=cy-(cy-oy)*(ns/s);s=ns;apply();}
  touches[a.identifier]=[a.clientX,a.clientY];
  touches[b.identifier]=[b.clientX,b.clientY];
 }
 e.preventDefault()},{passive:false});
pad.addEventListener('touchend',e=>{
 for(const t of e.changedTouches)delete touches[t.identifier]},
 {passive:false});
window.addEventListener('resize',fit);setTimeout(fit,300);
</script></body></html>"""


@app.get("/room")
def room():
    return ROOM


@app.get("/api/status")
def status():
    st = {k.decode(): v.decode() for k, v in R.hgetall("state:beam").items()}
    out = {"permit": R.get("state:mps.permit") == b"1",
           "w": float(st.get("w_out", 0)),
           "t": float(st.get("transmission", 0)),
           "i": float(st.get("i_out_ma", 0)),
           "worst": 0.0, "worst_at": "worst BLM", "warn": 50.0,
           "events": []}
    e = R.xrevrange(keys.stream("blm.losses"), count=3)
    if e:
        from pip2va.common.lattice import load_lattice
        blms = load_lattice().instruments("blm")
        wpm = np.mean([codec.unpack(f[b"d"])[1]["wpm"] for _, f in e],
                      axis=0)
        j = int(np.argmax(wpm))
        out["worst"] = float(wpm[j])
        out["worst_at"] = blms[j].name
    out["events"] = [
        f.get(b"detail", b"").decode()[:70]
        for _, f in R.xrevrange(keys.stream("mps.events"), count=5)]
    return jsonify(out)


@app.post("/api/ask")
def ask():
    q = (request.get_json(silent=True) or {}).get("q", "").strip()
    if not q:
        return jsonify({"answer": "empty question"})
    try:
        from pip2va.analysis import assistant
        text, engine = assistant.ask(R, q)
        return jsonify({"answer": f"[{engine}] {text}"})
    except Exception as e:
        return jsonify({"answer": f"assistant error: {e}"})


def main():
    app.run(host="0.0.0.0", port=6081)


if __name__ == "__main__":
    main()
