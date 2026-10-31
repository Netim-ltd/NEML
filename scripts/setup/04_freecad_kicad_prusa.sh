#!/usr/bin/env bash
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# NEML_SPEC.md 17.4 step 1 - the three design tools, installed as separate
# programs. SPEC 1.3 is the rule that shapes this file: FreeCAD (LGPL), KiCad
# (GPL-3.0) and PrusaSlicer (AGPL-3.0) are never linked into NEML and never
# copied into the tree. They are installed here and invoked as subprocesses.
# Idempotent.
#
#   sudo scripts/setup/04_freecad_kicad_prusa.sh

set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "run with sudo" >&2; exit 1; }
export DEBIAN_FRONTEND=noninteractive

# PrusaSlicer ships as an AppImage. Pin it here; override to move version.
PRUSASLICER_VERSION="${PRUSASLICER_VERSION:-2.8.1}"
PRUSASLICER_URL="${PRUSASLICER_URL:-https://github.com/prusa3d/PrusaSlicer/releases/download/version_${PRUSASLICER_VERSION}/PrusaSlicer-${PRUSASLICER_VERSION}+linux-x64-GTK3-202409181416.AppImage}"
PRUSA_DIR=/opt/neml/prusaslicer

echo "== freecad (LGPL - headless freecadcmd, SPEC 12.1) =="
apt-get update -qq
apt-get install -y --no-install-recommends freecad-python3 python3-numpy || apt-get install -y freecad
if command -v freecadcmd >/dev/null; then
    freecadcmd --version | head -n 1
else
    echo "WARNING: freecadcmd not on PATH. Install the FreeCAD AppImage and point"
    echo "         FREECADCMD_BIN at its freecadcmd (mcp_servers/neml_mcp_cad reads it)."
fi

echo
echo "== kicad (GPL-3.0 - kicad-cli only, SPEC 13.1 scope) =="
if ! command -v kicad-cli >/dev/null; then
    apt-get install -y --no-install-recommends software-properties-common
    add-apt-repository -y ppa:kicad/kicad-9.0-releases
    apt-get update -qq
    apt-get install -y --no-install-recommends kicad
fi
kicad-cli version

echo
echo "== prusaslicer + gcode viewer (AGPL-3.0 - subprocess only, SPEC 1.3) =="
if [[ ! -x "${PRUSA_DIR}/AppRun" ]]; then
    echo "verifying ${PRUSASLICER_URL}"
    curl -fsIL "${PRUSASLICER_URL}" >/dev/null || {
        echo "ERROR: that AppImage URL is dead. Open the PrusaSlicer releases page," >&2
        echo "       pick the current linux-x64 AppImage and re-run with" >&2
        echo "       PRUSASLICER_URL=<url> sudo scripts/setup/04_freecad_kicad_prusa.sh" >&2
        exit 1
    }
    tmp="$(mktemp -d)"
    curl -fsSL "${PRUSASLICER_URL}" -o "${tmp}/prusaslicer.AppImage"
    chmod +x "${tmp}/prusaslicer.AppImage"
    # Extracted, not mounted: no FUSE on a headless box, and an extracted tree
    # is what the mcp-fab container can bind-mount later.
    (cd "${tmp}" && ./prusaslicer.AppImage --appimage-extract >/dev/null)
    install -d /opt/neml
    rm -rf "${PRUSA_DIR}"
    mv "${tmp}/squashfs-root" "${PRUSA_DIR}"
    rm -rf "${tmp}"
fi

# SPEC 17.3 names these two paths in .env.example; keep them true.
ln -sf "${PRUSA_DIR}/AppRun" /usr/bin/prusa-slicer
cat > /usr/bin/prusa-gcodeviewer <<EOF
#!/usr/bin/env bash
# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
# SPEC 6.4 - the same AppImage in G-code viewer mode.
exec ${PRUSA_DIR}/AppRun --gcodeviewer "\$@"
EOF
chmod 0755 /usr/bin/prusa-gcodeviewer

prusa-slicer --help >/dev/null 2>&1 && echo "prusa-slicer: ok (${PRUSASLICER_VERSION})"

echo
echo "== slicer profiles (SPEC 12.4) =="
install -d /srv/neml/config/slicer_profiles
repo_profiles="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/manufacturing/slicer_profiles"
cp -f "${repo_profiles}"/*.ini /srv/neml/config/slicer_profiles/
ls -1 /srv/neml/config/slicer_profiles/

echo
echo "04_freecad_kicad_prusa.sh done. Next: scripts/setup/05_mcp_servers.sh (no sudo)"
