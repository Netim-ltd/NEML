<!-- Copyright (c) 2026 Mustafa Gulsoy. -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# NEML on Rancher

## Deployment decision

Rancher is deferred for the first NEML installation. The stated single
1 CPU / 2 GB server cannot reasonably host Rancher Manager and this platform.
For the first laboratory deployment, use a small Docker Compose control plane
with PostgreSQL and heavy simulation/CAD/LLM workers on other hosts. Keep this
Helm chart for a later multi-node deployment or a managed Rancher cluster.
The chart is a prepared packaging artifact, not evidence of live deployment.

The deployment target is a Rancher-managed Kubernetes cluster. The stated
1 CPU / 2 GB RAM / 200 GB disk server is also intended to host Rancher Manager.
**Do not install Rancher Manager and NEML together on that server.** Rancher's
[management-cluster installation requirements](https://ranchermanager.docs.rancher.com/getting-started/installation-and-upgrade/installation-requirements)
list 4 vCPUs and 16 GB RAM per node for the small production tier, and a
three-node highly available setup for production. A single 1 CPU / 2 GB node
is below that size. This chart is prepared for a larger or separately hosted
management setup; it cannot make the undersized server production-ready.

Even on an adequately sized cluster, this chart deploys only the brain control
plane. PostgreSQL, vLLM, embedding, simulation and fabrication services must
run on separately sized nodes or external hosts. Do not schedule GPU/CAD
workloads on the small server. Reserve node memory for Kubernetes and the OS.

## Rancher Desktop on Windows

Install Rancher Desktop and enable its Moby container engine. Windows also needs
WSL and hardware virtualization. Copy `.env.example` to `.env`, fill in the lab
secrets, and check the GPU prerequisites for the vLLM service. Do not commit
`.env` or private keys.

From PowerShell in the repository root:

```powershell
.\scripts\setup\prepare_rancher_desktop.ps1 -StartRuntime -BuildImages
.\scripts\setup\prepare_rancher_desktop.ps1 -StartServices
```

The script refuses to start with a placeholder PostgreSQL password, validates
Compose, migrates the database before starting the application, and leaves the model TLS proxy disabled until real certificates and a
LAN bind address are configured. The current Compose stack expects Linux
containers and an NVIDIA GPU for vLLM. Rancher Desktop does not by itself
provide robot hardware, ROS 2 on the host, or a Gazebo physics installation.

## Rancher Manager cluster

Rancher Manager runs on a Kubernetes cluster. The `deploy/rancher` Helm chart
packages the lab brain as a private ClusterIP workload. Build and push the brain
image first, then provide one namespace and one release per firm. Supply a
pre-existing Secret named by `existingSecret` with `dbUrl`, `cloudWs`, and
`apiKey`; add `modelSigningSeed` only when physical model transport is ready.
The chart runs Alembic as a pre-install/pre-upgrade Job and stores artifacts,
work files and the outbox on a persistent volume. Its Service has no Ingress.
The placeholder registry in `values.yaml` is intentionally rejected by the
chart schema; set a real image repository in the firm-specific values file.

The chart expects separately provisioned PostgreSQL, vLLM, embedding, and MCP
services, configured in `values.yaml`. It does not package a GPU scheduler,
Gazebo host, printer, or CAD machines. NEML's existing GPU mutex uses a Docker
socket, so visual simulation and shared-GPU scheduling need a Kubernetes-aware
adapter or dedicated isolated GPU resources before use. Do not expose the brain
Service publicly; the three signed model endpoints need a narrow TLS gateway.

The Rancher UI can import this chart from a Git repository. With Helm CLI, the
equivalent command after populating firm-specific values and Secrets is:

1. Import the cluster kubeconfig. Rename its imported context to `neml-rancher`
   after checking its server address and certificate.
2. Build and push the image to your Docker Hub namespace. Authenticate with
   `docker login` through your local credential store; do not put a token in a
   command argument or this repository.
3. Create one namespace and one separate PostgreSQL database per firm. In that
   namespace, create `neml-brain-secrets` with `dbUrl`, `cloudWs`, `apiKey`,
   and optionally `modelSigningSeed`. Provide a registry pull Secret in
   `imagePullSecrets` if the Docker Hub repository is private.
4. Create a firm values file outside the repository or in an ignored path.
   Set `image.repository` to `docker.io/<your-namespace>/neml-brain`, and set
   real URLs for every external dependency. Then run the preflight and deploy.
   The chart can also be packaged and pushed as an OCI artifact to Docker Hub;
   Rancher Apps supports OCI chart repositories.

```powershell
.\scripts\release\push_rancher_images.ps1 -DockerHubNamespace <your-namespace> -Tag 1.0 -Push
helm registry login registry-1.docker.io
.\scripts\release\push_rancher_chart.ps1 -DockerHubNamespace <your-namespace> -Push
.\scripts\setup\preflight_rancher_cluster.ps1 -Context neml-rancher `
  -Namespace <firm-namespace> -ValuesFile <firm-values.yaml>
.\scripts\setup\preflight_rancher_cluster.ps1 -Context neml-rancher `
  -Namespace <firm-namespace> -ValuesFile <firm-values.yaml> -Deploy
```

The first preflight only reads the cluster and renders the chart. The second
command performs the installation after checking that the namespace and
Secret already exist. The Helm migration hook changes the firm's database.
Do not reuse one database or Secret across firms; the existing legacy API
tables are not safe for shared multi-tenancy.

Alternatively, the Rancher UI can install the chart from a Git repository.
In Rancher, use **Apps > Repositories** to add the Docker Hub OCI chart
repository, then install `neml-brain` from **Apps > Charts**. The chart version
is `0.1.0`, while the brain container tag is configured separately in values.
The three model ticket/download/ack paths can be exposed with `edgeIngress`
only after an ingress controller, a trusted TLS Secret and a real DNS name are
available. Its paths use `Exact`; the rest of the brain API stays private.

The corresponding CLI form is:

```text
helm upgrade --install neml-brain ./deploy/rancher \
  --kube-context neml-rancher \
  --namespace <firm-namespace> --create-namespace \
  --values <firm-values.yaml>
```

The local Rancher Desktop script must not be pointed at a remote cluster.
`neml-rancher` is the intended local kubeconfig context name; the actual
cluster URL and credentials must be imported before using that name.

## Readiness

The platform's signed model API is only one part of a real deployment. Before
physical rollout, connect and validate the policy-bearing Gazebo adapter, run
the migration against a disposable database, verify the robot-side agent and
hardware safety envelope, and exercise canary and rollback with real devices.
