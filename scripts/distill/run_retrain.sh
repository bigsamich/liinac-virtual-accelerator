#!/bin/bash
set -e
cd /home/bigsamich/Workspace/projects/liinac-beam-sim
L=scripts/distill/retrain.log
echo "=== retrain $(date) ===" > $L
.venv/bin/python scripts/distill/make_dataset.py >>$L 2>&1
nice -n 15 .venv-train/bin/python scripts/distill/train_lora.py >>$L 2>&1
echo "training done $(date)" >>$L
.venv-train/bin/python /tmp/llama.cpp/convert_hf_to_gguf.py scripts/distill/merged --outfile scripts/distill/pip2va-expert-ft.gguf --outtype q8_0 >>$L 2>&1
python3 - <<'PYEOF' >>$L 2>&1
import json, urllib.request, hashlib
path = "scripts/distill/pip2va-expert-ft.gguf"
data = open(path, 'rb').read()
h = hashlib.sha256(data).hexdigest()
req = urllib.request.Request(f"http://localhost:11434/api/blobs/sha256:{h}",
                             data=data, method="POST")
urllib.request.urlopen(req, timeout=1800)
req = urllib.request.Request("http://localhost:11434/api/create",
    data=json.dumps({"model": "pip2va-expert-ft",
                     "files": {"pip2va-expert-ft.gguf": f"sha256:{h}"},
                     "parameters": {"temperature": 0.3}}).encode(),
    headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=1800) as r:
    for line in r: pass
print("MODEL RECREATED")
PYEOF
echo "RETRAIN COMPLETE $(date)" >>$L
tail -2 $L
