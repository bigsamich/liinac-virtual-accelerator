# EPICS web gateway: PVA client -> WebSocket JSON + (optional) Flutter app.
#
# WEBAPP_MODE selects where the browser app comes from (BuildKit only builds
# the stage that is actually referenced, so "none" skips Flutter entirely):
#   full  (default) - compile the Flutter web app from source in-image
#   none            - no Flutter build (WS/PVA gateway only; use the VNC GUI)
ARG WEBAPP_MODE=full

# ---- web content: full (Flutter) --------------------------------------
FROM ghcr.io/cirruslabs/flutter:stable AS web-full
WORKDIR /src
COPY webapp/pubspec.yaml webapp/pubspec.lock* ./
RUN git config --global --add safe.directory '*' && flutter pub get
COPY webapp/ ./
RUN flutter build web --release --pwa-strategy=none \
    && printf '%s\n' \
       "self.addEventListener('install',(e)=>self.skipWaiting());" \
       "self.addEventListener('activate',(e)=>{e.waitUntil((async()=>{const k=await caches.keys();await Promise.all(k.map((x)=>caches.delete(x)));await self.registration.unregister();(await self.clients.matchAll({type:'window'})).forEach((c)=>c.navigate(c.url));})());});" \
       > build/web/flutter_service_worker.js \
    && mkdir -p /web && cp -r build/web/. /web/

# ---- web content: none (tiny placeholder, no Flutter SDK pulled) -------
FROM alpine:3 AS web-none
RUN mkdir -p /web && printf '%s' \
    '<!doctype html><meta charset=utf-8><title>PIP-II VA gateway</title>' \
    '<body style="font-family:sans-serif;background:#0d1117;color:#d7dde5;padding:2rem">' \
    '<h2>PIP-II VA EPICS web gateway</h2><p>This build has no Flutter app ' \
    '(WEBAPP_MODE=none). The WebSocket/PVA gateway at <code>/ws</code> is ' \
    'live; use the desktop/VNC GUI, or rebuild with WEBAPP_MODE=full.</p>' \
    > /web/index.html

# ---- select the web content per WEBAPP_MODE ---------------------------
FROM web-${WEBAPP_MODE} AS websrc

# ---- gateway runtime ---------------------------------------------------
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc g++ make && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md ./
COPY pip2va ./pip2va
RUN pip install --no-cache-dir . && pip install --no-cache-dir p4p aiohttp
COPY --from=websrc /web /app/web
CMD ["python", "-m", "pip2va.services.epics_ws.main"]
