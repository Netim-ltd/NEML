#!/usr/bin/env bash
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
set -euo pipefail
# The host name is not in the repository: the workflow passes the repository variable NEML_DOMAIN (or /srv/neml/deploy.env holds it); panel., api. and lab. hang off it.
[[ -n "${NEML_DOMAIN:-}" || ! -f /srv/neml/deploy.env ]] || . /srv/neml/deploy.env
: "${NEML_DOMAIN:?set NEML_DOMAIN in /srv/neml/deploy.env}"
sha="${1:?release SHA required}"
[[ "$sha" =~ ^[a-f0-9]{40}$ ]] || { echo "invalid release SHA" >&2; exit 2; }
release="/srv/neml/releases/$sha"
web="/srv/neml/web/releases/$sha"
[[ -s "$web/index.html" ]] || { echo "Flutter artifact missing" >&2; exit 1; }
compose="$release/docker/compose.panel.yml"
[[ -f "$compose" ]] || { echo "panel compose missing" >&2; exit 1; }
previous="$(readlink -f /srv/neml/web/current 2>/dev/null || true)"
if docker container inspect neml-panel >/dev/null 2>&1; then
  managed="$(docker inspect neml-panel --format '{{index .Config.Labels "com.docker.compose.project"}}')"
  if [[ "$managed" != neml-panel ]]; then
    docker rm -f neml-panel >/dev/null
  fi
fi
cp "$release/deploy/nginx/neml-panel-unprivileged.conf" /srv/neml/neml-panel.conf
ln -sfn "$web" /srv/neml/web/current.next
mv -Tf /srv/neml/web/current.next /srv/neml/web/current
if ! docker compose -f "$compose" up -d --force-recreate --wait panel; then
  if [[ -n "$previous" && -s "$previous/index.html" ]]; then
    ln -sfn "$previous" /srv/neml/web/current.next
    mv -Tf /srv/neml/web/current.next /srv/neml/web/current
    docker compose -f "$compose" up -d --force-recreate --wait panel
  fi
  exit 1
fi
if ! curl --fail --silent --show-error --max-time 15 https://panel.${NEML_DOMAIN}/ >/dev/null; then
  if [[ -n "$previous" && -s "$previous/index.html" ]]; then
    ln -sfn "$previous" /srv/neml/web/current.next
    mv -Tf /srv/neml/web/current.next /srv/neml/web/current
    docker compose -f "$compose" up -d --force-recreate --wait panel
  fi
  exit 1
fi
printf '%s\n' "$sha" > /srv/neml/web/deployed-sha
