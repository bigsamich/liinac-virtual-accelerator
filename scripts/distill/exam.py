
"""Knowledge exam. Usage: exam.py hf <model_dir> | exam.py ollama <name>"""
import json, sys, urllib.request
SYS = ("You are the operations expert for the PIP-II 800 MeV H- "
       "superconducting linac virtual accelerator. Answer from the "
       "machine's measured findings; be specific.")
QA = [
 ("What is this machine's tightest activation constraint?",
  ["btl"]),
 ("How do I raise the source current to 6 mA safely?",
  ["rfq", "rebaselin"]),
 ("A cavity just died in SSR2. What is the recovery procedure?",
  ["neighbor", "15"]),
 ("How many cryomodules does PIP-II have and of what types?",
  ["23"]),
 ("Why does PIP-II use laserwires instead of wire scanners in the SC linac?",
  ["photodetach", "non-invasive", "melt", "full beam"]),
 ("At what source current is this machine space-charge matched?",
  ["5"]),
]
mode, target = sys.argv[1], sys.argv[2]
score = 0
for q, keys in QA:
    if mode == "ollama":
        req = urllib.request.Request("http://localhost:11434/api/chat",
            data=json.dumps({"model": target, "stream": False,
                "think": False,
                "options": {"num_predict": 150, "temperature": 0.1},
                "messages": [{"role": "system", "content": SYS},
                             {"role": "user", "content": q}]}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=900) as r:
            m = json.loads(r.read())["message"]
        a = (m.get("content") or m.get("thinking") or "")
    else:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        if "model" not in dir():
            tok = AutoTokenizer.from_pretrained(target)
            model = AutoModelForCausalLM.from_pretrained(
                target, dtype=torch.bfloat16, device_map={"": 0})
        ids = tok.apply_chat_template(
            [{"role": "system", "content": SYS},
             {"role": "user", "content": q}],
            add_generation_prompt=True, return_tensors="pt").to("cuda")
        out = model.generate(ids, max_new_tokens=150, do_sample=False)
        a = tok.decode(out[0][ids.shape[1]:], skip_special_tokens=True)
    hit = any(k in a.lower() for k in keys)
    score += hit
    print(f"[{'PASS' if hit else 'FAIL'}] {q}\n  -> {a[:220]}")
print(f"SCORE {score}/{len(QA)}")
sys.exit(0 if score >= 4 else 1)
