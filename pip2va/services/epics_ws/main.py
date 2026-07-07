"""EPICS web gateway: the ONE endpoint for browser clients.

- PVAccess client (p4p) toward the machine's PVA server(s)
- WebSocket JSON API at /ws  (pvws-style)
- Serves the compiled Flutter web app at /

Protocol (JSON messages over the WebSocket):
  -> {"op": "subscribe", "pvs": ["PIP2:BEAM:W", ...]}
  -> {"op": "unsubscribe", "pvs": [...]}
  -> {"op": "put", "pv": "LSCL:...:sPHS", "value": -23.0}
  -> {"op": "get", "pv": "..."}
  <- {"pv": "...", "value": <number|list>, "ts": <unix>}
  <- {"op": "put-ack", "pv": "...", "ok": true}

Updates are monitor-driven, throttled to ~10 Hz per PV per client.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time

import redis as redis_lib
from pip2va.common import codec, keys
from aiohttp import WSMsgType, web

log = logging.getLogger("epics-ws")

try:
    from p4p.client.thread import Context
    HAVE_P4P = True
except ImportError:                        # pragma: no cover
    HAVE_P4P = False

WEB_DIR = os.environ.get("PIP2VA_WEBAPP_DIR", "/app/web")
PORT = int(os.environ.get("PIP2VA_WS_PORT", "8085"))
THROTTLE = 0.1


class Hub:
    """One PVA monitor per PV, fanned out to websocket subscribers."""

    def __init__(self, loop):
        self.ctx = Context("pva")
        self.loop = loop
        self.r = redis_lib.Redis.from_url(
            os.environ.get("PIP2VA_REDIS_URL", "redis://localhost:6379/0"))
        self.monitors: dict = {}
        self.values: dict = {}
        self.subs: dict[str, set] = {}          # pv -> set[ws]
        self._last_sent: dict = {}              # (pv, id(ws)) -> t

    def ensure(self, pv: str):
        if pv in self.monitors:
            return
        def cb(value, pv=pv):
            try:
                v = value.raw.value if hasattr(value, "raw") else value
            except Exception:
                v = value
            try:
                v = list(v) if hasattr(v, "__len__") and not isinstance(
                    v, (str, bytes)) else float(v)
            except (TypeError, ValueError):
                return
            self.values[pv] = v
            asyncio.run_coroutine_threadsafe(self.fanout(pv, v), self.loop)
        self.monitors[pv] = self.ctx.monitor(pv, cb, notify_disconnect=False)

    async def fanout(self, pv: str, v):
        now = time.time()
        dead = []
        for ws in self.subs.get(pv, set()):
            key = (pv, id(ws))
            if now - self._last_sent.get(key, 0) < THROTTLE:
                continue
            self._last_sent[key] = now
            try:
                await ws.send_json({"pv": pv, "value": v, "ts": now})
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.subs.get(pv, set()).discard(ws)

    def subscribe(self, ws, pvs):
        for pv in pvs:
            self.ensure(pv)
            self.subs.setdefault(pv, set()).add(ws)
            if pv in self.values:
                asyncio.ensure_future(ws.send_json(
                    {"pv": pv, "value": self.values[pv],
                     "ts": time.time()}))

    def unsubscribe_all(self, ws):
        for s in self.subs.values():
            s.discard(ws)


async def _rpc(hub, ws, m):
    """Redis-backed request/response for things that are not PVs:
    studies queue/plan/run, ask-the-machine, snapshots/rescue, KB."""
    import json as _j
    rid = m.get("id")
    method = m.get("method")
    args = m.get("args", {})
    r = hub.r

    def reply(result=None, error=None):
        asyncio.ensure_future(ws.send_json(
            {"op": "rpc-reply", "id": rid, "result": result,
             "error": error}))

    def work():
        try:
            if method == "study_state":
                st = {k.decode(): v.decode()
                      for k, v in r.hgetall("state:study").items()}
                running = None
                if st.get("run") == "1":
                    pl = _j.loads(st.get("plan", "{}"))
                    running = {"name": pl.get("name"),
                               "status": st.get("status"),
                               "step": st.get("step"),
                               "total": st.get("total")}
                queue = []
                for raw in r.lrange("state:study.queue", 0, -1):
                    pl = _j.loads(raw)
                    queue.append(f"{pl['name']} ({pl['steps']}x"
                                 f"{pl['dwell_s']}s)")
                from pip2va.analysis.study_presets import PRESETS
                return {"running": running, "queue": queue,
                        "presets": list(PRESETS)}
            if method == "plan":
                from pip2va.analysis import studies
                plan, note = studies.plan_from_text(args["text"])
                return {"plan": plan, "note": note}
            if method == "queue_preset":
                from pip2va.analysis import studies, study_presets
                plan, _ = studies.validate_plan(
                    study_presets.get_plan(args["name"]))
                r.rpush("state:study.queue", _j.dumps(plan))
                return {"queued": plan["name"]}
            if method == "queue_plan":
                from pip2va.analysis import studies
                plan, _ = studies.validate_plan(args["plan"])
                r.rpush("state:study.queue", _j.dumps(plan))
                return {"queued": plan["name"]}
            if method == "run_next":
                if r.hget("state:study", "run") == b"1":
                    return {"error": "already running"}
                raw = r.lpop("state:study.queue")
                if not raw:
                    return {"error": "queue empty"}
                plan = _j.loads(raw)
                r.hset("state:study", mapping={
                    "plan": _j.dumps(plan), "run": 1, "status": "starting",
                    "step": 0, "total": plan["steps"], "result": ""})
                return {"started": plan["name"]}
            if method == "abort":
                r.hset("state:study", "run", 0)
                r.hset("settings:autotune:main", "restore", 1)
                return {"ok": True}
            if method == "ask":
                from pip2va.analysis import assistant
                text, engine = assistant.ask(r, args["q"])
                return {"answer": text, "engine": engine}
            if method == "rescue":
                r.hset("settings:autotune:main", "restore", 1)
                return {"ok": True}
            if method == "mps_reset":
                r.hset("settings:mps:main", "reset", 1)
                return {"ok": True}
            if method == "results":
                from pathlib import Path
                d = Path.home() / ".pip2va" / "studies"
                fs = sorted((f.stem.replace("result-", "")
                             for f in d.glob("result-*.json")),
                            reverse=True)[:20]
                return {"results": fs}
            if method == "device_list":
                import json as _jj
                from pip2va.common.lattice import load_lattice
                from pip2va.common import naming
                lat = load_lattice()
                nm = naming.Namer(lat)
                cls = args.get("cls")
                out = []
                for e in lat.elements:
                    if cls == "magnet" and e.type in (
                            "quad", "solenoid", "corrector"):
                        fields = (["current_x", "current_y"]
                                  if e.type == "corrector" else ["current"])
                        for f in fields:
                            sig = {"current": "I", "current_x": "IX",
                                   "current_y": "IY"}[f]
                            out.append({
                                "name": e.name, "section": e.section,
                                "type": e.type,
                                "rb": nm.pv(e.name, "MAG", f),
                                "sp": nm.pv(e.name, "MAG", f, setting=True),
                                "official": nm.map[e.name]["component"]})
                    elif cls == "rf" and e.type in ("rfgap", "rfq"):
                        out.append({
                            "name": e.name, "section": e.section,
                            "amp_rb": nm.pv(e.name, "LLRF", "amp"),
                            "amp_sp": nm.pv(e.name, "LLRF", "amp", setting=True),
                            "ph_rb": nm.pv(e.name, "LLRF", "phase"),
                            "ph_sp": nm.pv(e.name, "LLRF", "phase",
                                           setting=True),
                            "det_rb": nm.pv(e.name, "LLRF", "detuning_hz"),
                            "official": nm.map[e.name]["component"]})
                return {"devices": out}
            if method == "events":
                out = []
                for _, f in r.xrevrange(keys.stream("mps.events"),
                                        count=int(args.get("n", 40))):
                    out.append({
                        "kind": f.get(b"kind", b"").decode(),
                        "detail": f.get(b"detail", b"").decode(),
                        "t": float(f.get(b"t", 0))})
                return {"events": out}
            if method == "settings":
                cls, dev = args["cls"], args.get("dev", "main")
                h = r.hgetall(keys.settings(cls, dev))
                return {k.decode(): v.decode() for k, v in h.items()}
            if method == "set":
                import json as _jj
                key = keys.settings(args["cls"], args.get("dev", "main"))
                r.hset(key, args["field"], args["value"])
                from pip2va.common import audit
                audit.log_setting(r, key, args["field"],
                                  args["value"], "flutter")
                r.publish(keys.CH_SETTINGS, _jj.dumps({"key": key}))
                return {"ok": True}
            if method == "snapshots":
                from pip2va.common import snapshots
                act = args.get("action", "list")
                if act == "save":
                    snapshots.save(r, args["name"])
                    return {"ok": True, "saved": args["name"]}
                if act == "restore":
                    r.hset("settings:autotune:main", "restore", 1)
                    return {"ok": True}
                snaps = snapshots.list_snapshots()
                return {"names": [x.get("name", str(x)) if isinstance(x, dict)
                                  else str(x) for x in snaps]}
            if method == "scan_request":
                kind = args.get("kind", "wire")
                nmd = args["name"]
                if kind == "laserwire":
                    r.hset(f"req:lw:{nmd}", mapping={
                        "points": args.get("points", 48),
                        "ppp": 1, "halo": args.get("halo", 0)})
                elif kind == "allison":
                    r.hset("req:allison", mapping={"steps": 48})
                else:
                    r.hset(f"req:wire:{nmd}", mapping={
                        "points": args.get("points", 64), "ppp": 1})
                return {"ok": True}
            if method == "phys":
                if args.get("set"):
                    r.hset("settings:physics:main",
                           args["field"], args["value"])
                    return {"ok": True}
                h = r.hgetall("settings:physics:main")
                return {k.decode(): v.decode() for k, v in h.items()}
            if method == "scenario":
                from pip2va.analysis import scenarios
                act = args.get("action")
                if act == "list":
                    return {"scenarios": [
                        {"name": k, "level": v.get("level"),
                         "desc": v.get("desc")}
                        for k, v in scenarios.SCENARIOS.items()]}
                return {"error": "scenario control via GUI only"}
            if method == "scan_latest":
                e = r.xrevrange(keys.stream("profile.scan"), count=1)
                if not e:
                    return {"scan": None}
                _, d = codec.unpack(e[0][1][b"d"])
                return {"name": d.get("name", ""),
                        "done": float(d.get("done", 0)),
                        "pos": [float(x) for x in d.get("pos_mm", [])],
                        "ix": [float(x) for x in d.get("ix", [])],
                        "iy": [float(x) for x in d.get("iy", [])]}
            if method == "allison_latest":
                e = r.xrevrange(keys.stream("profile.allison"), count=1)
                if not e:
                    return {"img": None}
                _, d = codec.unpack(e[0][1][b"d"])
                return {"n": int(d["n"][0]), "done": float(d["done"][0]),
                        "img": [float(x) for x in d["img"]],
                        "eps": float(d["eps_ummrad"][0]),
                        "alpha": float(d["alpha"][0]),
                        "beta": float(d["beta_m"][0])}
            if method == "wcm_latest":
                e = r.xrevrange(keys.stream("wf.wcm"), count=1)
                if not e:
                    return {"q": None}
                _, d = codec.unpack(e[0][1][b"d"])
                nm = args.get("name", "MEBT:WCM1")
                q = d.get(f"{nm}:q_nc")
                pat = d.get("pat")
                bpg = {k.decode(): v.decode()
                       for k, v in r.hgetall("state:bpg").items()}
                return {"q": [float(x) for x in q] if q is not None else [],
                        "pat": [float(x) for x in pat]
                                if pat is not None else [],
                        "sig_ps": float(d.get(f"{nm}:sig_ps", [0])[0]),
                        "bpg": bpg}
            if method == "geometry":
                from pip2va.common.lattice import load_lattice
                from pip2va.gui.linac3d import floor_map
                lat = load_lattice()
                c, h, poly = floor_map(lat)
                blms = lat.instruments("blm")
                bl_idx = [i for i, e in enumerate(lat.elements)
                          if e.type == "blm"]
                secs = [{"name": s.name, "s": s.s_start}
                        for s in lat.sections]
                return {"poly": [[float(p[0]), float(p[1])]
                                 for p in poly.tolist()],
                        "blm_xy": [[float(c[i][0]), float(c[i][1])]
                                   for i in bl_idx],
                        "sections": secs}
            return {"error": f"unknown method {method}"}
        except Exception as e:
            return {"error": str(e)}

    res = await asyncio.get_event_loop().run_in_executor(None, work)
    if isinstance(res, dict) and "error" in res and len(res) == 1:
        reply(error=res["error"])
    else:
        reply(result=res)


async def ws_handler(request):
    hub: Hub = request.app["hub"]
    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)
    async for msg in ws:
        if msg.type != WSMsgType.TEXT:
            continue
        try:
            m = json.loads(msg.data)
        except ValueError:
            continue
        op = m.get("op")
        if op == "subscribe":
            hub.subscribe(ws, m.get("pvs", []))
        elif op == "unsubscribe":
            for pv in m.get("pvs", []):
                hub.subs.get(pv, set()).discard(ws)
        elif op == "put":
            ok = True
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None, lambda: hub.ctx.put(m["pv"], m["value"]))
            except Exception as e:
                ok = False
                log.warning("put %s failed: %s", m.get("pv"), e)
            await ws.send_json({"op": "put-ack", "pv": m.get("pv"),
                                "ok": ok})
        elif op == "rpc":
            asyncio.ensure_future(_rpc(hub, ws, m))
        elif op == "get":
            try:
                v = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: hub.ctx.get(m["pv"]))
                v = list(v) if hasattr(v, "__len__") else float(v)
                await ws.send_json({"pv": m["pv"], "value": v,
                                    "ts": time.time()})
            except Exception as e:
                await ws.send_json({"pv": m.get("pv"), "error": str(e)})
    hub.unsubscribe_all(ws)
    return ws


@web.middleware
async def no_cache(request, handler):
    resp = await handler(request)
    resp.headers["Cache-Control"] = "no-store, must-revalidate"
    return resp


async def index(request):
    return web.FileResponse(os.path.join(WEB_DIR, "index.html"))


def main():
    logging.basicConfig(level=logging.INFO)
    if not HAVE_P4P:
        raise SystemExit("p4p required")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    app = web.Application(middlewares=[no_cache])
    app["hub"] = Hub(loop)
    app.router.add_get("/ws", ws_handler)
    if os.path.isdir(WEB_DIR):
        app.router.add_get("/", index)
        app.router.add_static("/", WEB_DIR)
    log.info("EPICS web gateway on :%d (app: %s)", PORT, WEB_DIR)
    web.run_app(app, port=PORT, loop=loop)


if __name__ == "__main__":
    main()
