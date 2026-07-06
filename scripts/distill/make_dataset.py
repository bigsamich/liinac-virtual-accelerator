"""Build the fine-tune dataset from the machine's own knowledge:
KB findings + insights + every study result -> chat-format JSONL."""
import json, random, re
from pathlib import Path

D = Path.home() / ".pip2va" / "studies"
OUT = Path("scripts/distill/dataset.jsonl")
SYS = ("You are the operations expert for the PIP-II 800 MeV H- linac "
       "virtual accelerator. Answer from the machine's measured findings: "
       "be specific about devices, tolerances, trip points and procedures.")

import sys
sys.path.insert(0, "scripts/distill")
from pip2_facts import FACTS

rows = []
def add(q, a):
    rows.append({"messages": [
        {"role": "system", "content": SYS},
        {"role": "user", "content": q},
        {"role": "assistant", "content": a}]})

for q, a in FACTS:
    add(q, a)
    add(q.replace("What is", "Tell me about").replace(
        "What are", "Describe").replace("How does", "Explain how"), a)

kb = [json.loads(l) for l in
      (D / "knowledge.jsonl").read_text().splitlines() if l.strip()]
for f in kb:
    s = f.get("summary", "")
    dev = f.get("device", "")
    if not s or len(s) < 30:
        continue
    if f.get("kind") == "insight":
        add(f"What is the operational insight about {dev}?", s)
        add(f"What should I know before touching {dev}?", s)
    else:
        add(f"What did we measure about {dev}?", s)
        m = re.search(r"trips the MPS at ([\d.+-]+)", s)
        if m:
            add(f"What happens if {dev} reaches {m.group(1)}?",
                f"The machine trips: {s}")

ins = [f["summary"] for f in kb if f.get("kind") == "insight"][:20]
add("What are this machine's key operational constraints?",
    "\n".join("- " + i for i in ins))
add("Summarize what the beam study program has learned.",
    "\n".join("- " + i for i in ins))

for fp in sorted(D.glob("result-*.json")):
    try:
        d = json.loads(fp.read_text())
        plan, res = d["plan"], d["result"]
        sw = plan["sweeps"][0]
        steps = res.get("steps", [])
        if not steps:
            continue
        wl = [s["worst_blm"] for s in steps]
        tt = [s["transmission"] for s in steps]
        dev = f"{sw['device']} {sw['field']}"
        ans = (f"Study '{plan['name']}' swept {dev} from {sw['from']:g} to "
               f"{sw['to']:g} in {len(steps)} steps; status "
               f"{res.get('status')}. Losses ranged "
               f"{min(wl):.1f}-{max(wl):.1f} W/m, transmission "
               f"{min(tt):.4f}-{max(tt):.4f}.")
        if res.get("status") == "aborted-trip":
            ans += (f" The MPS tripped at {steps[-1]['set_values'][0]:g} — "
                    f"treat that as the empirical limit.")
        add(f"What did study {plan['name']} find?", ans)
        add(f"Is it safe to sweep {dev} between {sw['from']:g} and "
            f"{sw['to']:g}?",
            ("Yes — that span completed cleanly: " if
             res.get("status") == "completed" else
             "Careful — that exact span tripped the MPS: ") + ans)
    except Exception:
        continue

# --- QA mined from the user guides (docs/guides/*.md sections)
import re as _re
for gp in sorted(Path("docs/guides").glob("*.md")):
    txt = gp.read_text()
    for m in _re.finditer(r"^##+ (.+?)\n(.*?)(?=\n##|\Z)", txt, _re.S | _re.M):
        title = m.group(1).strip().lstrip("0123456789.— -")
        body = m.group(2).strip()
        body = _re.sub(r"\n{2,}", "\n", body)
        if 120 < len(body) < 1600 and "|" not in title:
            add(f"Explain: {title}", body)
            add(f"How does {title.lower()} work in this machine?", body)

# --- teacher paraphrases (qwen3.6 via ollama): reword questions so the
#     student generalizes beyond template phrasings
import os, urllib.request
if os.environ.get("TEACHER_AUG", "1") == "1":
    base = rows[:]
    random.seed(11)
    random.shuffle(base)
    n_aug = 0
    for r0 in base:
        if n_aug >= 400:
            break
        q0 = r0["messages"][1]["content"]
        a0 = r0["messages"][2]["content"]
        try:
            req = urllib.request.Request(
                "http://localhost:11434/api/chat",
                data=json.dumps({"model": "qwen3.6:latest", "stream": False,
                    "think": False,
                    "options": {"temperature": 0.8, "num_predict": 60},
                    "messages": [{"role": "user", "content":
                        "Reword this question in different words, same "
                        "meaning, one line, no preamble: " + q0}]}).encode(),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                q1 = json.loads(resp.read())["message"].get("content", "").strip()
            if 10 < len(q1) < 300 and q1 != q0:
                add(q1, a0)
                n_aug += 1
        except Exception:
            continue
    print(f"teacher paraphrases: {n_aug}")

random.seed(7)
random.shuffle(rows)
OUT.write_text("\n".join(json.dumps(r) for r in rows))
print(f"{len(rows)} training pairs -> {OUT}")
