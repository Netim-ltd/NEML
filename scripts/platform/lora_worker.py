# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Train one bounded, approved-data LoRA adapter; leave promotion manual."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from datetime import datetime
from pathlib import Path

from nightly_lora import TZ, dataset_digest, load_job, night_window


def load_pairs(path: Path) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    train: list[dict[str, str]] = []
    holdout: list[dict[str, str]] = []
    import hashlib

    seen: set[str] = set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("approved") is not True:
            continue
        prompt, completion = row.get("prompt"), row.get("completion")
        if not isinstance(prompt, str) or not isinstance(completion, str):
            raise ValueError(f"row {number}: prompt/completion must be text")
        if not (1 <= len(prompt) <= 4096 and 1 <= len(completion) <= 2048):
            raise ValueError(f"row {number}: text length outside bounds")
        digest = hashlib.sha256((prompt + "\0" + completion).encode()).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        (holdout if int(digest[:2], 16) < 51 else train).append(
            {"prompt": prompt, "completion": completion}
        )
    if len(train) < 32 or len(holdout) < 8:
        raise ValueError("need >=32 distinct approved training and >=8 holdout examples")
    return train, holdout


def train(job: dict[str, str], digest: str) -> None:
    import torch
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        BitsAndBytesConfig,
        Trainer,
        TrainerCallback,
        TrainingArguments,
        default_data_collator,
    )

    if not torch.cuda.is_available():
        raise RuntimeError("LoRA worker requires a GPU host; control server is not eligible")
    if dataset_digest(Path(job["dataset"])) != digest:
        raise RuntimeError("dataset changed after dispatch")
    train_rows, holdout_rows = load_pairs(Path(job["dataset"]))
    tokenizer = AutoTokenizer.from_pretrained(
        job["base_model"], revision=job["base_revision"], trust_remote_code=False
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    if tokenizer.pad_token is None:
        raise ValueError("base tokenizer has no EOS or pad token")
    max_length = 512

    class Pairs(torch.utils.data.Dataset):
        def __init__(self, rows: list[dict[str, str]]) -> None:
            self.items: list[dict[str, list[int]]] = []
            for row in rows:
                prefix = tokenizer(row["prompt"], add_special_tokens=True)["input_ids"]
                answer = tokenizer(row["completion"], add_special_tokens=False)["input_ids"]
                answer = answer + [tokenizer.eos_token_id]
                if len(prefix) + len(answer) > max_length:
                    prefix = prefix[-(max_length - len(answer)):]
                if not prefix or len(answer) >= max_length:
                    continue
                tokens = prefix + answer
                padding = max_length - len(tokens)
                self.items.append({
                    "input_ids": tokens + [tokenizer.pad_token_id] * padding,
                    "attention_mask": [1] * len(tokens) + [0] * padding,
                    "labels": [-100] * len(prefix) + answer + [-100] * padding,
                })

        def __len__(self) -> int:
            return len(self.items)

        def __getitem__(self, index: int) -> dict[str, list[int]]:
            return self.items[index]

    train_data, eval_data = Pairs(train_rows), Pairs(holdout_rows)
    if len(train_data) < 32 or len(eval_data) < 8:
        raise ValueError("too few usable tokenized examples")
    bf16 = bool(torch.cuda.is_bf16_supported())
    dtype = torch.bfloat16 if bf16 else torch.float16
    quantization = job.get("quantization", "none")
    quantization_config = None
    if quantization == "nf4":
        quantization_config = BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=dtype, bnb_4bit_use_double_quant=True,
        )
    model = AutoModelForCausalLM.from_pretrained(
        job["base_model"], revision=job["base_revision"], trust_remote_code=False,
        torch_dtype=dtype, quantization_config=quantization_config,
    )
    if model.num_parameters() > 1_500_000_000:
        raise ValueError("initial mini-LLM tier allows at most 1.5B parameters")
    model.config.use_cache = False
    output = Path(job["output"])
    run_id = datetime.now(TZ).strftime("%Y%m%dT%H%M%S") + "-" + digest[:12]
    candidate = output / "candidates" / run_id
    args = TrainingArguments(
        output_dir=str(candidate / "checkpoint"), max_steps=100,
        per_device_train_batch_size=1, per_device_eval_batch_size=1,
        gradient_accumulation_steps=4, learning_rate=2e-4,
        gradient_checkpointing=True, bf16=bf16, fp16=not bf16,
        eval_strategy="no", save_strategy="no", report_to="none",
        remove_unused_columns=False, dataloader_num_workers=0,
    )
    baseline = Trainer(model=model, args=args, eval_dataset=eval_data,
                       data_collator=default_data_collator).evaluate()["eval_loss"]
    if not night_window(datetime.now(TZ)):
        raise RuntimeError("night window closed before training")
    if quantization == "nf4":
        model = prepare_model_for_kbit_training(model)
    model = get_peft_model(model, LoraConfig(
        r=8, lora_alpha=16, lora_dropout=0.05, bias="none",
        task_type="CAUSAL_LM", target_modules="all-linear",
    ))

    class NightStop(TrainerCallback):
        def on_step_end(self, args, state, control, **kwargs):
            if not night_window(datetime.now(TZ)):
                control.should_training_stop = True
            return control

    trainer = Trainer(model=model, args=args, train_dataset=train_data,
                      eval_dataset=eval_data, data_collator=default_data_collator,
                      callbacks=[NightStop()])
    trainer.train()
    if not night_window(datetime.now(TZ)):
        raise RuntimeError("night window closed; candidate rejected")
    loss = trainer.evaluate()["eval_loss"]
    if dataset_digest(Path(job["dataset"])) != digest:
        raise RuntimeError("dataset changed during training")
    if not math.isfinite(loss) or not math.isfinite(baseline) or loss >= baseline:
        raise RuntimeError("holdout loss did not improve; candidate rejected")
    adapter_dir = candidate / "adapter"
    model.save_pretrained(adapter_dir, safe_serialization=True)
    tokenizer.save_pretrained(adapter_dir)
    adapter_file = adapter_dir / "adapter_model.safetensors"
    adapter_sha = hashlib.sha256(adapter_file.read_bytes()).hexdigest()
    record = {
        "tenant": job["tenant"], "domain": job["domain"],
        "operation": job["operation"],
        "base_model": job["base_model"], "base_revision": job["base_revision"],
        "quantization": quantization,
        "dataset_sha256": digest, "train_count": len(train_data),
        "holdout_count": len(eval_data), "baseline_loss": baseline,
        "candidate_loss": loss, "adapter_path": str(adapter_dir),
        "adapter_sha256": adapter_sha,
        "status": "offline_candidate", "created_at": datetime.now(TZ).isoformat(),
    }
    candidate.mkdir(parents=True, exist_ok=True)
    (candidate / "result.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    (output / "last-success.json").write_text(json.dumps(record, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    job = load_job(args.job, args.root.resolve())
    digest = os.environ["NEML_DATASET_SHA256"]
    if not night_window(datetime.now(TZ)):
        raise PermissionError("training is outside the night window")
    train(job, digest)


if __name__ == "__main__":
    main()
