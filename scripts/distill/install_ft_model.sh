#!/bin/bash
# Install the fine-tuned 32B student into local ollama from a GGUF file.
# Usage: ./install_ft_model.sh /path/to/pip2va-expert-ft32.gguf
set -e
GGUF="${1:?usage: install_ft_model.sh <gguf path>}"
python3 - "$GGUF" <<'PYEOF'
import hashlib, json, sys, urllib.request
path = sys.argv[1]
print("hashing + uploading blob (34 GB — takes a few minutes)...")
h = hashlib.sha256()
with open(path, "rb") as f:
    while chunk := f.read(1 << 24):
        h.update(chunk)
digest = h.hexdigest()
data = open(path, "rb").read()
urllib.request.urlopen(urllib.request.Request(
    f"http://localhost:11434/api/blobs/sha256:{digest}",
    data=data, method="POST"), timeout=7200)
tmpl = ("{{ if .System }}<|im_start|>system\n{{ .System }}<|im_end|>\n"
        "{{ end }}{{ if .Prompt }}<|im_start|>user\n{{ .Prompt }}"
        "<|im_end|>\n{{ end }}<|im_start|>assistant\n{{ .Response }}"
        "<|im_end|>\n")
req = urllib.request.Request("http://localhost:11434/api/create",
    data=json.dumps({"model": "pip2va-expert-ft",
                     "files": {"m.gguf": f"sha256:{digest}"},
                     "template": tmpl,
                     "parameters": {"temperature": 0.2,
                                    "stop": ["<|im_end|>"]}}).encode(),
    headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=3600) as r:
    for line in r:
        pass
print("ollama model created: pip2va-expert-ft")
PYEOF
echo "Exam it: .venv/bin/python scripts/distill/exam.py ollama pip2va-expert-ft"
