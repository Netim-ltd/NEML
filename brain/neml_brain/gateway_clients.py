# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Add, change, list and remove gateway clients (customers, products) in the clients file; the gateway picks changes up by itself.

    docker exec neml-gateway-1 python -m neml_brain.gateway_clients list
    docker exec neml-gateway-1 python -m neml_brain.gateway_clients set customer-a --max-tokens 512 --daily 100000 --priority 5
    docker exec neml-gateway-1 python -m neml_brain.gateway_clients set neml --max-tokens 16000 --new-key
    docker exec neml-gateway-1 python -m neml_brain.gateway_clients remove customer-a

`set` on a new name makes a key and prints it once; on an existing name it only changes the limits you give (--new-key rotates the key).
`list` never prints keys."""

from __future__ import annotations

import argparse
import json
import re
import secrets
from typing import Any

from neml_brain.gateway import clients_file, today, usage_book


def load() -> list[dict[str, Any]]:
    try:
        return list(json.loads(clients_file().read_text(encoding="utf-8")).get("clients", []))
    except (OSError, ValueError):
        return []


def save(rows: list[dict[str, Any]]) -> None:
    clients_file().parent.mkdir(parents=True, exist_ok=True)
    clients_file().write_text(json.dumps({"clients": rows}, indent=2), encoding="utf-8")


def set_client(rows: list[dict[str, Any]], name: str, limits: dict[str, int], new_key: bool = False) -> str | None:
    """Create or update `name`; returns the key when one was made."""
    row = next((r for r in rows if r["name"] == name), None)
    key = None
    if row is None:
        row = {"name": name, "key": "", "max_tokens": 2048, "daily_tokens": 0, "priority": 10}
        rows.append(row)
        new_key = True
    if new_key:
        key = row["key"] = secrets.token_hex(24)
    row.update({k: v for k, v in limits.items() if v is not None})
    return key


NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{1,31}$")
CONTEXT_TOKENS = 16000  # the model's context is 16K in all (prompt + answer): a longer answer cap cannot be honoured


def operate(a: dict[str, Any]) -> dict[str, Any]:
    """The lab's `gateway` operation (the web screen): action list | set | rotate | remove. Keys are never listed;
    a new or rotated key is returned once, in this answer."""
    action, name = str(a.get("action") or "list"), str(a.get("name") or "")
    rows, made = load(), None
    if action != "list":
        if not NAME.match(name):
            raise ValueError("ad: küçük harf, rakam, - veya _ (2-32 karakter)")
        if action == "remove":
            rows = [r for r in rows if r["name"] != name]
        elif action in ("set", "rotate"):
            limits = {"max_tokens": a.get("maxTokens"), "daily_tokens": a.get("dailyTokens"), "priority": a.get("priority")}
            for k, lo, hi in (("max_tokens", 1, CONTEXT_TOKENS), ("daily_tokens", 0, 10**9), ("priority", 0, 100)):
                v = limits[k]
                if v is not None and (isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi):
                    raise ValueError(f"{k}: {lo} ile {hi} arasında bir tam sayı olmalı")
            made = set_client(rows, name, limits, action == "rotate")
        else:
            raise ValueError("action: list, set, rotate ya da remove")
        save(rows)
    used = usage_book().get(today(), {})
    return {
        "clients": [
            {
                "name": r["name"],
                "max_tokens": r["max_tokens"],
                "daily_tokens": r["daily_tokens"],
                "priority": r["priority"],
                "key_hint": "…" + str(r["key"])[-4:],
                "today": {**used.get(r["name"], {"prompt": 0, "completion": 0, "requests": 0})},
            }
            for r in rows
        ],
        "new_key": {"name": name, "key": made} if made else None,
        "context_tokens": CONTEXT_TOKENS,
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="gateway_clients")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    s = sub.add_parser("set")
    s.add_argument("name")
    s.add_argument("--max-tokens", type=int)
    s.add_argument("--daily", type=int, help="tokens per UTC day, 0 = unlimited")
    s.add_argument("--priority", type=int, help="lower goes first")
    s.add_argument("--new-key", action="store_true")
    r = sub.add_parser("remove")
    r.add_argument("name")
    a = ap.parse_args(argv)
    rows = load()
    if a.cmd == "list":
        used = usage_book().get(today(), {})
        for c in rows:
            u = used.get(c["name"], {})
            print(f"{c['name']}: max_tokens={c['max_tokens']} daily={c['daily_tokens'] or 'unlimited'} priority={c['priority']} today={u.get('prompt', 0) + u.get('completion', 0)} tokens, {u.get('requests', 0)} requests")
    elif a.cmd == "remove":
        save([c for c in rows if c["name"] != a.name])
        print("removed", a.name)
    else:
        key = set_client(rows, a.name, {"max_tokens": a.max_tokens, "daily_tokens": a.daily, "priority": a.priority}, a.new_key)
        save(rows)
        print("saved", a.name)
        if key:
            print("key (shown once):", key)


if __name__ == "__main__":
    main()
