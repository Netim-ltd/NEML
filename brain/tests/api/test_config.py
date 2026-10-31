# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Settings and config loaders (SPEC 17.3) and the JSON log line (SPEC 8.1).

These cover neml_brain/config.py and neml_brain/logging.py, which the API
depends on. They live under tests/api/ because that is the test tree that
ships with this change.
"""

from __future__ import annotations

import json
import string
from pathlib import Path
from typing import Any

import pytest
import structlog
from pydantic import ValidationError

from neml_brain import config as config_module
from neml_brain.config import (
    Settings,
    budget_config,
    llm_config,
    load_config,
    mcp_config,
    tool_policy,
)
from neml_brain.logging import (
    bind_correlation_id,
    configure_logging,
    current_correlation_id,
)

# SPEC 17.3, lab block. Every one of these is required.
ENV = {
    "NEML_ENV": "lab",
    "NEML_DB_URL": "postgresql+asyncpg://neml:pw@localhost:5432/neml_local",
    "NEML_VLLM_URL": "http://localhost:8000/v1",
    "NEML_EMBED_URL": "http://localhost:8081",
    "NEML_MODEL": "Qwen/Qwen2.5-Coder-1.5B-Instruct-AWQ",
    "NEML_WORK_DIR": "/srv/neml/work",
    "NEML_ARTIFACT_DIR": "/srv/neml/artifacts",
    "NEML_OUTBOX_DB": "/var/lib/neml/outbox.db",
    "NEML_CLOUD_WS": "wss://api.neml.example.com/bridge/ws",
    "NEML_NODE_ID": "lab-01",
    "NEML_API_KEY": "s3cret",
}


@pytest.fixture(autouse=True)
def _restore_structlog() -> Any:
    """configure_logging() is global and binds the stream it was given. Under
    capsys that stream is closed at teardown, so leaving it configured would
    break every later test that logs."""
    yield
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_every_spec_variable_is_read(settings: Settings) -> None:
    assert settings.db_url == ENV["NEML_DB_URL"]
    assert settings.vllm_url == ENV["NEML_VLLM_URL"]
    assert settings.embed_url == ENV["NEML_EMBED_URL"]
    assert settings.llm_model == ENV["NEML_MODEL"]
    assert settings.work_dir == Path(ENV["NEML_WORK_DIR"])
    assert settings.artifact_dir == Path(ENV["NEML_ARTIFACT_DIR"])
    assert settings.outbox_db == Path(ENV["NEML_OUTBOX_DB"])
    assert settings.cloud_ws == ENV["NEML_CLOUD_WS"]
    assert settings.node_id == ENV["NEML_NODE_ID"]
    assert settings.api_key.get_secret_value() == ENV["NEML_API_KEY"]
    assert set(settings.as_env()) == set(ENV)


def test_secret_is_not_in_the_repr(settings: Settings) -> None:
    assert ENV["NEML_API_KEY"] not in repr(settings)


@pytest.mark.parametrize("missing", sorted(set(ENV) - {"NEML_ENV"}))
def test_missing_setting_fails_loudly(monkeypatch: pytest.MonkeyPatch, missing: str) -> None:
    """No silent default for a URL, a path or a secret (SPEC 17.3)."""
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv(missing)
    with pytest.raises(ValidationError) as caught:
        Settings(_env_file=None)  # type: ignore[call-arg]
    assert missing in str(caught.value)


def test_env_defaults_to_lab(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("NEML_ENV")
    assert Settings(_env_file=None).env == "lab"  # type: ignore[call-arg]


def test_repo_config_files_parse(settings: Settings) -> None:
    """The four files this service loads at startup, as they are in the repo."""
    assert llm_config(settings)["provider"] == "vllm"
    assert len(llm_config(settings)["intents"]) == 12  # SPEC 4.3 INTENT list
    assert set(mcp_config(settings)["servers"]) >= {"sim", "fab", "genome", "postgres"}
    assert budget_config(settings)["limits"]["llm_tokens"]["limit"] == 500_000
    assert "db.write_raw" in tool_policy(settings)["global_forbidden"]


def test_placeholders_are_expanded(settings: Settings) -> None:
    """config/llm.yaml carries ${NEML_VLLM_URL}; a literal one would be a
    broken base_url that only fails on the first model call."""
    loaded = llm_config(settings)
    assert loaded["providers"]["vllm"]["base_url"] == ENV["NEML_VLLM_URL"]
    assert loaded["embedding"]["url"] == ENV["NEML_EMBED_URL"]
    assert "${" not in json.dumps(loaded)


def test_unknown_placeholder_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    (tmp_path / "broken.yaml").write_text("url: ${NEML_NOT_A_THING}\n", encoding="utf-8")
    monkeypatch.setattr(config_module, "CONFIG_DIR", tmp_path)
    with pytest.raises(KeyError):
        load_config("broken.yaml", settings)


def test_missing_config_file_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    monkeypatch.setattr(config_module, "CONFIG_DIR", tmp_path)
    with pytest.raises(FileNotFoundError):
        load_config("llm.yaml", settings)


def test_non_mapping_config_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    (tmp_path / "list.yaml").write_text("- a\n- b\n", encoding="utf-8")
    monkeypatch.setattr(config_module, "CONFIG_DIR", tmp_path)
    with pytest.raises(ValueError, match="mapping"):
        load_config("list.yaml", settings)


def test_log_line_is_json_with_correlation_id(capsys: pytest.CaptureFixture[str]) -> None:
    """SPEC 8.1/18.3 - one JSON object per line, carrying the audit key."""
    configure_logging()
    structlog.contextvars.clear_contextvars()
    correlation_id = bind_correlation_id()
    assert current_correlation_id() == correlation_id

    structlog.get_logger("test").info("tool_call", tool="cad.generate", outcome="ok")
    line = capsys.readouterr().out.strip().splitlines()[-1]
    record: dict[str, Any] = json.loads(line)
    assert record["event"] == "tool_call"
    assert record["tool"] == "cad.generate"
    assert record["level"] == "info"
    assert record["correlation_id"] == correlation_id
    assert record["timestamp"].endswith("Z")


def test_correlation_id_is_hex_and_stable() -> None:
    structlog.contextvars.clear_contextvars()
    assert current_correlation_id() is None
    given = bind_correlation_id("abc123")
    assert given == "abc123"
    minted = bind_correlation_id()
    assert len(minted) == 32
    assert set(minted) <= set(string.hexdigits)
