# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Release tooling: version stamping and the artefact manifest (SPEC 0.6).

SPEC 0.6 is the rule this file enforces: *every artefact is versioned and its
origin is recorded (model, prompt hash, seed, input hash). An artefact without
that record is invalid.* So the manifest refuses to describe an artefact it
cannot account for, instead of quietly writing an empty field.

    python scripts/release/release.py stamp 1.2.0 [--build 7] [--check]
    python scripts/release/release.py manifest 1.2.0 dist/*.apk hardware/exports/*.3mf

An artefact the system generated carries its provenance in a sidecar next to it,
`<artefact>.provenance.json`, written by the generator (see
brain/neml_brain/generators/*.py, which already hash their inputs). Anything
built deterministically from the tree - an apk, a dll, a container image - has
no model and no seed; its input hash is the git commit, and the manifest says so
rather than pretending a model was involved.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
PROVENANCE_FIELDS = ("model", "prompt_hash", "seed", "input_hash")  # SPEC 0.6

# Generated (not built): these must carry a provenance sidecar.
GENERATED_DIRS = ("hardware/exports", "manufacturing/jobs", "evolution/experiments")


# ----------------------------------------------------------------- stamping


def _sub(path: Path, pattern: str, replacement: str) -> tuple[str, str]:
    """Return (old text, new text) with exactly one substitution applied."""
    old = path.read_text(encoding="utf-8")
    new, count = re.subn(pattern, replacement, old, count=1, flags=re.MULTILINE)
    if count != 1:
        raise SystemExit(f"{path}: no version field matched {pattern!r}")
    return old, new


def stamp(
    version: str, build: int | None = None, root: Path = ROOT, write: bool = True
) -> dict[str, bool]:
    """Put `version` into the three places that carry one. Returns
    {path: would change}. With write=False nothing is touched, which is what
    --check uses. Nothing else in the tree hard-codes a version."""
    if not SEMVER.match(version):
        raise SystemExit(f"{version!r} is not X.Y.Z")

    edits = [
        (root / "brain" / "neml_brain" / "__init__.py", r'^__version__ = ".*"$',
         f'__version__ = "{version}"'),
        (root / "dotnet" / "Directory.Build.props", r"<Version>.*</Version>",
         f"<Version>{version}</Version>"),
    ]

    pubspec = root / "mobile" / "pubspec.yaml"
    current_build = re.search(r"^version: .*\+(\d+)$", pubspec.read_text(encoding="utf-8"), re.M)
    next_build = build if build is not None else int(current_build.group(1)) if current_build else 1
    edits.append((pubspec, r"^version: .*$", f"version: {version}+{next_build}"))

    changed: dict[str, bool] = {}
    for path, pattern, replacement in edits:
        if path == root / "dotnet" / "Directory.Build.props" and "<Version>" not in path.read_text(
            encoding="utf-8"
        ):
            # The property does not exist yet: add it to the first group.
            pattern, replacement = r"(<PropertyGroup>)", rf"\1\n    <Version>{version}</Version>"
        old, new = _sub(path, pattern, replacement)
        changed[str(path.relative_to(root)).replace("\\", "/")] = old != new
        if old != new and write:
            path.write_text(new, encoding="utf-8")
    return changed


# ----------------------------------------------------------------- manifest


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def git_commit(root: Path = ROOT) -> str:
    return subprocess.run(  # noqa: S603,S607 - fixed argv, no shell
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def provenance(path: Path, commit: str) -> dict[str, Any]:
    """SPEC 0.6 record for one artefact. Sidecar first, build facts otherwise."""
    sidecar = path.with_suffix(path.suffix + ".provenance.json")
    if sidecar.is_file():
        record = json.loads(sidecar.read_text(encoding="utf-8"))
        missing = [f for f in PROVENANCE_FIELDS if f not in record]
        if missing:
            raise SystemExit(f"{sidecar}: missing {missing} (SPEC 0.6)")
        return {"source": "generated", **{f: record[f] for f in PROVENANCE_FIELDS}}

    posix = path.as_posix()
    if any(part in posix for part in GENERATED_DIRS):
        raise SystemExit(
            f"{path}: generated artefact with no {path.name}.provenance.json - "
            "an artefact without a record is invalid (SPEC 0.6)"
        )
    # Built from the tree: no model, no prompt, no seed; the commit is the input.
    return {
        "source": "deterministic-build",
        "model": None,
        "prompt_hash": None,
        "seed": None,
        "input_hash": commit,
    }


def manifest(version: str, paths: list[Path], root: Path = ROOT) -> dict[str, Any]:
    commit = git_commit(root)
    artefacts = []
    for path in paths:
        if not path.is_file():
            raise SystemExit(f"{path}: not a file")
        artefacts.append(
            {
                "path": path.as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                **provenance(path, commit),
            }
        )
    return {
        "product": "NEML",
        "version": version,
        "commit": commit,
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "spec": "NEML_SPEC.md 0.6",
        "artifacts": artefacts,
    }


# --------------------------------------------------------------------- cli


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    stamp_cmd = sub.add_parser("stamp", help="write the version into brain, dotnet and mobile")
    stamp_cmd.add_argument("version")
    stamp_cmd.add_argument("--build", type=int, help="Android build number (default: keep)")
    stamp_cmd.add_argument("--check", action="store_true", help="fail if anything would change")

    manifest_cmd = sub.add_parser("manifest", help="write the SPEC 0.6 artefact manifest")
    manifest_cmd.add_argument("version")
    manifest_cmd.add_argument("paths", nargs="+", type=Path)
    manifest_cmd.add_argument("--out", type=Path, help="default: stdout")

    args = parser.parse_args(argv)

    if args.command == "stamp":
        if args.check:
            stale = [
                path
                for path, would_change in stamp(args.version, args.build, write=False).items()
                if would_change
            ]
            if stale:
                print(f"version {args.version} is not stamped in: {', '.join(stale)}")
                return 1
            print(f"version {args.version} is stamped everywhere")
            return 0
        for path, did_change in stamp(args.version, args.build).items():
            print(f"{path}: {'updated' if did_change else 'already ' + args.version}")
        return 0

    document = json.dumps(manifest(args.version, args.paths), indent=2) + "\n"
    if args.out:
        args.out.write_text(document, encoding="utf-8")
        print(f"{args.out}: {len(args.paths)} artefact(s)")
    else:
        sys.stdout.write(document)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
