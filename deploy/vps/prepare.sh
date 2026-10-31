#!/bin/sh
# Fetch the GGUF model and render llm.yaml for the llama.cpp provider.
set -eu
cd "$(dirname "$0")"
mkdir -p models
[ -f models/model.gguf ] || curl -fL -o models/model.gguf \
  "${NEML_MODEL_URL:-https://huggingface.co/Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF/resolve/main/qwen2.5-coder-1.5b-instruct-q4_k_m.gguf}"
python3 - <<'PY'
import re
s = open("../../config/llm.yaml", encoding="utf-8").read()
s = s.replace("provider: vllm", "provider: llama_cpp", 1)
s = re.sub(r"(  llama_cpp:\n    enabled: )false", r"\1true", s, count=1)
open("llm.yaml", "w", encoding="utf-8").write(s)
PY
echo "ok: models/model.gguf and llm.yaml ready"
