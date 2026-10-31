# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Ticket-guarded edge model bundle download."""

from __future__ import annotations

import base64
import hmac
import json
import os
from dataclasses import asdict
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, Response

from neml_brain.api.problem import Problem
from neml_brain.platform.core import Scope
from neml_brain.platform.edge import DeploymentTicket, ModelAck, TicketRequest

router = APIRouter(prefix="/v1/platform", tags=["platform"])


@router.post("/feedback", status_code=201)
async def submit_feedback(request: Request) -> dict[str, str]:
    """An attested recovery is immutable and idempotent by report UUID."""
    raw = await request.body()
    if len(raw) > 16 * 1024:
        raise Problem(413, "Content Too Large", "Feedback report exceeds 16 KiB.")
    store = getattr(request.app.state, "platform_store", None)
    if store is None:
        raise Problem(503, "Service Unavailable", "Feedback store is not configured.")
    try:
        report = json.loads(raw)
        if not isinstance(report, dict):
            raise ValueError("expected a JSON object")
        UUID(report["report_id"])
        inserted = await store.record_feedback(report)
    except (KeyError, TypeError, ValueError, PermissionError, UnicodeDecodeError) as exc:
        raise Problem(403, "Forbidden", f"Feedback rejected: {exc}") from exc
    return {"status": "stored" if inserted else "already_stored"}


@router.get("/feedback-export")
async def export_feedback(
    request: Request,
    tenant: str = Query(min_length=1, max_length=64),
    domain: str = Query(min_length=1, max_length=64),
    operation: str = Query(min_length=1, max_length=64),
    after: UUID | None = None,
    authorization: str = Header(default=""),
) -> dict[str, Any]:
    """Private GPU-worker feed, scoped to this control-plane installation."""
    secret = os.getenv("NEML_TRAINING_EXPORT_KEY", "")
    allowed_tenant = os.getenv("NEML_TENANT_ID", "")
    if (
        len(secret) < 32
        or not allowed_tenant
        or tenant != allowed_tenant
        or not hmac.compare_digest(authorization, f"Bearer {secret}")
    ):
        raise Problem(403, "Forbidden", "Training export is not authorized.")
    store = getattr(request.app.state, "platform_store", None)
    if store is None:
        raise Problem(503, "Service Unavailable", "Feedback store is not configured.")
    rows = await store.export_feedback(
        Scope(tenant, domain), operation, str(after) if after is not None else None
    )
    return {"reports": rows, "next_after": rows[-1]["report"]["report_id"] if rows else None}


@router.post("/operation/generate")
async def generate_operation_advice(
    request: Request, authorization: str = Header(default="")
) -> dict[str, str]:
    """Operator-facing advice; never execute output as a robot command."""
    secret = os.getenv("NEML_OPERATION_CLIENT_KEY", "")
    if len(secret) < 32 or not hmac.compare_digest(authorization, f"Bearer {secret}"):
        raise Problem(403, "Forbidden", "Operation model client is not authorized.")
    raw = await request.body()
    if len(raw) > 8192:
        raise Problem(413, "Content Too Large", "Operation prompt exceeds 8 KiB.")
    try:
        payload = json.loads(raw)
        tenant = payload["tenant"]
        domain = payload["domain"]
        operation = payload["operation"]
        prompt = payload["prompt"]
        if tenant != os.getenv("NEML_TENANT_ID"):
            raise PermissionError("tenant does not match this control node")
        service = getattr(request.app.state, "operation_models", None)
        if service is None:
            raise Problem(503, "Service Unavailable", "Operation models are not configured.")
        result = await service.generate(tenant, domain, operation, prompt)
        return {
            "completion": str(result["completion"]),
            "use": "advisory_only",
            "adapter_sha256": str(result["adapter_sha256"]),
        }
    except (KeyError, TypeError, ValueError, PermissionError) as exc:
        raise Problem(403, "Forbidden", f"Operation request rejected: {exc}") from exc


@router.post("/ticket-request", response_model=None)
async def ticket_request(request: Request) -> dict[str, str] | Response:
    manager = getattr(request.app.state, "platform_deployment", None)
    if manager is None:
        raise Problem(503, "Service Unavailable", "Model distribution is not configured.")
    raw = await request.body()
    if len(raw) > 4096:
        raise Problem(400, "Bad Request", "Ticket request is too large.")
    try:
        signed = TicketRequest.from_json(raw.decode())
        ticket = await manager.request_ticket_signed(signed)
    except (KeyError, ValueError, PermissionError, UnicodeDecodeError) as exc:
        raise Problem(403, "Forbidden", f"Ticket request rejected: {exc}") from exc
    if ticket is None:
        return Response(status_code=204)
    return {"ticket": ticket.to_json()}


@router.get("/model-bundle")
async def model_bundle(
    request: Request, ticket_header: str = Header(alias="X-NEML-Ticket")
) -> dict[str, Any]:
    if len(ticket_header) > 4096:
        raise Problem(400, "Bad Request", "Deployment ticket is too long.")
    manager = getattr(request.app.state, "platform_deployment", None)
    artifacts = getattr(request.app.state, "platform_artifacts", None)
    store = getattr(request.app.state, "platform_store", None)
    if manager is None or artifacts is None or store is None:
        raise Problem(503, "Service Unavailable", "Model distribution is not configured.")
    try:
        encoded = ticket_header + "=" * (-len(ticket_header) % 4)
        ticket = DeploymentTicket.from_json(base64.urlsafe_b64decode(encoded).decode())
        await manager.verify_ticket(ticket)
        card, stored_path = await store.get_model(ticket.scope, ticket.robot_type, ticket.version)
        expected_path = artifacts._path(ticket.scope, ticket.robot_type, ticket.version)
        if str(expected_path) != stored_path:
            raise ValueError("registered artifact path differs from immutable model path")
        payload = artifacts.get(
            ticket.scope, ticket.robot_type, ticket.version, card.artifact_sha256
        )
    except (KeyError, ValueError, PermissionError, OSError) as exc:
        raise Problem(403, "Forbidden", f"Model bundle rejected: {exc}") from exc
    return {
        "card": asdict(card),
        "artifact_base64": base64.b64encode(payload).decode(),
    }


@router.post("/model-ack")
async def model_ack(request: Request) -> dict[str, str]:
    manager = getattr(request.app.state, "platform_deployment", None)
    if manager is None:
        raise Problem(503, "Service Unavailable", "Model distribution is not configured.")
    raw = await request.body()
    if len(raw) > 4096:
        raise Problem(400, "Bad Request", "Model acknowledgement is too large.")
    try:
        ack = ModelAck.from_json(raw.decode())
        deployment = await manager.acknowledge_signed(ack)
    except (KeyError, ValueError, PermissionError, UnicodeDecodeError) as exc:
        raise Problem(403, "Forbidden", f"Model acknowledgement rejected: {exc}") from exc
    return {"stage": deployment.stage.value}
