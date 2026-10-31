# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""SPEC 4.7 - the LLM boundary, and SPEC 4.3 - constrained generation.

The model does two things and nothing else: it picks a label (`guided_choice`)
and it fills a schema (`guided_json`). Grammar constrained decoding makes
off-schema output impossible on the server side; every answer is re-validated
here anyway, so a broken, downgraded or remote backend cannot leak free-form
text into the system. `summarize` is the single free-form path and its output
is `HumanText`, which cannot be used as prompt input.
"""

import asyncio
import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Protocol

import httpx
import jsonschema
import yaml

from neml_brain.api.metrics import LLM_LATENCY, LLM_REQUESTS
from neml_brain.llm import untrusted
from neml_brain.llm.profiles import PROFILES, HumanText
from neml_brain.paths import CONFIG_DIR

CONFIG_PATH = CONFIG_DIR / "llm.yaml"


class SchemaViolation(RuntimeError):
    """Model output left its grammar. It is dropped here, never passed upstream."""


@contextmanager
def _measured(profile: str) -> Iterator[None]:
    """SPEC 18.3: one count per request with its outcome, plus its latency."""
    started = time.monotonic()
    outcome = "ok"
    try:
        yield
    except SchemaViolation:
        outcome = "schema_violation"
        raise
    except BaseException:
        outcome = "error"
        raise
    finally:
        LLM_REQUESTS.labels(profile=profile, outcome=outcome).inc()
        LLM_LATENCY.labels(profile=profile).observe(time.monotonic() - started)


class LLMProvider(Protocol):
    async def classify(self, prompt: str, choices: list[str]) -> str: ...
    async def fill(self, prompt: str, schema: dict) -> dict: ...  # type: ignore[type-arg]
    async def summarize(self, prompt: str, max_tokens: int) -> str: ...


class _OpenAIChatProvider:
    """Shared OpenAI compatible /v1/chat/completions plumbing and validation.

    Subclasses only decide how their backend is told about the constraint.
    """

    # seconds to wait before each retry of a 5xx / refused call
    BUSY_WAITS: tuple[float, ...] = (15.0, 45.0, 120.0)

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_s: float = 120.0,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._api_key = api_key
        self._client = client or httpx.AsyncClient(timeout=timeout_s)

    # --- backend specific -------------------------------------------------
    def _choice_body(self, choices: list[str]) -> dict[str, Any]:
        raise NotImplementedError

    def _json_body(self, schema: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def _decode(self, obj: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
        """Undo any schema rewriting `_json_body` did; the result is validated against `schema`."""
        return obj

    # --- shared -----------------------------------------------------------
    async def aclose(self) -> None:
        await self._client.aclose()

    async def _chat(
        self,
        profile: str,
        prompt: str,
        extra: dict[str, Any],
        max_tokens: int | None = None,
        temperature: float = 0.0,
    ) -> str:
        untrusted.check(prompt)  # SPEC 5.4
        spec = PROFILES[profile]
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens or spec.max_tokens,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": spec.system_prompt},
                {"role": "user", "content": prompt},
            ],
            **extra,
        }
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        for wait in (*self.BUSY_WAITS, None):  # a busy or restarting server is waited out
            try:
                response = await self._client.post(
                    f"{self.base_url}/chat/completions", json=body, headers=headers
                )
                if response.status_code < 500:
                    break
                error: Exception = httpx.HTTPStatusError(
                    f"server error {response.status_code}",
                    request=response.request,
                    response=response,
                )
            except (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError) as exc:
                error = exc
            if wait is None:
                raise error
            await asyncio.sleep(wait)
        response.raise_for_status()
        try:
            return response.json()["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise SchemaViolation(f"malformed chat completion response: {exc}") from exc

    async def classify(self, prompt: str, choices: list[str], profile: str = "router") -> str:
        if PROFILES[profile].constraint != "guided_choice":
            raise ValueError(f"SPEC 4.4: profile {profile} does not classify")
        if not choices:
            raise ValueError("classify needs a non-empty choice list")
        with _measured(profile):
            # The decoder is constrained to `choices`, but the model never sees them otherwise.
            untrusted.check(prompt)  # before the f-string below drops the HumanText type
            shown = f"{prompt}\n\nAllowed labels: {', '.join(choices)}"
            text = (await self._chat(profile, shown, self._choice_body(choices))).strip()
            if text not in choices:
                raise SchemaViolation(
                    f"label {text[:80]!r} is not one of the {len(choices)} choices"
                )
            return text

    async def fill(
        self,
        prompt: str,
        schema: dict[str, Any],
        profile: str = "param_mech",
        max_tokens: int | None = None,
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        if PROFILES[profile].constraint != "guided_json":
            raise ValueError(f"SPEC 4.4: profile {profile} does not fill parameters")
        with _measured(profile):
            raw = await self._chat(
                profile, prompt, self._json_body(schema), max_tokens, temperature
            )
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise SchemaViolation(f"output is not JSON: {raw[:80]!r}") from exc
            if not isinstance(obj, dict):
                raise SchemaViolation(f"output is {type(obj).__name__}, expected an object")
            obj = self._decode(obj, schema)
            # best_match names the failing field ("params/width_mm: 2.4 is less than the minimum
            # of 12"); the bare oneOf message ("not valid under any of the given schemas") does not.
            error = jsonschema.exceptions.best_match(
                jsonschema.Draft202012Validator(schema).iter_errors(obj)
            )
            if error is not None:
                where = "/".join(str(part) for part in error.absolute_path)
                raise SchemaViolation(
                    f"off-schema output: {error.message}" + (f" (at {where})" if where else "")
                )
            return obj

    async def summarize(self, prompt: str, max_tokens: int) -> str:
        # SPEC 4.4: the only free-form profile, capped at its own budget, and the
        # result is tagged so it can never be fed back in.
        spec = PROFILES["summarize"]
        if max_tokens > spec.max_tokens:
            max_tokens = spec.max_tokens
        with _measured("summarize"):
            return HumanText(await self._chat("summarize", prompt, {"max_tokens": max_tokens}))


class VllmProvider(_OpenAIChatProvider):
    """SPEC 4.7 active provider. Guided decoding via the vLLM extension fields.

    `guided_choice` / `guided_json` are what the OpenAI SDK would smuggle in as
    `extra_body`; over raw HTTP they are top level request fields. The xgrammar
    backend is selected server side (SPEC 4.2).
    """

    def _choice_body(self, choices: list[str]) -> dict[str, Any]:
        return {"guided_choice": list(choices)}

    def _json_body(self, schema: dict[str, Any]) -> dict[str, Any]:
        return {"guided_json": schema}


class RemoteOpenAIProvider(_OpenAIChatProvider):
    """SPEC 4.7 closed path: implemented and tested, never selected by default.

    The OpenAI API has no `guided_choice`, so classification there is only
    enforced by the check in `classify()`. That is exactly why this path stays
    disabled in config/llm.yaml.
    """

    def _choice_body(self, choices: list[str]) -> dict[str, Any]:
        return {}

    def _json_body(self, schema: dict[str, Any]) -> dict[str, Any]:
        return {
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "neml_params", "strict": True, "schema": schema},
            }
        }


class LlamaCppProvider(_OpenAIChatProvider):
    """CPU / GPU-less hosts: llama.cpp's server speaks the OpenAI chat API but not vLLM's
    `guided_*` fields. Classification is pinned with a GBNF grammar, parameters with a JSON
    schema, so both stay grammar-constrained exactly as with xgrammar (SPEC 4.2).
    """

    # llama.cpp turns integer bounds into grammar but not the min/max of a `number`, so a small
    # model can answer 1e15 for a field capped at 1000. The reply is still validated; one retry
    # tells the model what was wrong (a retry at temperature 0 with the same prompt would not).
    RETRIES = 1

    async def fill(
        self,
        prompt: str,
        schema: dict[str, Any],
        profile: str = "param_mech",
        max_tokens: int | None = None,
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        last: SchemaViolation | None = None
        for _ in range(self.RETRIES + 1):
            hint = (
                f"\n\nYour previous answer was rejected: {last}. Answer again within the limits."
                if last
                else ""
            )
            try:
                return await super().fill(prompt + hint, schema, profile, max_tokens, temperature)
            except SchemaViolation as exc:
                last = exc
        raise last  # type: ignore[misc]  # RETRIES + 1 >= 1, so the loop ran and set it

    def _choice_body(self, choices: list[str]) -> dict[str, Any]:
        return {"grammar": "root ::= " + " | ".join(json.dumps(c) for c in choices)}

    def _json_body(self, schema: dict[str, Any]) -> dict[str, Any]:
        return {
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "neml_params",
                    "strict": True,
                    "schema": _digits_for_bounded_numbers(schema),
                },
            }
        }

    def _decode(self, obj: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
        decoded = _numbers_from_digits(obj, schema)
        return decoded if isinstance(decoded, dict) else obj


def _is_bounded_number(schema: Any) -> bool:
    return (
        isinstance(schema, dict)
        and schema.get("type") in ("number", "integer")
        and "maximum" in schema
        and schema.get("minimum", -1) >= 0
    )


def _digits_for_bounded_numbers(schema: Any) -> Any:
    """llama.cpp has no grammar for the min/max of a `number`: a 4B+ model happily writes 1e15 for
    a field capped at 1000. A non-negative bounded number becomes a digit-limited string
    (`[0-9]{1,N}` plus decimals for floats); `_numbers_from_digits` converts it back and the
    original bounds are still checked afterwards."""
    if _is_bounded_number(schema):
        digits = len(str(int(schema["maximum"])))
        decimals = "" if schema["type"] == "integer" else r"(\.[0-9]{1,3})?"
        return {"type": "string", "pattern": f"^[0-9]{{1,{digits}}}{decimals}$"}
    if isinstance(schema, dict):
        return {k: _digits_for_bounded_numbers(v) for k, v in schema.items()}
    if isinstance(schema, list):
        return [_digits_for_bounded_numbers(v) for v in schema]
    return schema


def _numbers_from_digits(value: Any, schema: Any, root: Any = None) -> Any:
    if not isinstance(schema, dict):
        return value
    root = schema if root is None else root
    ref = schema.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/"):
        target: Any = root
        for part in ref[2:].split("/"):
            target = target.get(part, {}) if isinstance(target, dict) else {}
        return _numbers_from_digits(value, target, root)
    for key in ("anyOf", "oneOf"):
        branches = schema.get(key)
        if branches:
            first = _numbers_from_digits(value, branches[0], root)
            for branch in branches:
                candidate = _numbers_from_digits(value, branch, root)
                # `$ref` inside a branch needs the root for the validity check too
                if jsonschema.Draft202012Validator(
                    {"$defs": root.get("$defs", {}), **branch}
                ).is_valid(candidate):
                    return candidate
            return first
    if _is_bounded_number(schema) and isinstance(value, str):
        try:
            return int(value) if schema["type"] == "integer" else float(value)
        except ValueError:
            return value  # left as a string: the schema check rejects it
    if isinstance(value, dict):
        props = schema.get("properties", {})
        return {k: _numbers_from_digits(v, props.get(k), root) for k, v in value.items()}
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        return [_numbers_from_digits(v, schema["items"], root) for v in value]
    return value


def load_provider(config: dict[str, Any] | None = None) -> LLMProvider:
    """Build the provider named by config/llm.yaml (SPEC 4.7, default: vllm)."""
    if config is None:
        config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    name = config["provider"]
    settings = config["providers"][name]
    if not settings.get("enabled", False):
        raise ValueError(f"config/llm.yaml selects provider {name!r} but it is disabled")
    base_url = os.path.expandvars(settings["base_url"])
    if "$" in base_url:
        raise ValueError(f"unresolved environment variable in base_url: {settings['base_url']}")
    timeout_s = float(settings.get("request_timeout_s", 120))
    if name == "vllm":
        return VllmProvider(base_url, settings["model"], timeout_s)
    if name == "llama_cpp":
        return LlamaCppProvider(base_url, settings["model"], timeout_s)
    if name == "remote_openai":
        # SPEC 5.4: the key lives in the process environment, never in config.
        return RemoteOpenAIProvider(
            base_url, settings["model"], timeout_s, api_key=os.environ[settings["api_key_env"]]
        )
    raise ValueError(f"unknown provider {name!r}")
