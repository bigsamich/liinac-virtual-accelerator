
"""LoRA r=64 fine-tune of Qwen3-32B on the full machine corpus."""
import json, torch
from datasets import Dataset
from peft import LoraConfig, get_peft_model
from transformers import (AutoModelForCausalLM, AutoTokenizer,
                          Trainer, TrainingArguments)
BASE = "Qwen/Qwen3-32B"
tok = AutoTokenizer.from_pretrained(BASE)
rows = [json.loads(l) for l in open("scripts/distill/dataset.jsonl")]
ds = Dataset.from_list([{"text": tok.apply_chat_template(
    r["messages"], tokenize=False, add_generation_prompt=False)}
    for r in rows])
def tok_fn(b):
    out = tok(b["text"], truncation=True, max_length=640,
              padding="max_length")
    pad = tok.pad_token_id
    out["labels"] = [[t if t != pad else -100 for t in seq]
                     for seq in out["input_ids"]]
    return out
ds = ds.map(tok_fn, batched=True, remove_columns=["text"])
model = AutoModelForCausalLM.from_pretrained(
    BASE, dtype=torch.bfloat16, device_map={"": 0})
model.gradient_checkpointing_enable()
model.enable_input_require_grads()
model = get_peft_model(model, LoraConfig(
    r=64, lora_alpha=128, lora_dropout=0.05, task_type="CAUSAL_LM",
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                    "gate_proj", "up_proj", "down_proj"]))
model.print_trainable_parameters()
Trainer(model=model, train_dataset=ds, args=TrainingArguments(
    output_dir="scripts/distill/out32", num_train_epochs=3,
    per_device_train_batch_size=1, gradient_accumulation_steps=16,
    learning_rate=8e-5, bf16=True, logging_steps=10,
    save_strategy="no", report_to=[])).train()
model = model.merge_and_unload()
model.save_pretrained("scripts/distill/merged32", safe_serialization=True)
tok.save_pretrained("scripts/distill/merged32")
print("MERGED32 SAVED")
