<!-- Copyright (c) 2026 Mustafa Gulsoy. -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
# Nightly task-specific mini LLM adapters

The GPU worker trains one LoRA adapter per **firm and operation**. The NEML
control server does not train models. A separate adapter can serve, for example,
maintenance triage, work-order drafting, CAD review or field report summaries.
Safety control of moving robots stays in the deterministic policy and physical
approval path; generated text is never a direct motor command.

## Worker setup

### GPU Docker worker

`docker/compose.lora.yml` packages the same bounded trainer as a one-shot GPU
container. Run it on a machine with a working Docker engine and NVIDIA GPU
container support. Set `NEML_TRAINING_ROOT` to an absolute directory containing
`jobs/` and the tenant/domain trees described below. Give UID 10001 write
access to that directory. For API-sourced feedback set
`NEML_FEEDBACK_EXPORT_URL` and `NEML_TRAINING_EXPORT_KEY` in the worker's
private environment. From the repository root:

```bash
docker compose -f docker/compose.lora.yml build
docker compose -f docker/compose.lora.yml run --rm nightly
```

The command enforces the Istanbul night window and leaves each adapter as a
candidate. Schedule the command on the GPU host after 23:59 Istanbul time.
The 1 CPU control server and a 3 GB GTX 1050 are not certified as training
hosts; GPU memory and driver compatibility must be checked on the actual host.

Kaggle Notebooks can run a bounded batch training job if a private dataset and
private notebook are available. They are unsuitable for the always-on model
API or robot control plane. Do not upload customer feedback, model keys, or
API tokens to a public notebook or dataset. Kaggle account access and its
available accelerator must be verified before creating a job there.

Use a Linux GPU host with enough VRAM for the chosen base model. Install a
CUDA-compatible PyTorch build, then install
`scripts/platform/requirements-lora.txt`. Pin the base model to a specific
40-character Hugging Face commit in every job. The sample in
`config/lora-job.example.json` must be edited before use. One job JSON file
goes in `<root>/jobs/`; datasets and outputs must be under
`<root>/tenants/<tenant>/domains/<domain>/`. Protect that root with operating-system permissions.
The example uses NF4 QLoRA with gradient checkpointing for a 0.5B base model.
This follows the [Transformers bitsandbytes guidance](https://huggingface.co/docs/transformers/quantization/bitsandbytes).
Even with 4-bit weights, available VRAM and driver compatibility must be
measured on the actual GPU host. `quantization: none` is available for larger
GPU memory. The initial worker rejects models above 1.5B parameters.

For `source: robot_feedback`, the robots generate failure/recovery reports
during the day. Each robot signs its report. An **independent outcome verifier**
must check the physical postcondition and sign the same report before its
successful recovery becomes a training example. The verifier's key must differ
from the robot's key. Store reports in
`<root>/tenants/<tenant>/domains/<domain>/reports/` and trusted public keys in
the sibling `trust.json`:

```json
{
  "robots": {"robot-01": "64_HEX_CHARACTERS"},
  "verifiers": {"outcome-monitor-01": "64_HEX_CHARACTERS"}
}
```

The report contains `tenant_id`, `domain_id`, `robot_id`, `robot_type`,
`operation`, `report_id`, timezone-aware `occurred_at`, normalized `features`,
`failed_action`, `failure_class`, `recovery_action`, `outcome: success`,
`quality >= 0.95`, `verifier_id`, `robot_signature`, and
`verifier_signature`. Both signatures cover all fields except the signatures.
The edge telemetry callback can pass a completed trace to
`scripts/edge/emit_learning_report.py`, which uses the robot's existing device
key. A separate sensor monitor calls `attest_recovery` from
`brain/neml_brain/platform/feedback.py` with its physical postcondition check
and its own key. Copy only the fully attested report to the training host.
The ROS 2 `feedback_monitor` node can also collect traces from the robot's
`state/skill_outcome` topic. Enable it in `robot.launch.py` with
`enable_learning_feedback:=true` after provisioning `NEML_TENANT_ID`,
`NEML_DOMAIN_ID`, `NEML_ROBOT_ID`, `NEML_ROBOT_TYPE`,
`NEML_DEVICE_PRIVATE_KEY_FILE`, and `NEML_EDGE_REPORT_DIR`. The skill executor
must publish a JSON `std_msgs/String` per completed attempt with `task_id`,
`operation`, `action`, `success`, `failure_class`, `features` (normalized),
`quality`, and timezone-aware `occurred_at`. The node pairs a failure with a
different successful action on the same task within ten minutes. Only the
explicitly listed noncritical failure classes in `platform/recovery.py` can
enter LoRA data; e-stop, collision and unknown classes are excluded.
The node's report has only the robot signature; an independent sensor monitor
must sign it before upload. The repository has no physical skill executor or
skill outcome publisher, so those inputs remain deployment gates. For the
`stop` recovery action, `scripts/platform/stop_verifier_node.py` is an example
independent ROS 2 monitor. Run it on a **different host** with its own Ed25519
key. It requires `NEML_ROBOT_PUBLIC_KEY_FILE`,
`NEML_VERIFIER_PRIVATE_KEY_FILE`, `NEML_VERIFIER_REPORT_DIR`,
`NEML_VERIFIED_REPORT_DIR`, tenant/domain/robot IDs and `NEML_VERIFIER_ID`.
It requires 16 distinct joint names and velocities, plus fresh base linear and
angular motion measurements for a continuous two-second stationary window
after the report, then signs only that specific stop report. The robot state
and joint telemetry publishers must run at a rate
that keeps sample gaps below 500 ms. Other recovery actions need separate
measured postcondition adapters before they can enter training.
For a connected deployment, register the verifier public key after database
migration:

```bash
python scripts/platform/provision.py verifier TENANT DOMAIN outcome-monitor-01 \
  --public-key-file /secure/verifier-public.hex
```

Run `scripts/edge/upload_feedback.py --reports /path/to/attested-reports
--endpoint https://CONTROL-HOST:8443/v1/platform/feedback` on the verifier
host. The control API checks both registered signatures, stores each UUID once
and publishes a `RecoveryVerified` event without training content. The robot
device public key comes from the existing robot provisioning step.

On the GPU host, set `NEML_FEEDBACK_EXPORT_URL` to the exact HTTPS
`/v1/platform/feedback-export` endpoint and set the same long random
`NEML_TRAINING_EXPORT_KEY` used by the control server. `transport: control_api`
pulls reports and public keys before each nightly dataset build. The control
server restricts export to its configured `NEML_TENANT_ID`; the worker checks
tenant, domain, operation and both signatures again. Put the HTTPS endpoint
behind a private firewall or VPN.
The exporter rejects invalid signatures, duplicate report IDs, cross-domain
reports and low-quality outcomes. It labels the **successful recovery**, never
the failed action. The platform provides the report schema and exporter; the
actual sensor-based outcome verifier and robot telemetry hook still need to be
connected to hardware.

Alternatively, `source: curated` reads a prepared JSONL dataset with `prompt`,
`completion`, and `approved: true` fields. Distinct examples are split by a stable
hash; at least 32 training and 8 holdout examples must remain. A held-out loss
improvement over the base model is required, but it does **not** prove task
quality or physical safety. Collect consent and remove private material before
putting examples in the training directory.

Schedule once a night on the GPU host, for example a local cron entry at
`00:10 Europe/Istanbul`:

```bash
10 0 * * * /opt/neml-venv/bin/python /opt/neml/scripts/platform/nightly_lora.py --root /srv/neml-training
```

The dispatcher allows training only between 23:59 and 04:59 Istanbul time,
skips an unchanged dataset/base revision, and limits each job to four hours.
Training stops when the window ends and rejects a partial candidate. Each
successful run writes a candidate adapter and metadata under the operation's
output directory. Training, evaluation, and serving each require a GPU; the
1 CPU / 2 GB control server remains free for orchestration. Ensure the GPU
host's clock and timezone data are correct. The per-job 100-step bound is a
starting limit; tune it from measured task results.

## Service and promotion

Candidates do not become active automatically. After human review of the
holdout examples and task-specific acceptance tests, an operator can create an
activation JSON file such as:

```json
{
  "approved_by": "operator-name",
  "candidate_result": "tenants/example-firm/domains/field/models/maintenance-triage/candidates/RUN_ID/result.json"
}
```

On the GPU host, set a long random `NEML_LORA_API_KEY` and start one service
process per approved operation:

```bash
python scripts/platform/serve_lora.py --root /srv/neml-training \
  --activation /srv/neml-training/activations/maintenance-triage.json --port 8765
```

The service checks the candidate checksum and binds to loopback. It accepts
`POST /v1/operation/generate` with bearer authorization and JSON fields
`tenant`, `domain`, `operation`, `prompt`; all identities must match the active adapter.
Put a private authenticated TLS gateway in front of it for other hosts. The
activation file is a local operational control, not a cryptographic approval
record. Do not expose this prototype service directly to the Internet.

After approval, set `NEML_OPERATION_ROUTES` on the control node to a JSON
mapping such as
`{"field/maintenance-triage":{"url":"https://gpu.example/v1/operation/generate","adapter_sha256":"<64-hex-digest>"}}`.
Use the digest from the candidate's `result.json`; the control node refuses a
response from another adapter.
Set `NEML_OPERATION_SERVICE_KEY` equal to the GPU service's `NEML_LORA_API_KEY`
and set a different `NEML_OPERATION_CLIENT_KEY` for authorized callers. The
control API's `POST /v1/platform/operation/generate` routes only configured
domain/operation pairs and returns advisory text. Its output is not connected
to actuation or the constrained robot command graph.

## Current integration limit

This adds an offline LoRA workflow, signed feedback API and storage, GPU pull,
dataset build, task-specific inference service and fixed control-plane routes.
No real GPU host, sensor outcome verifier, robot telemetry hook or physical
regression environment was provided. The control-plane planner deliberately
does not execute generated advice. Automatic publication into a robot fleet
remains disabled.
