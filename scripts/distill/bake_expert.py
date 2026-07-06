"""(Re)bake the pip2va-expert model: design facts + measured insights
into a qwen3.6 system prompt. Run anytime the KB gains insights."""
import json, sys, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from pip2_facts import FACTS
from pip2va.analysis import knowledge, llm
ins = [f["summary"] for f in knowledge.load(2000) if f.get("kind") == "insight"]
sys_prompt = ("You are the operations expert for the PIP-II 800 MeV H- "
    "linac virtual accelerator.\n\nDESIGN FACTS (PIP-II reference):\n"
    + "\n".join(f"- {q} {a}" for q, a in FACTS)
    + "\n\nMEASURED TRUTHS from this machine's beam-study program (these "
    "win over anything else):\n" + "\n".join("- " + i for i in ins)
    + "\nBe concise and specific. Live machine state arrives in the user "
      "message.")
req = urllib.request.Request(llm.OLLAMA_URL + "/api/create",
    data=json.dumps({"model": "pip2va-expert", "from": "qwen3.6:latest",
                     "system": sys_prompt,
                     "parameters": {"temperature": 0.3}}).encode(),
    headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=600) as r:
    for line in r:
        pass
print(f"pip2va-expert baked: {len(FACTS)} facts + {len(ins)} insights")
