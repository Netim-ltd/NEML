# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Edge CPU policy runtime; signed deployment tickets and fixed safety limits."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from neml_brain.platform.core import Scope
from neml_brain.platform.policy import LinearPolicy
from neml_brain.platform.robots import ModelCard, SafetyEnvelope


@dataclass(frozen=True)
class DeploymentTicket:
    scope: Scope
    robot_id: str
    robot_type: str
    version: str
    stage: str
    approval_id: str | None
    expires_at: datetime
    signature: str
    candidate_version: str = ""

    def to_json(self) -> str:
        return json.dumps(
            {**json.loads(self.signed_bytes()), "signature": self.signature},
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, value: str) -> DeploymentTicket:
        body = json.loads(value)
        return cls(
            Scope(body["tenant_id"], body["domain_id"]),
            body["robot_id"],
            body["robot_type"],
            body["version"],
            body["stage"],
            body.get("approval_id"),
            datetime.fromisoformat(body["expires_at"]),
            body["signature"],
            body.get("candidate_version", ""),
        )

    def signed_bytes(self) -> bytes:
        body = {
            "tenant_id": self.scope.tenant_id,
            "domain_id": self.scope.domain_id,
            "robot_id": self.robot_id,
            "robot_type": self.robot_type,
            "version": self.version,
            "candidate_version": self.candidate_version,
            "stage": self.stage,
            "approval_id": self.approval_id,
            "expires_at": self.expires_at.isoformat(),
        }
        return json.dumps(body, sort_keys=True, separators=(",", ":")).encode()


@dataclass(frozen=True)
class ModelAck:
    scope: Scope
    robot_id: str
    robot_type: str
    candidate_version: str
    applied_version: str
    stage: str
    occurred_at: datetime
    signature: str

    def signed_bytes(self) -> bytes:
        return json.dumps(
            {
                "tenant_id": self.scope.tenant_id,
                "domain_id": self.scope.domain_id,
                "robot_id": self.robot_id,
                "robot_type": self.robot_type,
                "candidate_version": self.candidate_version,
                "applied_version": self.applied_version,
                "stage": self.stage,
                "occurred_at": self.occurred_at.isoformat(),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()

    def to_json(self) -> str:
        return json.dumps(
            {**json.loads(self.signed_bytes()), "signature": self.signature},
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, value: str) -> ModelAck:
        body = json.loads(value)
        return cls(
            Scope(body["tenant_id"], body["domain_id"]),
            body["robot_id"],
            body["robot_type"],
            body["candidate_version"],
            body["applied_version"],
            body["stage"],
            datetime.fromisoformat(body["occurred_at"]),
            body["signature"],
        )


@dataclass(frozen=True)
class TicketRequest:
    scope: Scope
    robot_id: str
    robot_type: str
    nonce: str
    occurred_at: datetime
    signature: str

    def signed_bytes(self) -> bytes:
        return json.dumps(
            {
                "tenant_id": self.scope.tenant_id,
                "domain_id": self.scope.domain_id,
                "robot_id": self.robot_id,
                "robot_type": self.robot_type,
                "nonce": self.nonce,
                "occurred_at": self.occurred_at.isoformat(),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()

    def to_json(self) -> str:
        return json.dumps(
            {**json.loads(self.signed_bytes()), "signature": self.signature},
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, value: str) -> TicketRequest:
        body = json.loads(value)
        return cls(
            Scope(body["tenant_id"], body["domain_id"]),
            body["robot_id"],
            body["robot_type"],
            body["nonce"],
            datetime.fromisoformat(body["occurred_at"]),
            body["signature"],
        )


def sign_ticket_request(request: TicketRequest, device_key: Ed25519PrivateKey) -> TicketRequest:
    return TicketRequest(
        request.scope,
        request.robot_id,
        request.robot_type,
        request.nonce,
        request.occurred_at,
        device_key.sign(request.signed_bytes()).hex(),
    )


def sign_ack(ack: ModelAck, device_key: Ed25519PrivateKey) -> ModelAck:
    return ModelAck(
        ack.scope,
        ack.robot_id,
        ack.robot_type,
        ack.candidate_version,
        ack.applied_version,
        ack.stage,
        ack.occurred_at,
        device_key.sign(ack.signed_bytes()).hex(),
    )


def sign_ticket(ticket: DeploymentTicket, private_key: Ed25519PrivateKey) -> DeploymentTicket:
    """Lab-only helper called after a verified approval and stage transition."""
    return DeploymentTicket(
        ticket.scope,
        ticket.robot_id,
        ticket.robot_type,
        ticket.version,
        ticket.stage,
        ticket.approval_id,
        ticket.expires_at,
        private_key.sign(ticket.signed_bytes()).hex(),
        ticket.candidate_version,
    )


class EdgeRuntime:
    def __init__(
        self,
        scope: Scope,
        robot_id: str,
        robot_type: str,
        public_key: bytes,
        model_dir: Path,
        envelope: SafetyEnvelope,
    ) -> None:
        self.scope = scope
        self.robot_id = robot_id
        self.robot_type = robot_type
        self.key = Ed25519PublicKey.from_public_bytes(public_key)
        self.model_dir = model_dir.resolve()
        self.envelope = envelope
        self._active: LinearPolicy | None = None

    def install(self, card: ModelCard, artifact: bytes, ticket: DeploymentTicket) -> str:
        if card.scope != self.scope or ticket.scope != self.scope:
            raise PermissionError("cross-tenant model deployment")
        if card.robot_type != self.robot_type or ticket.robot_type != self.robot_type:
            raise PermissionError("wrong robot type")
        if ticket.robot_id != self.robot_id or ticket.version != card.version:
            raise PermissionError("deployment ticket does not target this model/robot")
        if ticket.stage != "rollback" and ticket.candidate_version not in ("", card.version):
            raise PermissionError("candidate version does not match model card")
        if ticket.expires_at <= datetime.now(UTC):
            raise PermissionError("expired deployment ticket")
        if ticket.stage not in ("canary", "fleet", "rollback"):
            raise PermissionError("invalid deployment stage")
        if ticket.stage != "rollback" and not ticket.approval_id:
            raise PermissionError("physical deployment needs human approval")
        digest = hashlib.sha256(artifact).hexdigest()
        if digest != card.artifact_sha256:
            raise ValueError("model artifact hash mismatch")
        card_message = (
            f"{card.scope.tenant_id}:{card.scope.domain_id}:"
            f"{card.robot_type}:{card.version}:{digest}"
        ).encode()
        try:
            self.key.verify(bytes.fromhex(card.signature), card_message)
            self.key.verify(bytes.fromhex(ticket.signature), ticket.signed_bytes())
        except (InvalidSignature, ValueError) as exc:
            raise PermissionError("model or deployment ticket signature invalid") from exc
        policy = LinearPolicy.from_bytes(artifact)
        if policy.robot_type != self.robot_type:
            raise ValueError("artifact robot type mismatch")
        self.model_dir.mkdir(parents=True, exist_ok=True)
        target = self.model_dir / f"{digest}.model"
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError("existing model file is corrupt")
        if not target.exists():
            with tempfile.NamedTemporaryFile(dir=self.model_dir, delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(artifact)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        # Replacing this small pointer is atomic. The old signed model remains
        # on disk for rollback; boot loads only the exact digest it names.
        pointer = self.model_dir / "active.json"
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=self.model_dir, delete=False
        ) as handle:
            temporary_pointer = Path(handle.name)
            json.dump({"version": card.version, "sha256": digest}, handle)
            handle.flush()
            os.fsync(handle.fileno())
        temporary_pointer.replace(pointer)
        self._active = policy
        return card.version

    def load_active(self, card: ModelCard) -> str:
        """Verify the persisted pointer, model bytes and public signature on boot."""
        if card.scope != self.scope or card.robot_type != self.robot_type:
            raise PermissionError("model card does not belong to this robot")
        pointer = json.loads((self.model_dir / "active.json").read_text(encoding="utf-8"))
        if pointer != {"version": card.version, "sha256": card.artifact_sha256}:
            raise PermissionError("active model pointer does not match signed card")
        artifact = (self.model_dir / f"{card.artifact_sha256}.model").read_bytes()
        if hashlib.sha256(artifact).hexdigest() != card.artifact_sha256:
            raise ValueError("active model bytes are corrupt")
        message = (
            f"{card.scope.tenant_id}:{card.scope.domain_id}:"
            f"{card.robot_type}:{card.version}:{card.artifact_sha256}"
        ).encode()
        try:
            self.key.verify(bytes.fromhex(card.signature), message)
        except (InvalidSignature, ValueError) as exc:
            raise PermissionError("active model signature invalid") from exc
        self._active = LinearPolicy.from_bytes(artifact)
        return card.version

    def choose(self, features: tuple[float, ...]) -> str:
        if self._active is None:
            raise RuntimeError("no verified model active")
        return self._active.choose(features)

    async def fetch_and_install(self, url: str, ticket: DeploymentTicket) -> str:
        """Download over TLS; signature checks still happen after transport."""
        if not url.startswith("https://"):
            raise PermissionError("model bundle URL must use HTTPS")
        encoded_ticket = base64.urlsafe_b64encode(ticket.to_json().encode()).decode().rstrip("=")
        async with httpx.AsyncClient(timeout=30.0, verify=True) as client:
            response = await client.get(url, headers={"X-NEML-Ticket": encoded_ticket})
            response.raise_for_status()
            bundle = response.json()
        body = bundle["card"]
        card_scope = Scope(body["scope"]["tenant_id"], body["scope"]["domain_id"])
        card = ModelCard(
            card_scope,
            body["robot_type"],
            body["version"],
            body["artifact_sha256"],
            body["signature"],
            datetime.fromisoformat(body["training_start"]),
            datetime.fromisoformat(body["training_end"]),
            {key: float(value) for key, value in body["metrics"].items()},
            body.get("rollback_version"),
        )
        artifact = base64.b64decode(bundle["artifact_base64"], validate=True)
        return self.install(card, artifact, ticket)

    async def deploy_from_url(
        self,
        bundle_url: str,
        ack_url: str,
        ticket: DeploymentTicket,
        device_key: Ed25519PrivateKey,
    ) -> str:
        if not ticket.candidate_version or not ack_url.startswith("https://"):
            raise PermissionError("signed candidate and HTTPS acknowledgement URL required")
        applied = await self.fetch_and_install(bundle_url, ticket)
        ack = ModelAck(
            self.scope,
            self.robot_id,
            self.robot_type,
            ticket.candidate_version,
            applied,
            ticket.stage,
            datetime.now(UTC),
            "",
        )
        signed = sign_ack(ack, device_key)
        async with httpx.AsyncClient(timeout=10.0, verify=True) as client:
            response = await client.post(
                ack_url,
                content=signed.to_json().encode(),
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
        return applied

    async def poll_and_deploy(
        self,
        ticket_url: str,
        bundle_url: str,
        ack_url: str,
        device_key: Ed25519PrivateKey,
    ) -> str | None:
        if not ticket_url.startswith("https://"):
            raise PermissionError("ticket endpoint must use HTTPS")
        request = TicketRequest(
            self.scope,
            self.robot_id,
            self.robot_type,
            secrets.token_hex(16),
            datetime.now(UTC),
            "",
        )
        signed = sign_ticket_request(request, device_key)
        async with httpx.AsyncClient(timeout=10.0, verify=True) as client:
            response = await client.post(
                ticket_url,
                content=signed.to_json().encode(),
                headers={"Content-Type": "application/json"},
            )
            if response.status_code == 204:
                return None
            response.raise_for_status()
            ticket = DeploymentTicket.from_json(response.json()["ticket"])
        return await self.deploy_from_url(bundle_url, ack_url, ticket, device_key)

    def authorize_actuator(
        self, *, speed_mps: float, force_n: float, zone: str, estop: bool
    ) -> None:
        """Independent fixed gate; callers must also keep hardware watchdog active."""
        self.envelope.constrain(speed_mps=speed_mps, force_n=force_n, zone=zone, estop=estop)
