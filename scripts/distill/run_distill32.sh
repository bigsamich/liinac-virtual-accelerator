#!/bin/bash
set -e
cd /home/bigsamich/Workspace/projects/liinac-beam-sim
L=scripts/distill/train32.log
echo "=== 32B distill $(date) ===" > $L
# wait for the C4 campaign to finish so its results are in the dataset
while [ "$(redis-cli -h localhost LLEN state:study.queue 2>/dev/null || echo 0)" != "0" ] || \
      [ "$(redis-cli -h localhost HGET state:study run 2>/dev/null)" = "1" ]; do
  sleep 60
done
echo "C4 drained $(date)" >> $L
.venv/bin/python scripts/distill/make_dataset.py >>$L 2>&1
echo "dataset done $(date)" >> $L
nice -n 15 .venv-train/bin/python scripts/distill/train_lora32.py >>$L 2>&1
echo "training done $(date)" >> $L
# exam the merged model DIRECTLY first (isolates serving from training)
nice -n 10 .venv-train/bin/python scripts/distill/exam.py hf scripts/distill/merged32 >>$L 2>&1 \
  && echo "HF-EXAM PASS" >> $L || echo "HF-EXAM FAIL" >> $L
.venv-train/bin/python /tmp/llama.cpp/convert_hf_to_gguf.py scripts/distill/merged32 \
  --outfile scripts/distill/pip2va-expert-ft32.gguf --outtype q6_k >>$L 2>&1 \
  || .venv-train/bin/python /tmp/llama.cpp/convert_hf_to_gguf.py scripts/distill/merged32 \
  --outfile scripts/distill/pip2va-expert-ft32.gguf --outtype q8_0 >>$L 2>&1
echo "gguf done $(date)" >> $L
python3 - <<'PYEOF' >>$L 2>&1
import json, urllib.request, hashlib
path = "scripts/distill/pip2va-expert-ft32.gguf"
data = open(path, 'rb').read()
h = hashlib.sha256(data).hexdigest()
urllib.request.urlopen(urllib.request.Request(
    f"http://localhost:11434/api/blobs/sha256:{h}", data=data,
    method="POST"), timeout=3600)
tmpl = ("{{ if .System }}<|im_start|>system\n{{ .System }}<|im_end|>\n"
        "{{ end }}{{ if .Prompt }}<|im_start|>user\n{{ .Prompt }}"
        "<|im_end|>\n{{ end }}<|im_start|>assistant\n{{ .Response }}"
        "<|im_end|>\n")
req = urllib.request.Request("http://localhost:11434/api/create",
    data=json.dumps({"model": "pip2va-expert-ft",
                     "files": {"m.gguf": f"sha256:{h}"},
                     "template": tmpl,
                     "parameters": {"temperature": 0.2,
                                    "stop": ["<|im_end|>"]}}).encode(),
    headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=3600) as r:
    for line in r: pass
print("OLLAMA 32B MODEL CREATED")
PYEOF
# final gate: exam through ollama; promote only on pass
rm -f scripts/distill/EXAM_PASS
if .venv/bin/python scripts/distill/exam.py ollama pip2va-expert-ft >>$L 2>&1; then
  touch scripts/distill/EXAM_PASS
  echo "OLLAMA-EXAM PASS — PROMOTED" >> $L
else
  echo "OLLAMA-EXAM FAIL — not promoted" >> $L
fi
echo "PIPELINE32 COMPLETE $(date)" >> $L
tail -4 $L
