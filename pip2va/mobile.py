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

# ---- 30-minute trend history (sampled every 3 s in-process)
import collections
import threading
import time as _time

TREND_N = 1800
_trends = {k: collections.deque(maxlen=TREND_N)
           for k in ("t", "w", "i", "loss")}


def _sampler():
    while True:
        try:
            st = {k.decode(): v.decode()
                  for k, v in R.hgetall("state:beam").items()}
            e = R.xrevrange(keys.stream("blm.losses"), count=3)
            worst = 0.0
            if e:
                worst = float(np.max(np.mean(
                    [codec.unpack(f[b"d"])[1]["wpm"] for _, f in e],
                    axis=0)))
            _trends["t"].append(round(100 * float(
                st.get("transmission", 0)), 3))
            _trends["w"].append(round(float(st.get("w_out", 0)), 2))
            _trends["i"].append(round(float(st.get("i_out_ma", 0)), 4))
            _trends["loss"].append(round(worst, 2))
        except Exception:
            pass
        try:
            _persist_finished()
        except Exception:
            pass
        _time.sleep(1.0)


def _persist_finished():
    """Save any finished study that nobody else persisted (mobile- or
    script-started runs): result file + knowledge-base entry, deduped
    machine-wide via a redis marker."""
    st = {k.decode(): v.decode() for k, v in R.hgetall("state:study").items()}
    if st.get("run") == "1" or not st.get("result"):
        return
    import hashlib
    mark = hashlib.md5(st["result"].encode()).hexdigest()
    if R.get("state:study.persisted") == mark.encode():
        return
    from pathlib import Path
    d = Path.home() / ".pip2va" / "studies"
    if not d.exists():
        return
    plan = json.loads(st.get("plan", "{}"))
    result = json.loads(st["result"])
    ts = _time.strftime("%Y%m%d-%H%M%S")
    name = plan.get("name", "study")
    # skip if a GUI/script already wrote a file for this run just now
    recent = sorted(d.glob(f"result-{name}-*.json"))
    if not (recent and _time.time() - recent[-1].stat().st_mtime < 90):
        (d / f"result-{name}-{ts}.json").write_text(
            json.dumps({"plan": plan, "result": result}, indent=1))
        from pip2va.analysis import knowledge
        knowledge.append(knowledge.summarize_result(plan, result))
    R.set("state:study.persisted", mark)


threading.Thread(target=_sampler, daemon=True).start()

PAGE = """<!doctype html><html><head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PIP-II VA</title><style>
body{background:#0d1117;color:#e6edf3;font-family:-apple-system,Segoe UI,
Roboto,sans-serif;margin:0;padding:12px}
.grid{display:grid;grid-template-columns:1fr;gap:10px}
.card{background:#161b22;border-radius:12px;padding:12px;text-align:center}
.card .v{font-size:26px;font-weight:700}.card .l{font-size:12px;color:#8b96a5}
.ok{color:#2ecc71}.bad{color:#e74c3c}
#permit{font-size:20px;font-weight:800;padding:14px}
#events{background:#161b22;border-radius:12px;padding:10px;margin-top:10px;
font-size:12px;color:#9fb0c3;white-space:pre-wrap}
#ask{width:100%;box-sizing:border-box;padding:12px;border-radius:10px;
border:1px solid #30363d;background:#0d1117;color:#e6edf3;font-size:16px;
margin-top:12px}
#ans{background:#161b22;border-radius:12px;padding:12px;margin-top:8px;
font-size:14px;display:none;line-height:1.45}
.rng{flex:1;padding:9px 0;border-radius:8px;border:0;font-size:13px;
font-weight:600;background:#21262d;color:#8b96a5}
.rng.on{background:#1f6feb;color:#fff}
button{width:100%;padding:12px;margin-top:8px;border-radius:10px;border:0;
background:#1f6feb;color:#fff;font-size:16px;font-weight:600}
button:active,.rng:active{transform:scale(.96);filter:brightness(1.35)}
.tapped{background:#2ea043!important}
button:disabled{opacity:.55}
a{color:#4fc3f7}</style></head><body>
<div class="grid">
<div class="card" id="permit">…</div>
<div class="card"><div class="v" id="w">…</div><div class="l">MeV</div></div>
<div class="card"><div class="v" id="t">…</div><div class="l">transmission</div></div>
<div class="card"><div class="v" id="i">…</div><div class="l">mA delivered</div></div>
<div class="card"><div class="v" id="loss">…</div><div class="l" id="lossat">worst BLM</div></div>
</div>
<div style="display:flex;gap:6px;margin-top:10px">
<button id="w30m" class="rng on" onclick="tap(this);setRange(1800,this)">30 min</button>
<button id="w5m" class="rng" onclick="tap(this);setRange(300,this)">5 min</button>
<button id="w30s" class="rng" onclick="tap(this);setRange(30,this)">30 s</button>
</div>
<div class="grid" style="margin-top:8px">
<div class="card"><canvas id="ct" width="360" height="84"></canvas>
<div class="l" id="lt">transmission %</div></div>
<div class="card"><canvas id="cl" width="360" height="84"></canvas>
<div class="l">worst BLM W/m</div></div>
<div class="card"><canvas id="cw" width="360" height="84"></canvas>
<div class="l">energy MeV</div></div>
<div class="card"><canvas id="ci" width="360" height="84"></canvas>
<div class="l">delivered mA</div></div>
</div>
<div id="events">…</div>
<div class="card" style="margin-top:10px;text-align:left">
<b>Studies</b> <a href="/studies" style="float:right">manage →</a>
<div id="study_run" style="font-size:14px;margin-top:6px">—</div>
<div id="study_q" class="l" style="white-space:pre-wrap">—</div>
</div>
<input id="ask" placeholder="Ask the machine…" autocomplete="off">
<button id="askbtn" onclick="tap(this);ask()">Ask</button>
<div id="ans"></div>
<p style="text-align:center"><a href="/studies">beam studies →</a>
&nbsp;&nbsp;<a href="/room">full control room →</a></p>
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
function spark(id,data,color){const c=document.getElementById(id),
 x=c.getContext('2d');x.clearRect(0,0,c.width,c.height);
 if(!data||data.length<2)return;
 const lo=Math.min(...data),hi=Math.max(...data),span=(hi-lo)||1e-9;
 x.strokeStyle=color;x.lineWidth=1.6;x.beginPath();
 data.forEach((v,k)=>{const px=k/(data.length-1)*(c.width-4)+2,
  py=c.height-6-(v-lo)/span*(c.height-24);
  k?x.lineTo(px,py):x.moveTo(px,py)});
 x.stroke();
 x.fillStyle='#8b96a5';x.font='10px sans-serif';
 x.fillText(hi.toPrecision(4),4,10);
 x.fillText(lo.toPrecision(4),4,c.height-1);
 x.fillStyle=color;x.font='bold 13px sans-serif';
 const last=data[data.length-1];
 x.fillText(last.toPrecision(4),c.width-56,12);}
let rangeN=1800;
function setRange(n,btn){rangeN=n;
 document.querySelectorAll('.rng').forEach(b=>b.className='rng');
 btn.className='rng on';trends();}
async function trends(){try{
 const d=await (await fetch('/api/trends')).json();
 const cut=a=>a.slice(-rangeN);
 spark('ct',cut(d.t),'#2ecc71');spark('cl',cut(d.loss),'#ff7043');
 spark('cw',cut(d.w),'#4fc3f7');spark('ci',cut(d.i),'#ffd54f');
}catch(e){}}
setInterval(trends,2000);trends();
async function studies(){try{
 const d=await (await fetch('/api/studies')).json();
 study_run.innerHTML=d.running?
  '<span class="ok">&#9654; '+d.running.name+'</span> — '+d.running.status+
  ' (step '+d.running.step+'/'+d.running.total+')':
  '<span style="color:#8b96a5">no study running</span>';
 study_q.textContent=d.queue.length?
  ('queued:\\n'+d.queue.map((q,i)=>('  '+(i+1)+'. '+q)).join('\\n')):
  'queue empty';
}catch(e){study_run.textContent='studies api error';}}
setInterval(studies,4000);studies();
function tap(b){b.classList.add('tapped');
 setTimeout(()=>b.classList.remove('tapped'),350);}
async function ask(){const q=document.getElementById('ask').value;if(!q)return;
 askbtn.disabled=true;askbtn.textContent='Asking…';
 ans.style.display='block';ans.textContent='thinking…';
 const r=await fetch('/api/ask',{method:'POST',
  headers:{'Content-Type':'application/json'},body:JSON.stringify({q})});
 ans.textContent=(await r.json()).answer;
 askbtn.disabled=false;askbtn.textContent='Ask';}
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
#bar button:active{transform:scale(.94);filter:brightness(1.5)}
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


STUDIES = """<!doctype html><html><head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Beam studies</title><style>
body{background:#0d1117;color:#e6edf3;font-family:-apple-system,Segoe UI,
Roboto,sans-serif;margin:0;padding:12px}
.card{background:#161b22;border-radius:12px;padding:12px;margin-top:10px}
.l{font-size:12px;color:#8b96a5}.ok{color:#2ecc71}.bad{color:#e74c3c}
input,textarea{width:100%;box-sizing:border-box;padding:11px;
border-radius:10px;border:1px solid #30363d;background:#0d1117;
color:#e6edf3;font-size:15px}
button{padding:10px 14px;border-radius:10px;border:0;background:#1f6feb;
color:#fff;font-size:14px;font-weight:600;margin-top:6px}
button:active,.chip:active{transform:scale(.96);filter:brightness(1.4)}
.tapped{background:#2ea043!important}
button:disabled{opacity:.55}
.item:active{background:#21262d}
button.gray{background:#21262d;color:#9fb0c3}
button.red{background:#8b1e1e}
.chip{display:inline-block;background:#21262d;color:#c8d2de;border-radius:14px;
padding:7px 11px;margin:3px 3px 0 0;font-size:12px}
.item{padding:8px 4px;border-bottom:1px solid #21262d;font-size:14px}
pre{white-space:pre-wrap;font-size:12px;color:#c8d2de}
a{color:#4fc3f7}</style></head><body>
<a href="/">← status</a>
<div class="card"><b>Now running</b><div id="run" class="l">—</div>
<button class="red" onclick="tap(this);this.textContent='Aborting…';post('/api/abort').then(r=>{this.textContent='Abort + restore';msg(r);load()})">Abort + restore</button></div>
<div class="card"><b>Plan with AI</b>
<textarea id="nl" rows="2" placeholder="e.g. sweep SSR1:CAV11 phase ±5°, 9 steps, restore after"></textarea>
<button id="planbtn" onclick="tap(this);plan()">Plan</button>
<div id="plansum" class="l"></div>
<button id="qbtn" style="display:none" onclick="tap(this);queuePlan()">Queue this study</button></div>
<div class="card"><b>Presets</b> <span class="l">(tap to queue)</span>
<div id="presets"></div></div>
<div class="card"><b>Queue</b><div id="queue" class="l">—</div>
<button onclick="tap(this);post('/api/run_next').then(r=>{msg(r);load()})">Run next</button></div>
<div class="card"><b>Recent results</b><div id="results"></div>
<pre id="report"></pre>
<button id="aibtn" style="display:none" class="gray" onclick="tap(this);this.textContent='Analyzing…';analyze().then(()=>this.textContent='AI analysis')">AI analysis</button></div>
<div id="msg" class="l" style="margin-top:8px"></div>
<script>
let planObj=null,curStem=null;
function tap(b){b.classList.add('tapped');
 setTimeout(()=>b.classList.remove('tapped'),350);}
const post=(u,b)=>fetch(u,{method:'POST',headers:{'Content-Type':
 'application/json'},body:JSON.stringify(b||{})}).then(r=>r.json());
function msg(r){document.getElementById('msg').textContent=
 r.error?('✗ '+r.error):('✓ '+(r.queued||r.started||'ok'));}
async function load(){
 const d=await (await fetch('/api/studies')).json();
 run.innerHTML=d.running?`<b>${d.running.name}</b> — ${d.running.status}
  (step ${d.running.step}/${d.running.total})`:'idle';
 queue.textContent=d.queue.length?d.queue.join('\n'):'(empty)';
 presets.innerHTML=d.presets.map(p=>
  `<span class="chip" title="${p.teaches}"
    onclick="tap(this);post('/api/queue',{preset:'${p.name}'}).then(r=>{msg(r);load()})">${p.name}</span>`).join('');
 results.innerHTML=d.results.map(r=>
  `<div class="item" onclick="show('${r}')">${r}</div>`).join('');
}
async function plan(){
 planbtn.disabled=true;planbtn.textContent='Planning…';
 plansum.textContent='planning…';
 const r=await post('/api/plan',{text:document.getElementById('nl').value});
 planbtn.disabled=false;planbtn.textContent='Plan';
 if(r.error){plansum.textContent='✗ '+r.error;return;}
 planObj=r.plan;plansum.textContent=r.summary+'  ['+r.note+']';
 qbtn.style.display='inline-block';}
async function queuePlan(){msg(await post('/api/queue',{plan:planObj}));
 qbtn.style.display='none';load();}
async function show(stem){curStem=stem;report.textContent='loading…';
 aibtn.style.display='inline-block';
 const r=await (await fetch('/api/result/'+stem)).json();
 report.textContent=r.report||r.error;}
async function analyze(){report.textContent='AI analyzing… (30-60 s)';
 const r=await post('/api/analyze/'+curStem);
 report.textContent=r.report||r.error;}

setInterval(load,4000);load();
</script></body></html>"""


@app.get("/studies")
def studies_page():
    return STUDIES


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


@app.get("/api/trends")
def trends():
    return jsonify({k: list(v) for k, v in _trends.items()})


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


# ---------------------------------------------------------------- studies

import glob as _glob
from pathlib import Path as _Path

STUDY_DIR = _Path.home() / ".pip2va" / "studies"
QUEUE_KEY = "state:study.queue"


@app.get("/api/studies")
def api_studies():
    st = {k.decode(): v.decode() for k, v in R.hgetall("state:study").items()}
    running = None
    if st.get("run") == "1":
        try:
            nm = json.loads(st.get("plan", "{}")).get("name", "?")
        except ValueError:
            nm = "?"
        running = {"name": nm, "status": st.get("status", ""),
                   "step": st.get("step", "0"), "total": st.get("total", "?")}
    queue = []
    for raw in R.lrange(QUEUE_KEY, 0, -1):
        try:
            pl = json.loads(raw)
            queue.append(f"{pl['name']} ({pl['steps']}x{pl['dwell_s']}s)")
        except ValueError:
            queue.append("?")
    results = sorted((f.stem.replace("result-", "") for f in
                      STUDY_DIR.glob("result-*.json")), reverse=True)[:15]
    from pip2va.analysis.study_presets import PRESETS
    return jsonify({"running": running, "queue": queue, "results": results,
                    "presets": [{"name": k, "teaches": v["teaches"]}
                                for k, v in PRESETS.items()]})


@app.post("/api/plan")
def api_plan():
    text = (request.get_json(silent=True) or {}).get("text", "").strip()
    from pip2va.analysis import studies as _st
    try:
        plan, note = _st.plan_from_text(text)
    except Exception as e:
        return jsonify({"error": str(e)})
    sw = plan["sweeps"][0]
    summary = (f"{plan['name']}: {plan['kind']} "
               f"{sw['device']}:{sw['field']} {sw['from']}..{sw['to']} "
               f"in {plan['steps']} steps x {plan['dwell_s']}s"
               + (f" (+{len(plan['sweeps'])-1} more knobs)"
                  if len(plan["sweeps"]) > 1 else ""))
    return jsonify({"plan": plan, "summary": summary, "note": note})


@app.post("/api/queue")
def api_queue():
    body = request.get_json(silent=True) or {}
    plan = body.get("plan")
    preset = body.get("preset")
    from pip2va.analysis import studies as _st
    if preset:
        from pip2va.analysis import study_presets
        plan = study_presets.get_plan(preset)
    if not plan:
        return jsonify({"error": "no plan"})
    try:
        plan, _ = _st.validate_plan(plan)
    except Exception as e:
        return jsonify({"error": str(e)})
    R.rpush(QUEUE_KEY, json.dumps(plan))
    return jsonify({"ok": True, "queued": plan["name"]})


@app.post("/api/run_next")
def api_run_next():
    if R.hget("state:study", "run") == b"1":
        return jsonify({"error": "a study is already running"})
    raw = R.lpop(QUEUE_KEY)
    if raw is None:
        return jsonify({"error": "queue empty"})
    plan = json.loads(raw)
    R.hset("state:study", mapping={
        "plan": json.dumps(plan), "run": 1, "status": "starting",
        "step": 0, "total": plan["steps"], "result": ""})
    return jsonify({"ok": True, "started": plan["name"]})


@app.post("/api/abort")
def api_abort():
    R.hset("state:study", "run", 0)
    R.hset(keys.settings("autotune", "main"), "restore", 1)
    return jsonify({"ok": True})


@app.get("/api/result/<stem>")
def api_result(stem):
    f = STUDY_DIR / f"result-{stem}.json"
    if not f.exists():
        return jsonify({"error": "not found"})
    d = json.loads(f.read_text())
    from pip2va.analysis import studies as _st
    try:
        rep = _st.rule_report(d["plan"], d["result"])
    except Exception as e:
        rep = f"report error: {e}"
    return jsonify({"report": rep})


@app.post("/api/analyze/<stem>")
def api_analyze(stem):
    f = STUDY_DIR / f"result-{stem}.json"
    if not f.exists():
        return jsonify({"error": "not found"})
    d = json.loads(f.read_text())
    from pip2va.analysis import studies as _st
    try:
        text, engine = _st.llm_report(d["plan"], d["result"])
        return jsonify({"report": f"[{engine}]\n{text}"})
    except Exception as e:
        return jsonify({"error": str(e)})


def main():
    app.run(host="0.0.0.0", port=6081)


if __name__ == "__main__":
    main()
