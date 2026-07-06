#!/bin/bash
# Bootstrap the PIP-II VA on a fresh DGX Spark (or any CUDA aarch64 box).
# Prereqs: docker + nvidia-container-toolkit, python3.12, (optional) ollama.
set -e
cd "$(dirname "$0")/.."
echo "== python env =="
python3 -m venv .venv
.venv/bin/pip -q install --upgrade pip
.venv/bin/pip -q install -e ".[gui,dev]" 2>/dev/null || .venv/bin/pip -q install -e ".[gui]"
echo "== seed machine state (study results, knowledge base, golden) =="
# pre-create as the invoking user BEFORE docker mounts it — otherwise the
# web-gui volume mount makes docker create it root-owned and host-side
# snapshot/study writes get permission-denied
mkdir -p ~/.pip2va/studies ~/.pip2va/snapshots
if [ ! -w ~/.pip2va/studies ]; then
  echo "!! ~/.pip2va is not writable by $USER (root-owned from an earlier"
  echo "   docker run). Fix with: sudo chown -R \$USER:\$USER ~/.pip2va"
  exit 1
fi
[ -f ~/.pip2va/studies/knowledge.jsonl ] || cp -r data/seed/studies/. ~/.pip2va/studies/
[ -f ~/.pip2va/snapshots/golden.json ] || cp -r data/seed/snapshots/. ~/.pip2va/snapshots/ 2>/dev/null || true
echo "== build + start the stack =="
docker compose build
make reset          # up + wait for baseline + MACHINE READY
echo "== optional: AI assistant (needs ollama) =="
if curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
  echo "  pulling models (qwen3.6 is ~20+ GB — one-time download)..."
  ollama pull qwen3.6 || curl -s http://localhost:11434/api/pull \
      -d '{"model":"qwen3.6"}' >/dev/null
  ollama pull qwen3-embedding:8b || curl -s http://localhost:11434/api/pull \
      -d '{"model":"qwen3-embedding:8b"}' >/dev/null
  if .venv/bin/python scripts/distill/bake_expert.py; then
    echo "  AI assistant ready (pip2va-expert)"
  else
    echo "  !! bake failed — check 'ollama list' has qwen3.6, then rerun:"
    echo "     .venv/bin/python scripts/distill/bake_expert.py"
  fi
else
  echo "  (ollama not detected — everything except the AI works; install"
  echo "   ollama, then rerun this script or bake_expert.py)"
fi
echo "== done. Native GUI: make gui | Browser: :6080 | Phone: :6081 =="
