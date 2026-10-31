<!-- Copyright (c) 2026 Mustafa Gulsoy. -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
# NEML public hosts

## Where the host name lives

No host name or address is in the code. Everything hangs off one base domain, `NEML_DOMAIN`
(below the examples use `neml.example.com`):

| Part | How it gets the domain |
| --- | --- |
| nginx (`deploy/nginx/*.conf`) | `envsubst '${NEML_DOMAIN}'` at deploy time (`deploy_release.sh`) |
| Deploy scripts (`scripts/setup/deploy_release.sh`, `deploy_panel.sh`) | `NEML_DOMAIN` from the environment, else `/srv/neml/deploy.env` on the host |
| GitHub workflow (`deploy-control.yml`) | repository variable `NEML_DOMAIN`, passed to the scripts |
| Brain settings | `scripts/setup/generate_secrets.py --domain <NEML_DOMAIN>` writes `NEML_CLOUD_WS` |
| .NET API CORS | `NEML_PUBLIC_URL`, `NEML_PANEL_URL` in `deploy/vps/.env` |
| Web screens (Blazor) | the address the page was opened from |
| Android build (`release.yml`) | repository variable `NEML_SERVER_URL` (`--dart-define`); the app also lets the operator change it |

The production namespace is `neml.example.com`. DNS currently maps the
following A records to `<SERVER_IP>` (your server's public address):

| Host | Role | Backend |
| --- | --- | --- |
| `panel.neml.example.com` | Flutter web operator UI | HTTPS static site |
| `api.neml.example.com` | .NET operator API, SignalR, outbound lab bridge | HTTPS reverse proxy to Neml.Api |
| `lab.neml.example.com` | Restricted robot model and feedback routes | Authenticated TLS gateway to brain |

The Flutter app defaults to `https://api.neml.example.com`. The .NET
API allows the exact origin `https://panel.neml.example.com`. The brain
uses `wss://api.neml.example.com/bridge/ws` with node ID
`neml-control-01`; its API key must equal the .NET `Bridge__ApiKey` setting.

The shared nginx instance runs in the `nginx-proxy` Docker container. Its host
configuration directory is `/opt/docker/nginx-proxy/conf.d` and its common
network is `nginx-proxy-network`. The NEML virtual host source is
`deploy/nginx/neml-proxy.conf`; the panel container uses
`deploy/nginx/neml-panel.conf`. The certificate is stored under
`/opt/docker/nginx-proxy/certbot/conf/live/neml.example.com` and covers
all three names.

As of 2026-10-02, the panel is live at
`https://panel.neml.example.com` and is served by the separate
`neml-panel` container. The API and lab hosts intentionally return HTTP 503
until their backends are provisioned. `/srv/neml/shared/.env` is absent, so the
brain is not deployed. Never replace these 503 responses with a success page
or proxy the brain's whole port 8080 to the public internet. The lab gateway
must expose only authenticated model and feedback endpoints. PostgreSQL, model
serving, embedding and MCP workers need provisioned hosts or private network
endpoints.

The `control-production` GitHub environment has two empty secrets awaiting
configuration: `NEML_API_ENV` and `NEML_BRAIN_ENV`. Fill the first from
`.env.api.example` and the second from `.env.control.example`, replacing all
example hosts, passwords, and keys. These are complete multiline `KEY=value`
files, not individual secret values. `Bridge__ApiKey` must equal `NEML_API_KEY`.
Use separate PostgreSQL databases for the API and brain. The API's first
deployment creates the owner account only when its email is absent; later
deployments do not reset the password. The brain's model, embedding and MCP
URLs can point to the same server or separate servers. They must be installed
and reachable before the brain can report healthy. The shared nginx publishes
the API and only the robot model/feedback routes from the brain.

Successful CI on `main` builds both Docker Hub images and a Flutter web
artifact. The deployment installs the tested panel artifact in a restricted
nginx container, transfers the two protected configuration files over SSH,
runs API and brain migrations, waits for health, and reloads the shared nginx.
Missing secrets or unhealthy backends fail the API/brain release. The control
release pointer advances only after both services pass. The panel can update
independently while backend provisioning is pending.

The shared nginx configuration currently cannot pass `nginx -t` while the
unrelated `yerimvar-api` container is stopped: its virtual host names that
container as a static upstream. The panel uses the already loaded route and
can update on port 80 without reloading nginx. API and lab activation needs
the shared nginx configuration to test and reload successfully.

The NEML deployment should be reported live only after the three HTTPS hosts
answer, login and SignalR work from the web origin, the bridge connects, the
brain health check is healthy, and a robot test has passed on actual hardware.
