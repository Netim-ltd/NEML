# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Build-time model preparation for neml-embed (SPEC 4.6).

Exports `intfloat/multilingual-e5-small` to ONNX and quantises the weights to
int8. Runs once in the builder stage; the runtime image gets two files
(model_int8.onnx, tokenizer.json) and never sees torch or transformers.

Usage: python prepare_model.py /opt/neml/embed-model
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

from onnxruntime.quantization import QuantType, quantize_dynamic
from optimum.onnxruntime import ORTModelForFeatureExtraction
from transformers import AutoTokenizer

MODEL_ID = "intfloat/multilingual-e5-small"


def main(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        exported = Path(tmp)
        ORTModelForFeatureExtraction.from_pretrained(MODEL_ID, export=True).save_pretrained(exported)
        AutoTokenizer.from_pretrained(MODEL_ID).save_pretrained(exported)
        quantize_dynamic(
            exported / "model.onnx", out_dir / "model_int8.onnx", weight_type=QuantType.QInt8
        )
        shutil.copy(exported / "tokenizer.json", out_dir / "tokenizer.json")
    size_mb = (out_dir / "model_int8.onnx").stat().st_size / 1e6
    print(f"{MODEL_ID} -> {out_dir}/model_int8.onnx ({size_mb:.1f} MB, int8, CPU)")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "/opt/neml/embed-model"))
