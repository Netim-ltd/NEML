# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Approved procurement-package mail transport with a second allowlist gate."""

from __future__ import annotations

import hashlib
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path

from neml_brain.platform.design import DesignPackage


@dataclass(frozen=True)
class SmtpSettings:
    host: str
    port: int
    username: str
    password: str
    sender: str
    recipients: frozenset[str]
    artifact_root: Path


class SmtpPurchaseSender:
    """Sends a request for human purchasing; never places an order."""

    def __init__(self, settings: SmtpSettings) -> None:
        if not settings.recipients or not settings.host or not settings.username:
            raise ValueError("SMTP settings are incomplete")
        self.settings = settings

    def send(self, recipient: str, package: DesignPackage) -> str:
        if recipient not in self.settings.recipients:
            raise PermissionError("procurement recipient is not allowlisted")
        paths = [
            package.requirements_path,
            package.freecad_path,
            package.kicad_path,
            package.firmware_path,
            package.simulation_report_path,
        ]
        root = self.settings.artifact_root.resolve()
        resolved = [Path(path).resolve() for path in paths]
        if any(root not in path.parents or not path.is_file() for path in resolved):
            raise PermissionError("procurement attachment must be an existing artifact")
        if sum(path.stat().st_size for path in resolved) > 20 * 1024 * 1024:
            raise ValueError("procurement package exceeds 20 MiB")
        message = EmailMessage()
        message["From"] = self.settings.sender
        message["To"] = recipient
        message["Subject"] = f"NEML design review: {package.gap.task_id}"
        message.set_content(
            "Human purchasing review requested. This message is not an order.\n"
            f"Tenant: {package.gap.scope.tenant_id}\n"
            f"Domain: {package.gap.scope.domain_id}\n"
            f"Parts cost: USD {package.parts_cost_usd}\n"
            "Shipping and tax are estimated separately.\n"
        )
        for path in resolved:
            message.add_attachment(
                path.read_bytes(),
                maintype="application",
                subtype="octet-stream",
                filename=path.name,
            )
        with smtplib.SMTP(self.settings.host, self.settings.port, timeout=20) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(self.settings.username, self.settings.password)
            smtp.send_message(message)
        return hashlib.sha256(message.as_bytes()).hexdigest()
