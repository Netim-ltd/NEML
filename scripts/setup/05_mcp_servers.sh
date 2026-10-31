#!/usr/bin/env bash
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# NEML_SPEC.md 17.4 step 4 - external MCP servers (SPEC 6.1).
#
# SPEC 6.1 is explicit: every repository address below comes from pre-May-2026
# knowledge and MUST be verified before anything is installed. This script does
# the verification and prints the result for every row. A dead or moved address
# is not an error you work around - it is the documented signal to fall back to
# the SPEC 6.2 server we wrote ourselves.
#
# Nothing third-party is installed automatically: these processes sit next to
# hardware, so a human reads the licence and the code first. The script tells
# you exactly what to run for each address it verified.
# Idempotent, no sudo.
#
#   scripts/setup/05_mcp_servers.sh

set -euo pipefail

# name | candidate repo (SPEC 6.1) | confidence | fallback when dead
ROWS=(
  "freecad|https://github.com/neka-nat/freecad-mcp|medium|own:neml_mcp_cad (SPEC 6.2 #13, port 9104)"
  "kicad|https://github.com/lamaalrajih/kicad-mcp|medium|write one per SPEC 6.2 (scope is SPEC 13.1)"
  "ros2|https://github.com/lpigeon/ros-mcp-server|medium|none needed - ros_gz bridge already covers the sim path"
  "postgres|https://github.com/crystaldba/postgres-mcp|medium-high|own:neml_mcp_pg (SPEC 6.2, port 9106) - already in this tree"
  "filesystem|https://github.com/modelcontextprotocol/servers|high|own:neml_mcp_fs (SPEC 6.2, port 9107) - already in this tree"
  "git|https://github.com/modelcontextprotocol/servers|high|own:neml_mcp_git (SPEC 6.2, port 9108) - already in this tree"
  "fetch|https://github.com/modelcontextprotocol/servers|high|write one per SPEC 6.2 (allowlist only)"
  "docker|https://github.com/ckreiling/mcp-server-docker|low-medium|none needed - GpuLock talks to the socket itself (SPEC 4.5)"
  "openscad|https://github.com/jhacksman/OpenSCAD-MCP-Server|low|optional, skip - FreeCAD is the SPEC 2 decision"
)

# The install line for an address that verifies. Empty means "read it first".
declare -A INSTALL=(
  [filesystem]="npx -y @modelcontextprotocol/server-filesystem /srv/neml/work /srv/neml/artifacts"
  [git]="uvx mcp-server-git --repository /srv/neml/work/repo"
  [fetch]="uvx mcp-server-fetch"
)

echo "SPEC 6.1 verification - $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "------------------------------------------------------------------"

alive=(); dead=()
for row in "${ROWS[@]}"; do
    IFS='|' read -r name url confidence fallback <<< "${row}"
    code="$(curl -sS -o /dev/null -w '%{http_code}' -L --max-time 15 "${url}" || echo 000)"
    if [[ "${code}" == "200" ]]; then
        printf 'VERIFIED  %-11s %s (HTTP %s, confidence %s)\n' "${name}" "${url}" "${code}" "${confidence}"
        alive+=("${name}")
    else
        printf 'DEAD      %-11s %s (HTTP %s)\n' "${name}" "${url}" "${code}"
        printf '          fallback: %s\n' "${fallback}"
        dead+=("${name}")
    fi
done

echo "------------------------------------------------------------------"
echo "alive: ${#alive[@]}   dead/unreachable: ${#dead[@]}"
echo

if ((${#alive[@]})); then
    echo "Install these by hand after reading the repository and its licence"
    echo "(SPEC 1.3: GPL/AGPL code is never copied into this tree):"
    for name in "${alive[@]}"; do
        if [[ -n "${INSTALL[${name}]:-}" ]]; then
            printf '  %-11s %s\n' "${name}" "${INSTALL[${name}]}"
        else
            printf '  %-11s read the repo, then install per its README\n' "${name}"
        fi
    done
    echo
fi

if ((${#dead[@]})); then
    echo "For every DEAD row above, the architecture already has the way out"
    echo "(SPEC 6.2): write the server yourself, ~300-600 lines of Python over"
    echo "Streamable HTTP. Only config/mcp.yaml changes."
    echo
fi

echo "Record the outcome in mcp_servers/vendor/servers.yaml:"
echo "  verified: $(date -u +%Y-%m-%d)   for each address that answered 200"
echo "  verified: null                   for anything you did not verify -"
echo "                                   a server with verified: null is not installed."
echo

echo "== our own servers (SPEC 6.2) - no verification needed, they are in this tree =="
printf '  %-14s %s\n' "neml-mcp-sim" "port 9101  (Gazebo, deterministic seed + GPU mutex)"
printf '  %-14s %s\n' "neml-mcp-fab" "port 9102  (PrusaSlicer + G-code viewer + PrusaLink)"
printf '  %-14s %s\n' "neml-mcp-genome" "port 9103  (hardware genome)"
printf '  %-14s %s\n' "neml-mcp-cad" "port 9104  (FreeCAD wrapper - the freecad fallback)"
printf '  %-14s %s\n' "neml-mcp-pg" "port 9106  (READ-ONLY SQL - the postgres fallback, T-016)"
printf '  %-14s %s\n' "neml-mcp-fs" "port 9107  (two allowed paths - the filesystem fallback, T-016)"
printf '  %-14s %s\n' "neml-mcp-git" "port 9108  (the work repo only - the git fallback, T-016)"
printf '  %-14s %s\n' "neml-mcp-fetch" "port 9109  (docs-only web fetch, allowlist enforced in the server)"
echo
echo "Start them with:"
echo "  docker compose --env-file .env -f docker/compose.yml up -d \\"
echo "    mcp-sim mcp-fab mcp-genome mcp-cad mcp-pg mcp-fs mcp-git mcp-fetch"
echo
echo "T-016 asks that /health report every MCP green. Seven of the eight servers"
echo "in config/mcp.yaml are covered by the list above. The eighth is kicad (9105):"
echo "it needs kicad-cli, which arrives with T-093 in Faz 6. Until then a red"
echo "kicad line in /health is the correct answer, not a silent omission."
echo
echo "Before mcp-pg: create the READ-ONLY role (SPEC 6.1 #4). The GRANTs are"
echo "listed under postgres.required_grants in mcp_servers/vendor/servers.yaml;"
echo "POSTGRES_RO_USER and POSTGRES_RO_PASSWORD go in .env."
echo
echo "05_mcp_servers.sh done. Next: SPEC 17.4 step 5 (brain)."
