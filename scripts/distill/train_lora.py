"""LoRA fine-tune of Qwen3-8B on the machine's study knowledge."""
import json, torch
from datasets import Dataset
from peft import LoraConfig, get_peft_model
from transformers import (AutoModelForCausalLM, AutoTokenizer,
                          Trainer, TrainingArguments)

BASE = "Qwen/Qwen3-8B"
tok = AutoTokenizer.from_pretrained(BASE)
rows = [json.loads(l) for l in open("scripts/distill/dataset.jsonl")]
def fmt(r):
    text = tok.apply_chat_template(r["messages"], tokenize=False,
                                   add_generation_prompt=False)
    return {"text": text}
ds = Dataset.from_list([fmt(r) for r in rows])
def tok_fn(b):
    out = tok(b["text"], truncation=True, max_length=512,
              padding="max_length")
    # mask padding out of the loss — otherwise pads dominate 10:1
    pad = tok.pad_token_id
    out["labels"] = [[t if t != pad else -100 for t in seq]
                     for seq in out["input_ids"]]
    return out
ds = ds.map(tok_fn, batched=True, remove_columns=["text"])
model = AutoModelForCausalLM.from_pretrained(
    BASE, torch_dtype=torch.bfloat16, device_map={"": 0})
model = get_peft_model(model, LoraConfig(
    r=16, lora_alpha=32, lora_dropout=0.05, task_type="CAUSAL_LM",
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                    "gate_proj", "up_proj", "down_proj"]))
model.print_trainable_parameters()
Trainer(model=model, train_dataset=ds, args=TrainingArguments(
    output_dir="scripts/distill/out", num_train_epochs=4,
    per_device_train_batch_size=2, gradient_accumulation_steps=8,
    learning_rate=1e-4, bf16=True, logging_steps=10,
    save_strategy="no", report_to=[])).train()
model = model.merge_and_unload()
model.save_pretrained("scripts/distill/merged", safe_serialization=True)
tok.save_pretrained("scripts/distill/merged")
print("MERGED SAVED")
