# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Can the whole SPEC 8.2 module tree be imported?

The cheapest broken-package sentry: a syntax error or a missing sibling module
fails right here instead of somewhere far away.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import pkgutil
import random
from collections.abc import Callable
from typing import Any

import httpx
import jsonschema
import pytest

import neml_brain

from .conftest import FROZEN_NOW, SEED, FakeLLM, FrozenClock

# SPEC 8.2 module tree.
SPEC_PACKAGES = (
    "api",
    "agents",
    "llm",
    "generators",
    "mcp",
    "memory",
    "evolution",
    "runtime",
    "safety",
    "bridge",
    "db",
    "autonomy",
    "cli",
)


def test_spec_8_2_packages_exist() -> None:
    missing = [
        name for name in SPEC_PACKAGES if importlib.util.find_spec(f"neml_brain.{name}") is None
    ]
    assert not missing, f"SPEC 8.2 alt paketleri eksik: {missing}"


def test_every_module_imports() -> None:
    failures: dict[str, str] = {}
    missing_deps: dict[str, str] = {}
    for info in pkgutil.walk_packages(neml_brain.__path__, "neml_brain.", onerror=lambda _: None):
        try:
            importlib.import_module(info.name)
        except ModuleNotFoundError as exc:
            # ponytail: a third-party wheel missing from this box is an environment
            # problem, not a broken package. Only neml_brain-level breakage fails here.
            if (exc.name or "").startswith("neml_brain"):
                failures[info.name] = f"{type(exc).__name__}: {exc}"
            else:
                missing_deps[info.name] = exc.name or "?"
        except Exception as exc:  # noqa: BLE001 - every import error is a failure
            failures[info.name] = f"{type(exc).__name__}: {exc}"
    assert not failures, f"import edilemeyen modüller: {failures} (atlanan: {missing_deps})"


def test_cli_app_is_wired() -> None:
    from neml_brain.cli.main import app

    groups = {group.name for group in app.registered_groups}
    commands = {command.name for command in app.registered_commands}
    assert groups == {"task", "approve", "robot"}
    assert "status" in commands


# ------------------------------------------------------------------ conftest fixtures


def test_clock_rng_and_artifact_dir(
    clock: FrozenClock, rng: random.Random, artifact_dir: Any
) -> None:
    assert clock.now() == clock.now() == FROZEN_NOW
    assert clock.advance(60) > FROZEN_NOW
    assert rng.random() == random.Random(SEED).random()  # noqa: S311
    assert artifact_dir.is_dir()
    assert os.environ["NEML_ARTIFACT_DIR"] == str(artifact_dir)


async def _ok_app(scope: Any, receive: Any, send: Any) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send({"type": "http.response.body", "body": b'{"status":"ok"}'})


async def test_client_factory_talks_to_an_asgi_app(
    client_factory: Callable[..., httpx.AsyncClient],
) -> None:
    response = await client_factory(_ok_app).get("/health")
    assert response.json() == {"status": "ok"}


async def test_fake_llm_enforces_guided_decoding(fake_llm: FakeLLM) -> None:
    assert await fake_llm.classify("p", ["a", "b"]) == "a"
    fake_llm.choice = "kod üret"
    with pytest.raises(AssertionError):
        await fake_llm.classify("p", ["a", "b"])  # SPEC 4.3: the enum cannot be escaped

    schema = {"type": "object", "required": ["n"], "properties": {"n": {"type": "integer"}}}
    fake_llm.fill_value = {"n": 3}
    assert await fake_llm.fill("p", schema) == {"n": 3}
    fake_llm.fill_value = {"n": "üç"}
    with pytest.raises(jsonschema.ValidationError):
        await fake_llm.fill("p", schema)  # SPEC 4.3: output outside the schema is impossible

    fake_llm.summary_text = "x" * 20
    assert await fake_llm.summarize("p", max_tokens=2) == "x" * 8
    assert [kind for kind, _ in fake_llm.calls] == [
        "classify",
        "classify",
        "fill",
        "fill",
        "summarize",
    ]
