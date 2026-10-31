# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Verified robot recoveries flow into task-specific offline training data."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neml_brain.api.platform import router
from neml_brain.api.problem import install_error_handlers
from neml_brain.platform.feedback import (
    attest_recovery,
    sign_report,
    training_pair,
    verify_report,
)
from neml_brain.platform.task_models import OperationModels

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts" / "platform"
sys.path.insert(0, str(SCRIPTS))
from build_feedback_dataset import build  # noqa: E402
from lora_worker import load_pairs  # noqa: E402
from nightly_lora import load_job  # noqa: E402
from pull_feedback import pull  # noqa: E402


def public(key: Ed25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )


def report(index: int) -> dict:
    return {
        "tenant_id": "firm",
        "domain_id": "field",
        "robot_id": "robot-1",
        "robot_type": "field",
        "operation": "recovery",
        "report_id": str(uuid4()),
        "occurred_at": datetime.now(UTC).isoformat(),
        "features": [index / 100],
        "failed_action": "forward",
        "failure_class": "obstacle",
        "recovery_action": "stop",
        "outcome": "success",
        "quality": 0.99,
        "verifier_id": "sensor-1",
    }


def test_report_requires_independent_verified_recovery() -> None:
    robot, verifier = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    row = report(1)
    row["robot_signature"] = sign_report(row, robot)
    with pytest.raises(PermissionError):
        attest_recovery(row, public(robot), verifier, lambda _: False)
    accepted = attest_recovery(row, public(robot), verifier, lambda _: True)
    verify_report(accepted, public(robot), public(verifier))
    assert training_pair(accepted)["completion"] == "stop"
    accepted["recovery_action"] = "forward"
    with pytest.raises((PermissionError, ValueError)):
        verify_report(accepted, public(robot), public(verifier))


def test_day_reports_become_night_dataset(tmp_path: Path) -> None:
    robot, verifier = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    domain = tmp_path / "tenants" / "firm" / "domains" / "field"
    reports = domain / "reports"
    reports.mkdir(parents=True)
    (domain / "trust.json").write_text(
        json.dumps(
            {
                "robots": {"robot-1": public(robot).hex()},
                "verifiers": {"sensor-1": public(verifier).hex()},
            }
        ),
        encoding="utf-8",
    )
    for index in range(100):
        row = report(index)
        row["robot_signature"] = sign_report(row, robot)
        accepted = attest_recovery(row, public(robot), verifier, lambda _: True)
        (reports / f"{accepted['report_id']}.json").write_text(
            json.dumps(accepted), encoding="utf-8"
        )
    job_path = tmp_path / "job.json"
    job_path.write_text(
        json.dumps(
            {
                "tenant": "firm",
                "domain": "field",
                "operation": "recovery",
                "source": "robot_feedback",
                "transport": "local",
                "base_model": "test/tiny",
                "base_revision": "a" * 40,
                "dataset": "tenants/firm/domains/field/datasets/recovery.jsonl",
                "output": "tenants/firm/domains/field/models/recovery",
            }
        ),
        encoding="utf-8",
    )
    job = load_job(job_path, tmp_path)
    assert build(job, tmp_path) == 100
    train, holdout = load_pairs(Path(job["dataset"]))
    assert len(train) >= 32 and len(holdout) >= 8
    assert all(item["completion"] == "stop" for item in train + holdout)


def test_feedback_api_requires_identity_and_export_key(monkeypatch: pytest.MonkeyPatch) -> None:
    class Store:
        async def record_feedback(self, row: dict) -> bool:
            return True

        async def export_feedback(self, scope, operation, after):
            assert scope.tenant_id == "firm" and operation == "recovery"
            return []

    app = FastAPI()
    install_error_handlers(app)
    app.include_router(router)
    app.state.platform_store = Store()
    monkeypatch.setenv("NEML_TENANT_ID", "firm")
    monkeypatch.setenv("NEML_TRAINING_EXPORT_KEY", "x" * 32)
    client = TestClient(app)
    assert client.post("/v1/platform/feedback", json=report(1)).status_code == 201
    params = {"tenant": "firm", "domain": "field", "operation": "recovery"}
    assert client.get("/v1/platform/feedback-export", params=params).status_code == 403
    headers = {"Authorization": "Bearer " + "x" * 32}
    assert (
        client.get("/v1/platform/feedback-export", params=params, headers=headers).json()["reports"]
        == []
    )
    params["tenant"] = "other"
    assert (
        client.get("/v1/platform/feedback-export", params=params, headers=headers).status_code
        == 403
    )


def test_gpu_pull_rechecks_exported_identity_and_signatures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    robot, verifier = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    row = report(5)
    row["robot_signature"] = sign_report(row, robot)
    accepted = attest_recovery(row, public(robot), verifier, lambda _: True)
    pages = iter(
        [
            {
                "reports": [
                    {
                        "report": accepted,
                        "robot_public_key": public(robot).hex(),
                        "verifier_public_key": public(verifier).hex(),
                    }
                ],
                "next_after": accepted["report_id"],
            },
            {"reports": [], "next_after": None},
        ]
    )

    class Response:
        status = 200

        def __init__(self, page: dict):
            self.page = page

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self, _: int) -> bytes:
            return json.dumps(self.page).encode()

    class Opener:
        def open(self, *_args, **_kwargs):
            return Response(next(pages))

    monkeypatch.setattr("pull_feedback.build_opener", lambda *_: Opener())
    monkeypatch.setenv(
        "NEML_FEEDBACK_EXPORT_URL", "https://control.example/v1/platform/feedback-export"
    )
    monkeypatch.setenv("NEML_TRAINING_EXPORT_KEY", "x" * 32)
    job = {
        "tenant": "firm",
        "domain": "field",
        "operation": "recovery",
        "dataset": str(tmp_path / "tenants/firm/domains/field/datasets/recovery.jsonl"),
    }
    assert pull(job, tmp_path) == 1
    assert build(job, tmp_path) == 1
    dataset = Path(job["dataset"]).read_text(encoding="utf-8")
    assert '"completion": "stop"' in dataset


@pytest.mark.asyncio
async def test_task_model_route_returns_advice_only(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def post(self, url, json, headers):
            assert url == "https://gpu.example/v1/operation/generate"
            assert headers["Authorization"].startswith("Bearer ")
            return httpx.Response(
                200,
                json={**json, "completion": "inspect sensor", "adapter_sha256": "a" * 64},
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: Client())
    models = OperationModels(
        '{"field/recovery":{"url":"https://gpu.example/v1/operation/generate",'
        '"adapter_sha256":"' + "a" * 64 + '"}}',
        "x" * 32,
    )
    result = await models.generate("firm", "field", "recovery", "What happened?")
    assert result == {
        "completion": "inspect sensor",
        "use": "advisory_only",
        "adapter_sha256": "a" * 64,
    }
    with pytest.raises(KeyError):
        await models.generate("firm", "field", "other", "What happened?")
