#!/bin/sh
# Ship the code to the host and restart only the services named (default: brain), so a running design
# in the brain is not cut by an unrelated deploy.
# Usage (from deploy/vps): ./ship.sh [brain] [api] [mcp-kicad] [mcp-cad] ...
set -eu
[ -f ship.sh ] || { echo "run from deploy/vps: cd deploy/vps && ./ship.sh <service>" >&2; exit 1; }
host="${NEML_HOST:-neml}"
what="${*:-brain}"
tar -C ../.. -cf - brain/neml_brain mcp_servers docker hardware config deploy/vps/compose.yml | ssh "$host" 'tar -C ~/neml -xf -'
case " $what " in *" api "*) ./publish-api.sh "$host" ;; esac
ssh "$host" "cd ~/neml/deploy/vps && sudo docker compose build $what && sudo docker compose up -d --no-build $what"
