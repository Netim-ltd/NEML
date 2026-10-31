#!/usr/bin/env bash
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
env_file="${NEML_API_ENV_FILE:-/srv/neml/shared/api.env}"
[[ -s "$env_file" ]] || { echo "API configuration missing: $env_file" >&2; exit 1; }
python3 "$repo/scripts/setup/check_api_env.py" "$env_file" "${NEML_CONTROL_ENV_FILE:-/srv/neml/shared/.env}"
export NEML_API_ENV_FILE="$env_file"
proxy_ip="$(docker network inspect nginx-proxy-network --format '{{range .Containers}}{{if eq .Name "nginx-proxy"}}{{.IPv4Address}}{{end}}{{end}}')"
proxy_ip="${proxy_ip%%/*}"
[[ -n "$proxy_ip" ]] || { echo "nginx-proxy is not on nginx-proxy-network" >&2; exit 1; }
export NEML_NGINX_PROXY_IP="$proxy_ip"
compose="$repo/docker/compose.api.yml"
docker compose --env-file "$env_file" -f "$compose" config --quiet
docker compose --env-file "$env_file" -f "$compose" pull api migrate provision-owner
docker compose --env-file "$env_file" -f "$compose" up --no-deps --force-recreate --abort-on-container-exit --exit-code-from migrate migrate
docker compose --env-file "$env_file" -f "$compose" up --no-deps --force-recreate --abort-on-container-exit --exit-code-from provision-owner provision-owner
docker compose --env-file "$env_file" -f "$compose" up -d --wait --no-deps api
docker compose --env-file "$env_file" -f "$compose" ps
