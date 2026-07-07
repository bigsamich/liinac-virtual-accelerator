# EPICS web gateway: PVA client -> WebSocket JSON + Flutter web app (:8085)
#
# Stage 1 builds the Flutter web app from source (webapp/ is in git; only
# webapp/build/ is ignored) so `docker compose build` is self-contained and
# needs no Flutter SDK on the host.
FROM ghcr.io/cirruslabs/flutter:stable AS webbuild
WORKDIR /src
COPY webapp/pubspec.yaml webapp/pubspec.lock* ./
RUN git config --global --add safe.directory '*' && flutter pub get
COPY webapp/ ./
RUN flutter build web --release --pwa-strategy=none
# kill-switch service worker: unregister any stale worker on clients so the
# freshly-built app always loads (module imports cache hard otherwise)
RUN printf '%s\n' \
    "self.addEventListener('install',(e)=>self.skipWaiting());" \
    "self.addEventListener('activate',(e)=>{e.waitUntil((async()=>{const k=await caches.keys();await Promise.all(k.map((x)=>caches.delete(x)));await self.registration.unregister();(await self.clients.matchAll({type:'window'})).forEach((c)=>c.navigate(c.url));})());});" \
    > build/web/flutter_service_worker.js

# Stage 2: the gateway runtime
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc g++ make && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md ./
COPY pip2va ./pip2va
RUN pip install --no-cache-dir . && pip install --no-cache-dir p4p aiohttp
COPY --from=webbuild /src/build/web /app/web
CMD ["python", "-m", "pip2va.services.epics_ws.main"]
