# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Cloud -> lab command routing, the ack contract, approval announcements, live feed."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from neml_brain.bridge.commands import ApprovalAnnouncer, CommandRouter
from neml_brain.bridge.live import LivePublisher
from neml_brain.bridge.protocol import new_envelope


class Sent:
    def __init__(self) -> None:
        self.items: list[tuple[str, dict[str, Any], str | None]] = []

    def __call__(self, kind: str, payload: dict[str, Any], *, idempotency_key: str | None = None):
        self.items.append((kind, payload, idempotency_key))

    def acks(self) -> list[dict[str, Any]]:
        return [p for k, p, _ in self.items if k == "command_ack"]


class Repo:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    async def create_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("create", payload))
        return {"id": "t1", **payload}

    async def update_task(self, task_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        self.calls.append(("update", (task_id, changes)))
        return None if task_id == "missing" else {"id": task_id, **changes}

    async def cancel_task(self, task_id: str) -> bool:
        return task_id != "missing"


class Safety:
    def __init__(self) -> None:
        self.decided: list[dict[str, Any]] = []
        self.estops: list[tuple[str, str, str]] = []

    async def software_estop(self, robot_id: str, actor: str, reason: str):
        self.estops.append((robot_id, actor, reason))
        return {"state": "estop"}

    async def decide_approval(self, **kw: Any):
        self.decided.append(kw)
        return {"decision": kw["decision"]}


class Orch:
    async def handle_command(self, **kw: Any) -> dict[str, Any]:
        return {"accepted": True, "text": kw["text"], "actor": kw["actor"]}


class SettingsStore:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    async def model_ids(self) -> list[str]:
        return ["_lab", "quadruped_v2"]

    async def get(self, model_id: str) -> dict[str, Any]:
        return dict(self.rows.get(model_id, {}))

    async def put(self, model_id: str, values: dict[str, Any], actor: str) -> dict[str, Any]:
        merged = {**self.rows.get(model_id, {}), **values}
        self.rows[model_id] = {k: v for k, v in merged.items() if v is not None}
        self.rows[model_id]["_by"] = actor
        return {k: v for k, v in self.rows[model_id].items() if k != "_by"}


def make() -> tuple[CommandRouter, Sent, Safety, Repo, SettingsStore]:
    sent, safety, repo, store = Sent(), Safety(), Repo(), SettingsStore()
    router = CommandRouter(
        repo=repo,
        safety=safety,
        orchestrator=Orch(),
        settings=store,
        send=sent,
    )
    return router, sent, safety, repo, store


def command(kind: str, payload: dict[str, Any], cid: str = "11111111-1111-1111-1111-111111111111"):
    return new_envelope(
        1,
        "command",
        {"id": cid, "seq": 1, "kind": kind, "payload": payload, "idempotency_key": "k"},
    )


async def test_task_create_is_applied_and_acked_in_the_cloud_contract() -> None:
    router, sent, _, repo, _ = make()
    await router(
        command(
            "task.create",
            {
                "title": "walk",
                "kind": "human",
                "source": "user:mg",
                "priority": 5,
                "spec": {},
                "robotId": "R01",
            },
        )
    )
    assert repo.calls[0][1]["robot_id"] == "R01"  # camelCase in, column name out
    (ack,) = sent.acks()
    assert ack["commandId"] == "11111111-1111-1111-1111-111111111111"
    assert ack["state"] == "applied" and ack["result"]["id"] == "t1"


async def test_unknown_kind_and_missing_fields_are_rejected_not_failed() -> None:
    router, sent, *_ = make()
    await router(command("firmware.flash", {}))
    await router(command("task.create", {"title": "x"}))
    assert [a["state"] for a in sent.acks()] == ["rejected", "rejected"]
    assert "unknown command kind" in sent.acks()[0]["result"]["error"]


async def test_a_handler_crash_is_a_failed_ack_and_the_link_survives() -> None:
    router, sent, _, repo, _ = make()

    async def boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("db down")

    repo.create_task = boom  # type: ignore[method-assign]
    await router(
        command(
            "task.create", {"title": "t", "kind": "human", "source": "s", "priority": 1, "spec": {}}
        )
    )
    assert sent.acks()[0]["state"] == "failed" and "db down" in sent.acks()[0]["result"]["error"]


async def test_update_parses_a_deadline_and_a_missing_task_is_rejected() -> None:
    router, sent, _, repo, _ = make()
    await router(command("task.update", {"taskId": "t1", "deadline": "2026-10-04T10:00:00+00:00"}))
    assert isinstance(repo.calls[0][1][1]["deadline"], datetime)
    await router(command("task.update", {"taskId": "missing", "priority": 3}))
    assert [a["state"] for a in sent.acks()] == ["applied", "rejected"]


async def test_estop_goes_through_the_software_estop_with_the_cloud_actor() -> None:
    router, sent, safety, *_ = make()
    await router(command("robot.estop", {"robotId": "R01", "reason": "bench"}))
    assert safety.estops == [("R01", "cloud", "bench")]
    assert sent.acks()[0]["state"] == "applied"


async def test_approval_decision_uses_the_cloud_wire_names() -> None:
    router, _, safety, *_ = make()
    env = new_envelope(
        1,
        "approval_decision",
        {"approvalId": "a1", "decision": "approved", "by": "owner@firm.com", "note": None},
    )
    await router(env)
    assert safety.decided == [
        {"approval_id": "a1", "decision": "approved", "decided_by": "owner@firm.com", "note": None}
    ]


async def test_a_malformed_approval_decision_is_dropped_without_deciding() -> None:
    router, _, safety, *_ = make()
    await router(
        new_envelope(1, "approval_decision", {"approvalId": "a1", "decision": "expired", "by": "x"})
    )
    assert safety.decided == []  # `expired` is only ever set by the sweep


async def test_model_settings_round_trip_and_validation() -> None:
    router, sent, _, _, store = make()
    await router(command("model_settings.get", {"modelId": "quadruped_v2"}))
    assert sent.acks()[-1]["result"]["missing_required"] == ["mtbf_min_hours"]

    await router(
        command(
            "model_settings.put",
            {"modelId": "quadruped_v2", "values": {"mtbf_min_hours": 400}, "by": "owner@firm.com"},
        )
    )
    assert sent.acks()[-1]["state"] == "applied"
    assert store.rows["quadruped_v2"]["_by"] == "owner@firm.com"
    assert sent.acks()[-1]["result"]["missing_required"] == []

    await router(
        command("model_settings.put", {"modelId": "quadruped_v2", "values": {"mtbf_min_hours": -1}})
    )
    await router(command("model_settings.put", {"modelId": "nope", "values": {}}))
    assert [a["state"] for a in sent.acks()[-2:]] == ["rejected", "rejected"]

    await router(command("model_settings.get", {}))
    listing = sent.acks()[-1]["result"]["models"]
    assert [m["modelId"] for m in listing] == ["_lab", "quadruped_v2"]


async def test_announcer_sends_each_pending_approval_once_with_a_stable_key() -> None:
    sent = Sent()
    rows = [
        {
            "id": "a1",
            "level": 4,
            "subject_kind": "task",
            "subject_id": "t1",
            "expires_at": "2026-10-04T00:00:00+00:00",
            "payload": {"x": 1},
        }
    ]

    async def pending() -> list[dict[str, Any]]:
        return rows

    announcer = ApprovalAnnouncer(pending, sent)
    assert await announcer.announce() == 1 and await announcer.announce() == 0
    kind, payload, key = sent.items[0]
    assert kind == "approval_request" and key == "approval-request:a1"
    assert payload["approvalId"] == "a1" and payload["subjectKind"] == "task"
    assert payload["expiresAt"] == "2026-10-04T00:00:00+00:00"


# ---------------------------------------------------------------- live feed
class FakeSessions:
    """async_sessionmaker stand-in: each execute() pops the next canned result."""

    def __init__(self, *results: list[Any]) -> None:
        self.results = list(results)

    def __call__(self) -> "FakeSessions":
        return self

    async def __aenter__(self) -> "FakeSessions":
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None

    async def execute(self, *_a: Any, **_k: Any) -> Any:
        rows = self.results.pop(0)
        return SimpleNamespace(all=lambda: rows)


def publisher(sessions: FakeSessions, sent: Sent) -> LivePublisher:
    async def used() -> float:
        return 0.42

    return LivePublisher(sessions, sent, model="qwen", budget_used=used, gpu_owner=lambda: "gazebo")  # type: ignore[arg-type]


async def test_brain_status_uses_the_spec_9_4_event_shape() -> None:
    sent = Sent()
    await publisher(FakeSessions(), sent).brain_status()
    kind, payload, _ = sent.items[0]
    assert kind == "event" and payload["name"] == "BrainStatus"
    assert payload["data"] == {
        "online": True,
        "model": "qwen",
        "gpuOwner": "gazebo",
        "budgetUsed": 0.42,
    }


async def test_robot_state_is_sent_only_when_something_changed() -> None:
    sent = Sent()
    seen = datetime(2026, 10, 3, tzinfo=UTC)
    row = SimpleNamespace(id="R01", state="idle", soc=0.8, last_seen=seen)
    pub = publisher(
        FakeSessions([row], [row], [SimpleNamespace(**{**row.__dict__, "soc": 0.7})]), sent
    )
    assert [await pub.robots(), await pub.robots(), await pub.robots()] == [1, 0, 1]
    assert sent.items[0][1] == {
        "robotId": "R01",
        "state": "idle",
        "batterySoc": 0.8,
        "lastSeen": seen.isoformat(),
    }


async def test_task_updates_skip_the_first_look_then_report_changes() -> None:
    sent = Sent()
    t = lambda state: SimpleNamespace(id="t1", state=state, note=None)  # noqa: E731
    pub = publisher(FakeSessions([t("queued")], [t("queued")], [t("running")]), sent)
    assert [await pub.tasks(), await pub.tasks(), await pub.tasks()] == [0, 0, 1]
    assert sent.items[0][1]["name"] == "TaskUpdated"
    assert sent.items[0][1]["data"]["state"] == "running"


async def test_telemetry_does_not_lose_samples_that_share_a_timestamp() -> None:
    sent = Sent()
    ts = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
    a = SimpleNamespace(ts=ts, robot_id="R01", metric="soc", value=0.8, tags=None)
    b = SimpleNamespace(ts=ts, robot_id="R01", metric="temp", value=40.0, tags=None)
    pub = publisher(FakeSessions([a], [a, b]), sent)  # second poll re-reads `a` and finds `b`
    assert [await pub.telemetry(), await pub.telemetry()] == [1, 1]
    metrics = [s["metric"] for _, p, _ in sent.items for s in p["samples"]]
    assert metrics == ["soc", "temp"]  # `a` once, `b` once
    assert sent.items[0][1]["samples"][0]["robotId"] == "R01"


async def test_audit_rows_go_out_once_as_a_durable_log() -> None:
    sent = Sent()
    ts = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
    row = SimpleNamespace(
        id=7,
        ts=ts,
        actor="agent:mechanical",
        action="cad.generate",
        target="bracket",
        outcome="ok",
        duration_ms=12,
        aid=None,
    )
    pub = publisher(FakeSessions([row], []), sent)
    assert [await pub.audit(), await pub.audit()] == [1, 0]
    kind, payload, _ = sent.items[0]
    assert kind == "log" and payload["audit"][0]["actor"] == "agent:mechanical"
    assert payload["audit"][0]["durationMs"] == 12


@pytest.mark.parametrize("kind", ["telemetry"])
def test_only_telemetry_is_droppable(kind: str) -> None:
    from neml_brain.bridge.protocol import Priority, priority_of

    assert priority_of(kind) is Priority.DROPPABLE
    assert priority_of("command_ack") is Priority.DURABLE


# ---------------------------------------------------------------- print commands
async def test_print_cancel_and_qc_route_to_fab_and_reject_cleanly() -> None:
    from neml_brain.bridge.fab_ops import FabRejected, qc_form

    calls: list[tuple[str, Any]] = []

    class FakeFab:
        async def cancel(self, job_id: str, reason: str | None) -> dict[str, Any]:
            calls.append(("cancel", job_id))
            if job_id == "done":
                raise FabRejected("print job is already done")
            return {"state": "cancelled"}

        async def submit_qc(self, job_id: str, body: dict[str, Any], genome: str | None) -> Any:
            calls.append(("qc", body))
            return {"verdict": "pass"}

    sent = Sent()
    router = CommandRouter(
        repo=None,
        safety=None,
        orchestrator=None,
        settings=None,  # type: ignore[arg-type]
        send=sent,
        fab=FakeFab(),
    )
    await router._command(command("print.cancel", {"jobId": "j1"}))
    await router._command(command("print.cancel", {"jobId": "done"}))
    await router._command(command("print.qc", {"jobId": "j1", "form": {"mass_g": 1}}))
    await router._command(command("print.qc", {"jobId": "j1"}))
    states = [p["state"] for _, p, _ in sent.items]
    assert states == ["applied", "rejected", "applied", "rejected"]

    class Form:
        def __init__(self, **kw: Any) -> None:
            self.kw = kw

    body = {
        **{f"dim_{i}_mm": 10.0 for i in (1, 2, 3)},
        **{f"dim_{i}_nominal_mm": 10.0 for i in (1, 2, 3)},
        "mass_g": 50.0,
        "mass_nominal_g": 50.0,
        "warp_mm": 0.1,
        "hole_gauge_ok": True,
        "layer_adhesion_ok": True,
    }
    assert qc_form(body, Form).kw["mass_measured_g"] == 50.0
    with pytest.raises(FabRejected):
        qc_form({**body, "warp_mm": "x"}, Form)
