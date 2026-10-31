# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
FROM pytorch/pytorch:2.7.1-cuda12.6-cudnn9-runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/opt/neml/brain

WORKDIR /opt/neml
COPY scripts/platform/requirements-lora.txt /tmp/requirements-lora.txt
RUN python -m pip install --no-cache-dir -r /tmp/requirements-lora.txt 'cryptography>=42'
COPY brain/neml_brain /opt/neml/brain/neml_brain
COPY scripts/platform/nightly_lora.py scripts/platform/lora_worker.py \
     scripts/platform/build_feedback_dataset.py scripts/platform/pull_feedback.py \
     /opt/neml/scripts/platform/

RUN useradd --create-home --uid 10001 neml
USER neml
ENTRYPOINT ["python", "/opt/neml/scripts/platform/nightly_lora.py"]
CMD ["--root", "/training"]
