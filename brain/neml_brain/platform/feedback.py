# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Signed robot failure/recovery reports for autonomous, verified learning data."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from neml_brain.platform.recovery import TRAINABLE_FAILURES

FIELDS = (
    "tenant_id",
    "domain_id",
    "robot_id",
    "robot_type",
    "operation",
    "report_id",
    "occurred_at",
    "features",
    "failed_action",
    "failure_class",
    "recovery_action",
    "outcome",
    "quality",
    "verifier_id",
)


def report_bytes(report: dict[str, Any]) -> bytes:
    if any(field not in report for field in FIELDS):
        raise ValueError("report is missing required fields")
    return json.dumps(
        {field: report[field] for field in FIELDS},
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def sign_report(report: dict[str, Any], key: Ed25519PrivateKey) -> str:
    return key.sign(report_bytes(report)).hex()


def attest_recovery(
    report: dict[str, Any],
    robot_public: bytes,
    verifier_key: Ed25519PrivateKey,
    postcondition: Callable[[dict[str, Any]], bool],
) -> dict[str, Any]:
    """A separate sensor monitor supplies the postcondition callback."""
    try:
        Ed25519PublicKey.from_public_bytes(robot_public).verify(
            bytes.fromhex(report["robot_signature"]), report_bytes(report)
        )
    except (InvalidSignature, KeyError, TypeError, ValueError) as exc:
        raise PermissionError("robot report signature invalid") from exc
    if not postcondition(report):
        raise PermissionError("independent postcondition was not verified")
    attested = dict(report)
    attested["verifier_signature"] = sign_report(attested, verifier_key)
    verifier_public = verifier_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    verify_report(attested, robot_public, verifier_public)
    return attested


def verify_report(
    report: dict[str, Any],
    robot_public: bytes,
    verifier_public: bytes,
    *,
    now: datetime | None = None,
) -> None:
    if robot_public == verifier_public:
        raise PermissionError("robot and outcome verifier must use separate keys")
    payload = report_bytes(report)
    for field in (
        "tenant_id",
        "domain_id",
        "robot_id",
        "robot_type",
        "operation",
        "report_id",
        "failure_class",
        "verifier_id",
    ):
        value = report[field]
        if not isinstance(value, str) or not 1 <= len(value) <= 128:
            raise ValueError(f"invalid {field}")
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", report["operation"]):
        raise ValueError("invalid operation")
    try:
        UUID(report["report_id"])
    except (ValueError, AttributeError) as exc:
        raise ValueError("report ID must be a UUID") from exc
    failed, recovery = report["failed_action"], report["recovery_action"]
    if report["failure_class"] not in TRAINABLE_FAILURES:
        raise ValueError("failure class is not approved for LoRA data")
    if (
        not isinstance(failed, str)
        or not isinstance(recovery, str)
        or not 1 <= len(failed) <= 128
        or not 1 <= len(recovery) <= 128
        or failed == recovery
    ):
        raise ValueError("failed and recovery actions must be different")
    if report["outcome"] != "success":
        raise ValueError("only verified recoveries become positive training examples")
    quality = report["quality"]
    if (
        isinstance(quality, bool)
        or not isinstance(quality, (int, float))
        or not math.isfinite(quality)
        or quality < 0.95
    ):
        raise ValueError("recovery quality is below threshold")
    features = report["features"]
    if (
        not isinstance(features, list)
        or not 1 <= len(features) <= 64
        or any(
            isinstance(x, bool)
            or not isinstance(x, (int, float))
            or not math.isfinite(x)
            or abs(x) > 1
            for x in features
        )
    ):
        raise ValueError("features must be bounded normalized numbers")
    timestamp = datetime.fromisoformat(report["occurred_at"])
    if timestamp.tzinfo is None or timestamp > (now or datetime.now(UTC)) + timedelta(minutes=5):
        raise ValueError("report time is missing a timezone or in the future")
    try:
        Ed25519PublicKey.from_public_bytes(robot_public).verify(
            bytes.fromhex(report["robot_signature"]), payload
        )
        Ed25519PublicKey.from_public_bytes(verifier_public).verify(
            bytes.fromhex(report["verifier_signature"]), payload
        )
    except (InvalidSignature, KeyError, TypeError, ValueError) as exc:
        raise PermissionError("robot or independent outcome verifier signature invalid") from exc


def training_pair(report: dict[str, Any]) -> dict[str, Any]:
    """Use the successful recovery as label; never train on the failed action."""
    prompt = json.dumps(
        {
            "robot_type": report["robot_type"],
            "operation": report["operation"],
            "features": report["features"],
            "failed_action": report["failed_action"],
            "failure_class": report["failure_class"],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return {
        "prompt": prompt,
        "completion": report["recovery_action"],
        "approved": True,
        "source_sha256": hashlib.sha256(report_bytes(report)).hexdigest(),
    }
