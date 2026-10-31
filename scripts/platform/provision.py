# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Operator-only provisioning for platform tenants, domains and hierarchy."""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine


async def provision(args: argparse.Namespace) -> None:
    engine = create_async_engine(os.environ["NEML_DB_URL"])
    try:
        async with engine.begin() as conn:
            if args.kind == "tenant":
                await conn.execute(
                    sa.text("INSERT INTO platform_tenants (id, name) VALUES (:id, :name)"),
                    {"id": args.tenant, "name": args.name},
                )
                return
            await conn.execute(
                sa.text("SELECT set_config('neml.tenant_id', :tenant, true)"),
                {"tenant": args.tenant},
            )
            if args.kind == "domain":
                await conn.execute(
                    sa.text("""
                        INSERT INTO platform_domains (tenant_id, id, name)
                        VALUES (:tenant, :id, :name)
                    """),
                    {"tenant": args.tenant, "id": args.domain, "name": args.name},
                )
                return
            if args.kind == "verifier":
                public_key = bytes.fromhex(Path(args.public_key_file).read_text().strip())
                if len(public_key) != 32:
                    raise ValueError("Ed25519 verifier public key must be 32 bytes")
                await conn.execute(
                    sa.text("""
                        INSERT INTO platform_verifiers
                          (tenant_id, domain_id, id, public_key)
                        VALUES (:tenant, :domain, :id, :key)
                    """),
                    {"tenant": args.tenant, "domain": args.domain,
                     "id": args.verifier, "key": public_key},
                )
                return
            rank = {"strategy": 0, "domain": 1, "team": 2, "robot": 3}[args.rank]
            if rank == 0 and args.parent is not None:
                raise ValueError("strategy must not have a parent")
            if rank > 0:
                parent_rank = (
                    await conn.execute(
                        sa.text("""
                            SELECT rank FROM platform_units
                            WHERE tenant_id = :tenant AND domain_id = :domain AND id = :parent
                        """),
                        {"tenant": args.tenant, "domain": args.domain, "parent": args.parent},
                    )
                ).scalar_one_or_none()
                if parent_rank != rank - 1:
                    raise ValueError("parent must be the immediately higher rank")
            public_key = None
            if rank == 3:
                if not args.robot_type or not args.public_key_file:
                    raise ValueError("robot requires type and device public key")
                public_key = bytes.fromhex(Path(args.public_key_file).read_text().strip())
                if len(public_key) != 32:
                    raise ValueError("Ed25519 device public key must be 32 bytes")
            await conn.execute(
                sa.text("""
                    INSERT INTO platform_units
                      (tenant_id, domain_id, id, rank, parent_id, robot_type,
                       device_public_key, safe_default)
                    VALUES (:tenant, :domain, :id, :rank, :parent, :type, :key, :safe)
                """),
                {
                    "tenant": args.tenant,
                    "domain": args.domain,
                    "id": args.unit,
                    "rank": rank,
                    "parent": args.parent,
                    "type": args.robot_type,
                    "key": public_key,
                    "safe": args.safe_default,
                },
            )
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="kind", required=True)
    tenant = sub.add_parser("tenant")
    tenant.add_argument("tenant")
    tenant.add_argument("name")
    domain = sub.add_parser("domain")
    domain.add_argument("tenant")
    domain.add_argument("domain")
    domain.add_argument("name")
    verifier = sub.add_parser("verifier")
    verifier.add_argument("tenant")
    verifier.add_argument("domain")
    verifier.add_argument("verifier")
    verifier.add_argument("--public-key-file", required=True)
    unit = sub.add_parser("unit")
    unit.add_argument("tenant")
    unit.add_argument("domain")
    unit.add_argument("unit")
    unit.add_argument("rank", choices=("strategy", "domain", "team", "robot"))
    unit.add_argument("--parent")
    unit.add_argument("--robot-type")
    unit.add_argument("--public-key-file")
    unit.add_argument("--safe-default", default="hold_position")
    asyncio.run(provision(parser.parse_args()))


if __name__ == "__main__":
    main()
