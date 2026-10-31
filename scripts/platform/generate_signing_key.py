# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Create a lab signing seed and public key outside the source checkout."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    folder = args.directory.resolve()
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    secret_path = folder / "model-signing-seed.hex"
    public_path = folder / "model-signing-public.hex"
    with secret_path.open("x", encoding="ascii") as handle:
        handle.write(key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()).hex())
    os.chmod(secret_path, 0o600)
    public_path.write_text(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex())
    print(f"Public key: {public_path}")
    print(f"Set NEML_MODEL_SIGNING_SEED from {secret_path} in the lab secret manager")


if __name__ == "__main__":
    main()
