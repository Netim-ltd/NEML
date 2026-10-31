# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Serve one explicitly approved operation adapter on a GPU host's loopback."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def load_activation(path: Path, root: Path) -> dict:
    activation = json.loads(path.read_text(encoding="utf-8"))
    if not activation.get("approved_by") or not activation.get("candidate_result"):
        raise ValueError("a named human approval and candidate_result are required")
    result_path = (root / activation["candidate_result"]).resolve()
    if not result_path.is_relative_to(root.resolve()):
        raise ValueError("candidate result escapes training root")
    record = json.loads(result_path.read_text(encoding="utf-8"))
    if record.get("status") != "offline_candidate":
        raise ValueError("candidate did not pass offline evaluation")
    adapter = Path(record["adapter_path"]).resolve()
    if not adapter.is_relative_to(root.resolve()):
        raise ValueError("adapter escapes training root")
    digest = hashlib.sha256((adapter / "adapter_model.safetensors").read_bytes()).hexdigest()
    if digest != record["adapter_sha256"]:
        raise ValueError("adapter checksum mismatch")
    return record


def serve(record: dict, *, host: str, port: int, api_key: str) -> None:
    if host not in ("127.0.0.1", "::1"):
        raise ValueError("inference service must bind to loopback; use a private gateway")
    if len(api_key) < 32:
        raise ValueError("NEML_LORA_API_KEY must be at least 32 characters")
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    if not torch.cuda.is_available():
        raise RuntimeError("LoRA serving requires a GPU host")
    dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    quantization = record.get("quantization", "none")
    if quantization not in ("none", "nf4"):
        raise ValueError("unsupported candidate quantization")
    quantization_config = (
        BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                           bnb_4bit_compute_dtype=dtype, bnb_4bit_use_double_quant=True)
        if quantization == "nf4" else None
    )
    base = AutoModelForCausalLM.from_pretrained(
        record["base_model"], revision=record["base_revision"],
        trust_remote_code=False, torch_dtype=dtype, device_map="auto",
        quantization_config=quantization_config,
    )
    if base.num_parameters() > 1_500_000_000:
        raise ValueError("initial mini-LLM tier allows at most 1.5B parameters")
    model = PeftModel.from_pretrained(base, record["adapter_path"], is_trainable=False)
    model.eval()
    tokenizer = AutoTokenizer.from_pretrained(
        record["base_model"], revision=record["base_revision"], trust_remote_code=False,
    )
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def reply(self, status: int, body: dict) -> None:
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:
            self.reply(200, {"status": "ok"}) if self.path == "/health" else self.reply(404, {})

        def do_POST(self) -> None:
            if self.path != "/v1/operation/generate":
                self.reply(404, {})
                return
            supplied = self.headers.get("Authorization", "")
            if not hmac.compare_digest(supplied, f"Bearer {api_key}"):
                self.reply(401, {"error": "unauthorized"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 8192:
                    raise ValueError("request too large or empty")
                request = json.loads(self.rfile.read(length))
                prompt = request.get("prompt")
                if (request.get("tenant") != record["tenant"]
                        or request.get("domain") != record["domain"]
                        or request.get("operation") != record["operation"]
                        or not isinstance(prompt, str) or not 1 <= len(prompt) <= 4096):
                    raise ValueError("tenant, operation or prompt invalid")
                device = next(model.parameters()).device
                inputs = tokenizer(prompt, return_tensors="pt", truncation=True,
                                   max_length=512).to(device)
                with lock, torch.inference_mode():
                    tokens = model.generate(**inputs, max_new_tokens=128, do_sample=False,
                                            pad_token_id=tokenizer.eos_token_id)
                completion = tokenizer.decode(
                    tokens[0][inputs["input_ids"].shape[-1]:], skip_special_tokens=True
                )
                self.reply(200, {"tenant": record["tenant"],
                                 "domain": record["domain"],
                                 "operation": record["operation"],
                                 "adapter_sha256": record["adapter_sha256"],
                                 "completion": completion})
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self.reply(400, {"error": str(exc)})

    ThreadingHTTPServer((host, port), Handler).serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--activation", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    record = load_activation(args.activation, args.root.resolve())
    serve(record, host=args.host, port=args.port, api_key=os.environ["NEML_LORA_API_KEY"])


if __name__ == "__main__":
    main()
