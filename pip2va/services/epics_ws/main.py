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
