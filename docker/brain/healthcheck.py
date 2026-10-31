# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Container health check for the SPEC 6.2 MCP daemons.

They speak Streamable HTTP and have no /health route, so the probe is the one
round trip every MCP server must answer: `initialize`.

Usage: python mcp_health.py http://127.0.0.1:9101/mcp
"""

import json
import sys
import urllib.request

body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}).encode()
request = urllib.request.Request(  # noqa: S310 - fixed localhost URL from the compose file
    sys.argv[1], data=body, headers={"Content-Type": "application/json"}
)
with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310
    payload = json.load(response)
sys.exit(0 if "result" in payload else 1)
