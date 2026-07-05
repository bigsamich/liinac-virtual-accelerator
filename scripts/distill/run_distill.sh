#!/bin/bash
set -e
cd /home/bigsamich/Workspace/projects/liinac-beam-sim
L=scripts/distill/pipeline.log
echo "=== distill pipeline $(date) ===" > $L
python3 -m venv .venv-train 2>>$L
.venv-train/bin/pip install -q --upgrade pip >>$L 2>&1
.venv-train/bin/pip install -q torch --index-url https://download.pytorch.org/whl/cu129 >>$L 2>&1 \
  || .venv-train/bin/pip install -q torch >>$L 2>&1
.venv-train/bin/pip install -q transformers peft datasets accelerate sentencepiece protobuf >>$L 2>&1
echo "deps done $(date)" >> $L
.venv-train/bin/python -c "import torch; print('cuda:', torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')" >>$L 2>&1
# refresh dataset to include campaign results landed since generation
.venv/bin/python scripts/distill/make_dataset.py >>$L 2>&1
.venv-train/bin/python scripts/distill/train_lora.py >>$L 2>&1
echo "training done $(date)" >> $L
# GGUF conversion
if [ ! -d /tmp/llama.cpp ]; then git clone --depth 1 https://github.com/ggerganov/llama.cpp /tmp/llama.cpp >>$L 2>&1; fi
.venv-train/bin/pip install -q gguf mistral-common >>$L 2>&1
.venv-train/bin/python /tmp/llama.cpp/convert_hf_to_gguf.py scripts/distill/merged --outfile scripts/distill/pip2va-expert-ft.gguf --outtype q8_0 >>$L 2>&1
echo "gguf done $(date)" >> $L
python3 - <<'PYEOF' >>$L 2>&1
import json, urllib.request, os
path = os.path.abspath("scripts/distill/pip2va-expert-ft.gguf")
# ollama create from local gguf via CLI-less API: use file blob upload
import hashlib
h = hashlib.sha256(open(path,'rb').read()).hexdigest()
data = open(path,'rb').read()
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
print("OLLAMA MODEL CREATED: pip2va-expert-ft")
PYEOF
echo "PIPELINE COMPLETE $(date)" >> $L
tail -3 $L
