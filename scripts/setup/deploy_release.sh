#!/usr/bin/env bash
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
set -euo pipefail
# The host name is not in the repository: the workflow passes the repository variable NEML_DOMAIN (or /srv/neml/deploy.env holds it); panel., api. and lab. hang off it.
[[ -n "${NEML_DOMAIN:-}" || ! -f /srv/neml/deploy.env ]] || . /srv/neml/deploy.env
: "${NEML_DOMAIN:?set NEML_DOMAIN in /srv/neml/deploy.env}"
previous_release="$(readlink -f /srv/neml/current 2>/dev/null || true)"
proxy_backed_up=0
rollback() {
  trap - ERR
  set +e
  echo "Deployment failed; restoring previous NEML release" >&2
  if [[ "$proxy_backed_up" == 1 ]]; then
    cp /opt/docker/nginx-proxy/conf.d/neml.conf.prev /opt/docker/nginx-proxy/conf.d/neml.conf
    docker exec nginx-proxy nginx -t && docker exec nginx-proxy nginx -s reload
  fi
  if [[ -f /srv/neml/shared/api.env.previous ]]; then
    mv /srv/neml/shared/api.env.previous /srv/neml/shared/api.env
  fi
  if [[ -f /srv/neml/shared/.env.previous ]]; then
    mv /srv/neml/shared/.env.previous /srv/neml/shared/.env
  fi
  if [[ "$previous_release" == /srv/neml/releases/* && -f "$previous_release/docker/compose.api.yml" ]]; then
    export NEML_IMAGE_TAG="sha-${previous_release##*/}"
    export NEML_API_ENV_FILE=/srv/neml/shared/api.env
    export NEML_CONTROL_ENV_FILE=/srv/neml/shared/.env
    bash "$previous_release/scripts/setup/deploy_api.sh"
    bash "$previous_release/scripts/setup/deploy_control.sh" --deploy
  fi
}
trap rollback ERR

if [[ $# -ne 3 ]]; then
  echo "usage: deploy_release.sh SHA DOCKERHUB_NAMESPACE RELEASE_ROOT" >&2
  exit 2
fi
sha="$1"
namespace="$2"
release_root="$3"
[[ "$sha" =~ ^[a-f0-9]{40}$ ]] || { echo "invalid commit SHA" >&2; exit 2; }
[[ "$namespace" =~ ^[a-z0-9][a-z0-9_-]*$ ]] || { echo "invalid namespace" >&2; exit 2; }
[[ "$release_root" == /srv/neml/releases ]] || { echo "invalid release root" >&2; exit 2; }
release="$release_root/$sha"
[[ -f "$release/docker/compose.control.yml" ]] || { echo "release missing compose" >&2; exit 1; }
[[ -f "$release/docker/compose.api.yml" ]] || { echo "release missing API compose" >&2; exit 1; }
[[ -f /srv/neml/shared/.env ]] || { echo "shared .env missing" >&2; exit 1; }
[[ -f /srv/neml/shared/api.env ]] || { echo "API env missing" >&2; exit 1; }
export NEML_CONTROL_ENV_FILE=/srv/neml/shared/.env
export NEML_API_ENV_FILE=/srv/neml/shared/api.env
export NEML_DOCKERHUB_NAMESPACE="$namespace"
export NEML_IMAGE_TAG="sha-$sha"

# The repository snapshot contains only deployment code; all secrets stay in shared/.env.
cd "$release"
docker network inspect nginx-proxy-network >/dev/null
docker exec nginx-proxy nginx -t >/dev/null
bash scripts/setup/deploy_api.sh
proxy_config=/opt/docker/nginx-proxy/conf.d/neml.conf
cp "$proxy_config" "$proxy_config.prev"
proxy_backed_up=1
envsubst '${NEML_DOMAIN}' < "$release/deploy/nginx/neml-proxy-live.conf" > "$proxy_config"
if ! docker exec nginx-proxy nginx -t; then
  cp "$proxy_config.prev" "$proxy_config"
  docker exec nginx-proxy nginx -t
  rollback
  exit 1
fi
docker exec nginx-proxy nginx -s reload
curl --fail --silent --show-error --max-time 15 https://api.${NEML_DOMAIN}/health >/dev/null
bash scripts/setup/deploy_control.sh --check
bash scripts/setup/deploy_control.sh --deploy
docker exec neml-control-brain-1 python -c 'import json,urllib.request; h=json.load(urllib.request.urlopen("http://127.0.0.1:8080/health",timeout=10)); assert h["status"]=="ok",h.get("degraded")'
[[ "$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 15 https://lab.${NEML_DOMAIN}/)" == 404 ]]
mkdir -p /srv/neml
ln -sfn "$release" /srv/neml/current.next
mv -Tf /srv/neml/current.next /srv/neml/current
printf '%s\n' "$sha" > /srv/neml/deployed-sha
rm -f /srv/neml/shared/api.env.previous /srv/neml/shared/.env.previous
