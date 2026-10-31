<!-- Copyright (c) 2026 Mustafa Gulsoy. -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
# NEML small control server

This is the first deployment target for the stated **1 CPU, 2 GB RAM, 200 GB**
server. It runs only the NEML brain and its database migration using Docker
Compose. PostgreSQL, model inference, embeddings, FreeCAD, KiCad, Blender,
simulation and fabrication workers run on other hosts. Docker Hub holds the
`neml-brain` image. The machine does not run Rancher Manager.

The Compose limits are 0.75 CPU / 1 GiB for the brain, and 0.5 CPU / 512 MiB
for the short-lived migration. These are resource ceilings, not a measured
capacity guarantee. Leave space for Docker and the operating system. Heavy
jobs must stay on the other machines.

## Prepare

1. Provision external PostgreSQL with its own database, least-privilege NEML
   user, backups and TLS certificate. Use a hostname matching the certificate.
   The connection URL must include `sslmode=verify-full`.
2. Provision the cloud bridge, LLM, embedding service and each MCP service on
   other hosts. Their URLs must use WSS/HTTPS. Restrict access through a private
   network and authenticate at the gateway; TLS alone does not authorize MCP
   calls. Keep CAD and robot hardware behind that gateway.
3. Build and push the brain image from a development machine with Docker:

   ```powershell
   docker login
   .\scripts\release\push_rancher_images.ps1 -DockerHubNamespace YOUR_NAMESPACE -Tag 1.0 -Push
   ```

   Docker CLI stores the login in its configured credential store. Use a
   private repository and `docker login` on the server if the image is private.
4. On the Linux server, install Docker Engine with the Compose plugin, copy
   the repository, and copy `.env.control.example` to `.env` in its root.
   Replace every placeholder. Set `.env` permissions to owner-read only.
   Generate `NEML_MODEL_SIGNING_SEED` as 32 cryptographically random bytes in
   hexadecimal. Keep the seed and database password outside Git and backups
   with broad access. Use separate databases and secrets per customer.
   Set `NEML_TENANT_ID` to that customer's tenant and generate a distinct
   `NEML_TRAINING_EXPORT_KEY` for the GPU worker. The learning flow is in
   `docs/NIGHTLY_LORA.md`.
   Set `NEML_OWNERS` to the comma-separated identities of real owner accounts
   before requesting level 4 physical approval. An empty value keeps that
   approval level closed.

## Check and deploy

### Push-triggered deployment

`.github/workflows/deploy-control.yml` runs only after the `CI` workflow
succeeds for the current `main` commit. It builds `neml-brain:sha-<commit>` on
the GitHub runner, pushes it to Docker Hub, transfers a versioned Compose
snapshot over pinned-host-key SSH, and deploys it on the control server. A
missing Docker Hub token or deploy SSH key leaves this workflow green with a
notice and skips publication until the environment is provisioned. A
failed health check leaves the release unmarked as current. Database migrations
are forward only; a failed deployment needs investigation before an older image
is restarted.

Configure the `control-production` GitHub environment with variable
`DOCKERHUB_NAMESPACE` and secrets `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`,
`DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`, `DEPLOY_KNOWN_HOSTS`. The deploy
user needs permission to write `/srv/neml/releases`, update `/srv/neml/current`,
and run Docker Compose. Put the private `.env` at `/srv/neml/shared/.env`, with
its namespace matching the GitHub variable. Log the server into Docker Hub if
the repository is private. Restrict the GitHub environment to `main`. Leave
control-plane deployment without a required
reviewer if every successful push should deploy automatically. Robot motion
releases retain their separate approval path.

Git pushes produce control-plane images and deployments. Physical robot model
rollout remains under the API's signed ticket, human approval, canary,
acknowledgement, and rollback path. Robot **software** and firmware do not yet
have an attested OTA executor; do not point CI directly at motor-controller
flash or ROS 2 installation until that path is implemented and tested on the
actual robot hardware.

From the repository root on the server:

```bash
chmod 600 .env
bash scripts/setup/deploy_control.sh --check
bash scripts/setup/deploy_control.sh --deploy
```

The check validates required values, secure remote URL schemes, the database
TLS mode, loopback binding and Docker Compose syntax. The deploy command pulls
the Docker Hub image, applies the Alembic migration, waits for the brain health
check and prints service status. It can be rerun for an image update after
changing `NEML_IMAGE_TAG`. A failed migration stops the brain from starting.
The brain API is bound only to `127.0.0.1:8080` by default. Place a separately
configured authenticated TLS gateway or VPN in front of any client access.

The optional `model-tls` profile exposes only the signed ticket, bundle and
acknowledgement routes on port 8443. Enable it only after setting real trusted
certificate/key files and a controlled bind address. Physical canary and fleet
deployment still require human approval and real robot validation.

## Readiness limits

The repository does not include credentials or access to the server, Docker
Hub namespace, external service hosts or robot devices. This package has not
been deployed there. The policy-bearing Gazebo adapter, real hardware safety
checks, and cross-firm isolation of the legacy API remain work before a
commercial physical rollout. This Compose setup is for one isolated tenant;
separate each firm's database and installation.
