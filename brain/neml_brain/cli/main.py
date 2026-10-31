# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""nemlctl - thin CLI over the lab brain REST API (SPEC 8.3, task T-020).

It owns no logic: every command is one HTTP call to :8080 plus a Rich table.
Errors come back as RFC 7807 problem+json and are printed as-is.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx
import typer
from rich.console import Console
from rich.table import Table

BASE_URL = os.environ.get("NEML_BRAIN_URL", "http://localhost:8080").rstrip("/")
TIMEOUT_S = 30.0

console = Console()
app = typer.Typer(help="NEML laboratuvar kontrol aracı.", no_args_is_help=True)
task_app = typer.Typer(help="Görev işlemleri.", no_args_is_help=True)
approve_app = typer.Typer(help="Onay kuyruğu (SPEC 5.2).", no_args_is_help=True)
robot_app = typer.Typer(help="Robot işlemleri.", no_args_is_help=True)
app.add_typer(task_app, name="task")
app.add_typer(approve_app, name="approve")
app.add_typer(robot_app, name="robot")


# --------------------------------------------------------------------------- transport


def _request(method: str, path: str, **kwargs: Any) -> Any:
    """One call against the brain. Exit 2 = unreachable, exit 1 = API said no."""
    try:
        response = httpx.request(method, f"{BASE_URL}{path}", timeout=TIMEOUT_S, **kwargs)
    except httpx.HTTPError as exc:
        console.print(f"[red]beyin API'sine ulaşılamadı[/red] ({BASE_URL}): {exc}")
        raise typer.Exit(2) from exc
    if response.status_code >= 400:
        _print_problem(response)
        raise typer.Exit(1)
    return response.json() if response.content else None


def _print_problem(response: httpx.Response) -> None:
    """RFC 7807 application/problem+json."""
    try:
        problem = response.json()
    except ValueError:
        problem = {}
    title = problem.get("title") or response.reason_phrase or "hata"
    detail = problem.get("detail") or response.text[:300]
    console.print(f"[red]{response.status_code} {title}[/red] {detail}")


def _json_arg(value: str) -> dict[str, Any]:
    """JSON text, or the path to a JSON file."""
    path = Path(value)
    if path.is_file():
        value = path.read_text(encoding="utf-8")
    try:
        parsed = json.loads(value)
    except ValueError as exc:
        raise typer.BadParameter(f"geçersiz JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise typer.BadParameter("JSON nesnesi bekleniyor")
    return parsed


# --------------------------------------------------------------------------- rendering


def _rows(payload: Any) -> list[dict[str, Any]]:
    """A list, an {"items": [...]} envelope or a {name: {...}} mapping -> rows."""
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    items = payload.get("items")
    if isinstance(items, list):
        return items
    return [
        {"resource": key, **value} if isinstance(value, dict) else {"resource": key, "used": value}
        for key, value in payload.items()
    ]


def _cell(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _table(title: str, rows: list[dict[str, Any]], columns: tuple[str, ...]) -> None:
    table = Table(title=title)
    for column in columns:
        table.add_column(column)
    for row in rows:
        table.add_row(*(_cell(row.get(column)) for column in columns))
    console.print(table)
    if not rows:
        console.print("[dim]kayıt yok[/dim]")


def _kv(title: str, data: dict[str, Any]) -> None:
    table = Table(title=title)
    table.add_column("alan")
    table.add_column("değer")
    for key, value in data.items():
        table.add_row(key, _cell(value))
    console.print(table)


# --------------------------------------------------------------------------- status


@app.command("status")
def status() -> None:
    """Beyin sağlığı, model, GPU sahibi ve günlük bütçe kullanımı."""
    health = _request("GET", "/health")
    table = Table(title="NEML durum")
    table.add_column("alan")
    table.add_column("değer")
    table.add_row("beyin", _cell(health.get("status")))
    table.add_row("model", _cell(health.get("model")))
    table.add_row("gpu", _cell(health.get("gpu_owner")))
    for name, state in (health.get("components") or {}).items():
        table.add_row(name, _cell(state))
    console.print(table)
    _table(
        "Bütçe (SPEC 14.4)",
        _rows(_request("GET", "/v1/budget")),
        ("resource", "used", "limit", "ratio"),
    )


# --------------------------------------------------------------------------- task


@task_app.command("list")
def task_list(
    state: str | None = typer.Option(None, help="queued|planning|running|..."),
    kind: str | None = typer.Option(None, help="human|repair|exploration|..."),
    limit: int = typer.Option(50, help="Azami satır."),
) -> None:
    """Görevleri listeler."""
    filters = (("state", state), ("kind", kind), ("limit", limit))
    params = {k: v for k, v in filters if v is not None}
    _table(
        "Görevler",
        _rows(_request("GET", "/v1/tasks", params=params)),
        ("id", "title", "kind", "state", "priority", "robot_id"),
    )


@task_app.command("create")
def task_create(
    title: str = typer.Argument(..., help="Görev başlığı."),
    kind: str = typer.Option("human", help="SPEC 7 tasks.kind"),
    priority: float = typer.Option(1.0),
    robot: str | None = typer.Option(None, help="Robot kimliği."),
    spec: str = typer.Option("{}", help="JSON metni ya da .json yolu."),
) -> None:
    """Yeni görev oluşturur."""
    body: dict[str, Any] = {
        "title": title,
        "kind": kind,
        "source": f"user:{os.environ.get('USERNAME') or os.environ.get('USER') or 'cli'}",
        "priority": priority,
        "spec": _json_arg(spec),
    }
    if robot:
        body["robot_id"] = robot
    created = _request("POST", "/v1/tasks", json=body)
    console.print(f"[green]oluşturuldu[/green] {_cell((created or {}).get('id'))}")


@task_app.command("cancel")
def task_cancel(task_id: str = typer.Argument(..., help="Görev kimliği.")) -> None:
    """Görevi iptal eder."""
    _request("DELETE", f"/v1/tasks/{task_id}")
    console.print(f"[yellow]iptal edildi[/yellow] {task_id}")


@task_app.command("show")
def task_show(task_id: str = typer.Argument(..., help="Görev kimliği.")) -> None:
    """Görev detayını ve koşu geçmişini gösterir."""
    _kv(f"Görev {task_id}", _request("GET", f"/v1/tasks/{task_id}") or {})
    _table(
        "Koşular",
        _rows(_request("GET", f"/v1/tasks/{task_id}/runs")),
        ("attempt", "env", "seed", "started_at", "ended_at", "outcome"),
    )


# --------------------------------------------------------------------------- robot


@robot_app.command("safety-check")
def robot_safety_check(
    robot_id: str = typer.Argument(..., help="Robot kimliği, örn. R01."),
    estop: bool = typer.Option(..., "--estop/--no-estop", help="E-stop testi geçti mi."),
    watchdog: bool = typer.Option(..., "--watchdog/--no-watchdog", help="Watchdog 150 ms testi."),
    current_limit: bool = typer.Option(
        ..., "--current-limit/--no-current-limit", help="Akım limiti testi."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Soru sorma."),
) -> None:
    """SAFETY.md bölüm 0: tezgâhta yapılan testin sonucunu kaydeder.

    Üç bayrak da açıkça verilmeli; varsayılan yoktur çünkü bu bir beyandır. Başarısız
    test de kaydedilir: en yeni kayıt belirleyicidir ve önceki geçişi geçersiz kılar.
    """
    who = os.environ.get("USERNAME") or os.environ.get("USER") or "cli"
    if not yes:
        typer.confirm(
            f"{robot_id}: e-stop={estop} watchdog={watchdog} akım-limiti={current_limit}. "
            f"Bu testi {who} olarak bizzat yaptığınızı beyan ediyor musunuz?",
            abort=True,
        )
    result = _request(
        "POST",
        f"/v1/robots/{robot_id}/safety-check",
        json={
            "estop_ok": estop,
            "watchdog_ok": watchdog,
            "current_limit_ok": current_limit,
            "performed_by": who,
        },
    )
    passed = bool((result or {}).get("passed"))
    console.print(
        f"[green]kaydedildi: geçti[/green] {robot_id}"
        if passed
        else f"[red]kaydedildi: BAŞARISIZ[/red] {robot_id} — fiziksel görevler reddedilecek"
    )


# --------------------------------------------------------------------------- approve


@approve_app.command("list")
def approve_list() -> None:
    """Bekleyen onayları listeler."""
    _table(
        "Bekleyen onaylar",
        _rows(_request("GET", "/v1/approvals")),
        ("id", "level", "subject_kind", "subject_id", "requested_at", "expires_at"),
    )


@approve_app.command("show")
def approve_show(approval_id: str = typer.Argument(..., help="Onay kimliği.")) -> None:
    """Onay detayını gösterir."""
    _kv(f"Onay {approval_id}", _request("GET", f"/v1/approvals/{approval_id}") or {})


def _decide(approval_id: str, decision: str, note: str | None, yes: bool) -> None:
    # The human gate of SPEC 5.2 is enforced server-side; this prompt only stops a
    # fat-fingered level-4 approval leaving the terminal.
    if not yes:
        typer.confirm(f"{approval_id} -> {decision}. Onaylıyor musunuz?", abort=True)
    _request(
        "POST",
        f"/v1/approvals/{approval_id}/decide",
        json={
            "decision": decision,
            "note": note,
            "decided_by": os.environ.get("USERNAME") or os.environ.get("USER") or "cli",
        },
    )
    console.print(f"[green]{decision}[/green] {approval_id}")


@approve_app.command("approve")
def approve_approve(
    approval_id: str = typer.Argument(..., help="Onay kimliği."),
    note: str | None = typer.Option(None, help="Karar notu."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Soru sorma."),
) -> None:
    """Onayı verir."""
    _decide(approval_id, "approved", note, yes)


@approve_app.command("reject")
def approve_reject(
    approval_id: str = typer.Argument(..., help="Onay kimliği."),
    note: str | None = typer.Option(None, help="Karar notu."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Soru sorma."),
) -> None:
    """Onayı reddeder."""
    _decide(approval_id, "rejected", note, yes)


if __name__ == "__main__":
    app()
