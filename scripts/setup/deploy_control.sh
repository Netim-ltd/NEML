#!/usr/bin/env bash
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
# Small Linux control node; run from a checkout containing docker/compose.control.yml.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
env_file="${NEML_CONTROL_ENV_FILE:-$repo/.env}"
export NEML_CONTROL_ENV_FILE="$env_file"
compose="$repo/docker/compose.control.yml"
mode="${1:---check}"

if [[ "$mode" != --check && "$mode" != --deploy ]]; then
  echo "Usage: $0 [--check|--deploy]" >&2
  exit 2
fi
command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }
command -v docker >/dev/null || { echo "Docker CLI is required" >&2; exit 1; }
python3 "$repo/scripts/setup/check_control_env.py" "$env_file"
docker compose --env-file "$env_file" -f "$compose" config --quiet

if [[ "$mode" == --check ]]; then
  echo "Compose configuration is valid. No containers were started."
  exit 0
fi

docker compose --env-file "$env_file" -f "$compose" pull brain migrate
docker compose --env-file "$env_file" -f "$compose" up -d --wait brain
docker compose --env-file "$env_file" -f "$compose" ps
