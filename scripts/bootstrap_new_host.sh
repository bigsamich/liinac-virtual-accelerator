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
mkdir -p ~/.pip2va
[ -d ~/.pip2va/studies ] || cp -r data/seed/studies ~/.pip2va/studies
[ -d ~/.pip2va/snapshots ] || cp -r data/seed/snapshots ~/.pip2va/snapshots 2>/dev/null || true
echo "== build + start the stack =="
docker compose build
make reset          # up + wait for baseline + MACHINE READY
echo "== optional: AI assistant models (needs ollama with qwen3.6) =="
if curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
  .venv/bin/python scripts/distill/bake_expert.py || true
else
  echo "  (ollama not detected — GUI works without AI; install ollama and"
  echo "   run scripts/distill/bake_expert.py later)"
fi
echo "== done. Native GUI: make gui | Browser: :6080 | Phone: :6081 =="
