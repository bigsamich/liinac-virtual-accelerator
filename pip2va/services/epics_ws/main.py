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
