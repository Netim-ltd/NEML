# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Lifespan duman testi (SPEC 8.1).

`docker/compose.yml` beyni `uvicorn neml_brain.main:app` ile başlatır. Sözleşme
testleri servisleri `app.state`'e kendileri koyduğu için lifespan'ı hiç
çalıştırmaz; bu dosya onu gerçekten çalıştırır, yani main.py'nin import'ları ve
kurucu çağrıları bozulursa test kırmızıya döner.

Ağ yok: veritabanı, vLLM, MCP ve bulut köprüsü kapalı portlara bakar. Bileşenler
`down` raporlanır ama süreç ayağa kalkar ve temiz kapanır -- ölçülen budur.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from neml_brain.config import get_settings
from neml_brain.db.session import get_engine, get_sessionmaker
from neml_brain.main import create_app

CLOSED = "127.0.0.1:1"  # bağlantı anında reddedilir, test beklemez


@pytest.fixture
def lab_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name, value in {
        "NEML_ENV": "test",
        "NEML_DB_URL": f"postgresql+asyncpg://neml:neml@{CLOSED}/neml_local",
        "NEML_VLLM_URL": f"http://{CLOSED}/v1",
        "NEML_EMBED_URL": f"http://{CLOSED}",
        "NEML_MODEL": "Qwen/Qwen2.5-Coder-1.5B-Instruct-AWQ",
        "NEML_WORK_DIR": str(tmp_path / "work"),
        "NEML_ARTIFACT_DIR": str(tmp_path / "artifacts"),
        "NEML_OUTBOX_DB": str(tmp_path / "outbox.db"),
        "NEML_CLOUD_WS": f"ws://{CLOSED}/bridge/ws",
        "NEML_NODE_ID": "lab-test",
        "NEML_API_KEY": "test-key",
    }.items():
        monkeypatch.setenv(name, value)
    for cached in (get_settings, get_engine, get_sessionmaker):
        cached.cache_clear()
    yield
    for cached in (get_settings, get_engine, get_sessionmaker):
        cached.cache_clear()


def test_lifespan_starts_and_stops(lab_env: None) -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health")
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    # Hiçbir bileşen ayakta değil, ama hepsi isimleriyle raporlanır.
    assert body["status"] == "degraded"
    assert set(body["components"]) == {"db", "llm", "mcp", "bridge", "budget"}
    assert {"db", "llm"} <= set(body["degraded"])
    # ADR-011 bütçeyi veritabanında tutar; DB kapalıyken durum da degraded olur.
    assert body["components"]["budget"]["status"] == "down"


def test_every_wired_service_is_on_app_state(lab_env: None) -> None:
    """api/deps.py'nin `app.state`'ten aldığı isimler lifespan'da gerçekten kurulur."""
    app = create_app()
    with TestClient(app):
        for name in (
            "repo",
            "llm",
            "mcp",
            "sim",
            "budget",
            "gpu_lock",
            "safety",
            "bridge",
            "orchestrator",
        ):
            assert getattr(app.state, name, None) is not None, name
