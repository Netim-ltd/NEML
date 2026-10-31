# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Process settings and on-disk configuration loaders (SPEC 17.3, 15).

Two rules drive this module:

* Every NEML_* variable of SPEC 17.3 is declared here and the ones that name a
  URL, a path or a secret have NO default. A missing one raises at import of
  the settings object, which happens during app startup -- never at the first
  request that needed it.
* The YAML files under ``config/`` are read verbatim and their ``${VAR}``
  placeholders are expanded with ``string.Template.substitute``, which raises
  on an unknown name instead of leaving a broken literal in a URL.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from string import Template
from typing import Any

import yaml
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from neml_brain.paths import CONFIG_DIR


class Settings(BaseSettings):
    """SPEC 17.3 `.env` — lab side only. The bridge/printer/.NET blocks that
    belong to other processes are deliberately not mirrored here."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", frozen=True
    )

    env: str = Field(default="lab", validation_alias="NEML_ENV")
    db_url: str = Field(validation_alias="NEML_DB_URL")
    vllm_url: str = Field(validation_alias="NEML_VLLM_URL")
    embed_url: str = Field(validation_alias="NEML_EMBED_URL")
    llm_model: str = Field(validation_alias="NEML_MODEL")
    work_dir: Path = Field(validation_alias="NEML_WORK_DIR")
    artifact_dir: Path = Field(validation_alias="NEML_ARTIFACT_DIR")
    outbox_db: Path = Field(validation_alias="NEML_OUTBOX_DB")
    cloud_ws: str = Field(validation_alias="NEML_CLOUD_WS")
    node_id: str = Field(validation_alias="NEML_NODE_ID")
    api_key: SecretStr = Field(validation_alias="NEML_API_KEY")

    def as_env(self) -> dict[str, str]:
        """The values as the env names SPEC 17.3 uses, for YAML expansion."""
        return {
            "NEML_ENV": self.env,
            "NEML_DB_URL": self.db_url,
            "NEML_VLLM_URL": self.vllm_url,
            "NEML_EMBED_URL": self.embed_url,
            "NEML_MODEL": self.llm_model,
            "NEML_WORK_DIR": str(self.work_dir),
            "NEML_ARTIFACT_DIR": str(self.artifact_dir),
            "NEML_OUTBOX_DB": str(self.outbox_db),
            "NEML_CLOUD_WS": self.cloud_ws,
            "NEML_NODE_ID": self.node_id,
            "NEML_API_KEY": self.api_key.get_secret_value(),
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Read and validate the environment once. Raises ValidationError listing
    every missing variable, which is what startup should die on."""
    return Settings()  # type: ignore[call-arg]  # values come from the environment


def load_config(name: str, settings: Settings) -> dict[str, Any]:
    """Load ``config/<name>`` with ${VAR} expanded from the settings + os.environ."""
    path = CONFIG_DIR / name
    if not path.is_file():
        raise FileNotFoundError(f"required configuration file is missing: {path}")
    environment = {**os.environ, **settings.as_env()}
    expanded = Template(path.read_text(encoding="utf-8")).substitute(environment)
    loaded = yaml.safe_load(expanded)
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} must contain a YAML mapping, got {type(loaded).__name__}")
    return loaded


def llm_config(settings: Settings) -> dict[str, Any]:
    """SPEC 4.2/4.4/4.7 — provider, profiles, intents, embedding."""
    return load_config("llm.yaml", settings)


def mcp_config(settings: Settings) -> dict[str, Any]:
    """SPEC 6.5 — MCP server URLs, timeouts, retries."""
    return load_config("mcp.yaml", settings)


def budget_config(settings: Settings) -> dict[str, Any]:
    """SPEC 14.4 — daily limits, reset time, notify ratio."""
    return load_config("budget.yaml", settings)


def tool_policy(settings: Settings) -> dict[str, Any]:
    """SPEC 5.4 — static per-agent tool policy. Never widened at runtime."""
    return load_config("policy/tools.yaml", settings)
