# MTA CLI E2E Tekton Pipeline — Design

**Date:** 2026-08-10  
**Status:** Approved for implementation planning  
**Repo:** `migtools`-owned `konveyor-cli-deployment` (this repo; may move later)  
**Reference:** [mta-fbc-e2e-pipeline.yaml](https://github.com/migtools/mta-tackle2-ui/blob/main/.tekton/integration-tests/mta-fbc-e2e-pipeline.yaml) (operator FBC E2E; cluster-based)

## Problem

The draft MTA operator FBC E2E Tekton pipeline provisions an ephemeral OpenShift cluster, installs the operator from FBC, and runs UI Cypress tests. MTA CLI testing does not need a cluster. It needs OS hosts (Windows, Linux/RHEL9, macOS), remote CLI deployment, and a tier0 pytest suite.

Today this is driven by Jenkins: Mac VMs are provisioned on AWS; Windows and Linux run as long-lived OpenStack VMs (OpenStack is being sunset). Deployment already exists in this repo via `install_cli.py` (remote SSH) and `prepare_remote_host.py` (`kantra-cli-tests`).

## Goals

1. Trigger when a new CLI stage build arrives (Konflux IntegrationTestScenario + `SNAPSHOT`).
2. Provision **all** test VMs on AWS from pre-baked AMIs/snapshots (AMI baking is manual / out of scope).
3. Generate dependency zips and image lists via `misc-downstream` (cloned beside this repo), then remote-deploy with existing Python tooling.
4. Run tier0 tests on Linux, Windows, and Darwin in parallel.
5. Collect JUnit/HTML/logs; fail the PipelineRun if any OS fails.
6. Destroy VMs on success; on failure keep VMs for debugging with a 24h TTL tag.

## Non-goals

- Baking AMIs/snapshots
- Implementing the TTL janitor/cron (pipeline only writes tags)
- Full (non-tier0) test suite
- OpenStack or Jenkins cutover automation
- Moving the pipeline YAML to another repo (may happen later)

## Architecture

```text
SNAPSHOT (new CLI stage / FBC build)
        │
        ▼
┌───────────────────┐
│  parse-metadata   │  extract FBC/image URL (and version hints)
└─────────┬─────────┘
          ▼
┌───────────────────┐
│  prepare-artifacts│  clone konveyor-cli-deployment + misc-downstream
│                   │  generate image list + OS zips (linux/windows/darwin)
└─────────┬─────────┘
          ├──────────────┬──────────────┐
          ▼              ▼              ▼
   linux-e2e        windows-e2e      darwin-e2e
   (parallel)       (parallel)       (parallel)
          │              │              │
          └──────────────┴──────────────┘
                         ▼
              ┌─────────────────────┐
              │  aggregate-results  │  fail PipelineRun if any OS failed
              └─────────────────────┘
```

### Per-OS lane

1. Provision EC2 from the OS-specific AMI (AWS API credentials from a Secret).
2. Wait until SSH is reachable.
3. Remote deploy with existing tooling, e.g.:

   ```bash
   ./install_cli.py \
     --mta_version <version> \
     --build stage \
     --image <fbc-image-from-snapshot> \
     --dependency_file <path-to-os-zip> \
     --os <linux|windows|darwin> \
     --platform amd64 \
     --ip_address <vm-public-ip>
   ```

   Current manual example uses the FBC image tag that embeds the operator NVR, e.g. `mta-operator-container-8.1.3-202607312122.p2.gf5b3f83.assembly.stream.el9`, plus a pre-generated OS zip from `misc-downstream`.

4. Prepare the test host (`prepare_remote_host.py`): clone `kantra-cli-tests`, install requirements, write `.env`.
5. Run tier0 over SSH: `cd kantra-cli-tests; pytest -s -v tests/tier0_tests.py` (overridable).
6. SCP reports (JUnit/HTML) and relevant logs back into TaskRun artifacts; gate on pytest exit code.
7. Cleanup:
   - **Passed:** terminate the instance immediately.
   - **Failed / deploy error:** leave instance running; tag for 24h TTL (see below).

## Tasks

| Task | Responsibility |
|------|----------------|
| `parse-metadata` | Resolve component container image from `SNAPSHOT` (same git-resolved task pattern as the FBC pipeline). |
| `prepare-artifacts` | Clone this repo and `misc-downstream`; write CI `config.json`; run Konflux zip/image generation so Linux, Windows, and Darwin zips land in a shared workspace. |
| `linux-e2e` / `windows-e2e` / `darwin-e2e` | Provision → deploy → prepare tests → pytest tier0 → collect results → destroy or TTL-tag. |
| `aggregate-results` | Combine per-OS `testStatus`; expose pipeline results; fail if any OS is not `PASSED`. |

Approach choice: **shared prepare + three explicit parallel OS tasks** (not Tekton matrix, not sequential). Matrix can be considered later; Mac may need AWS special-casing (e.g. dedicated hosts) that is clearer as an explicit task.

## Parameters

| Param | Purpose | Default / notes |
|-------|---------|-----------------|
| `SNAPSHOT` | Konflux application snapshot JSON | Provided by IntegrationTestScenario |
| `AMI_LINUX` | RHEL9 (or equivalent) AMI ID | Required for real runs; placeholder OK in draft |
| `AMI_WINDOWS` | Windows AMI ID | Same |
| `AMI_MAC` | macOS AMI ID | Same; may require dedicated host / special instance type |
| `AWS_REGION` | AWS region for EC2 | e.g. `us-east-1` |
| `INSTANCE_TYPE_LINUX` / `_WINDOWS` / `_MAC` | EC2 instance types | Sensible defaults; Mac often differs |
| `TEST_COMMAND` | Remote pytest invocation | `pytest -s -v tests/tier0_tests.py` |
| `FAILURE_TTL_HOURS` | How long failed VMs may live | `24` |
| `SSH_USER` | Default SSH user | `ec2-user` |
| `SSH_USER_WINDOWS` | Windows SSH user if different | Default same as `SSH_USER` unless overridden |

## Secrets & config (not in git)

- **`aws-cli-e2e-credentials`** (name illustrative): AWS API access for provision/terminate/tag.
- **SSH private key**: one keypair for all OSes (matches current practice). Mounted into the task filesystem (e.g. `/secrets/aws-vm-login-key.pem`).
- Optional **`GIT_USERNAME` / `GIT_PASSWORD`**: required by `kantra-cli-tests` for some scenarios (see README).

`prepare-artifacts` writes a CI `config.json` analogous to local usage:

```json
{
  "misc_downstream_path": "<workspace>/misc-downstream/",
  "extract_binary": "mta-cli-binary-extract.py",
  "extract_binary_konflux": "mta-cli-binary-extract-konflux.py",
  "get_images_output": "get-image-build-details.py ",
  "bundle": "--bundle mta-operator-bundle-container-",
  "no_brew": "--no-brew",
  "ssh_user": "ec2-user",
  "ssh_key": "/secrets/aws-vm-login-key.pem"
}
```

No new remote protocol: `install_cli.py` and `prepare_remote_host.py` continue to read `ssh_user` / `ssh_key` from config.

## Artifact preparation

- Clone `misc-downstream` beside `konveyor-cli-deployment` inside the task workspace (same layout as local development).
- Generate dependency files and the list of images to pull once in `prepare-artifacts`, producing OS-specific zip paths for linux/windows/darwin.
- Upload/use the correct zip per OS lane via `--dependency_file` (as in the existing remote deploy command).
- Image pulls for the remote host remain the responsibility of the existing remote deployment path (Podman on the VM, etc.).

## Results & pass/fail

- Each OS task writes `testStatus`: `PASSED` or `FAILED`.
- Collect both:
  - **Exit code** from pytest (primary gate).
  - **Report files** (JUnit/XML, HTML, logs) via SCP when present.
- `aggregate-results` fails the PipelineRun if any OS failed. Tier0 only — full suite is intentionally out of scope because it is known to have persistent failures.

## VM lifecycle & tags

On failure (or deploy error after the instance exists), tag the instance, for example:

- `mta-cli-e2e=true`
- `mta-cli-e2e-pipeline-run=<PipelineRun name>`
- `ttl-delete-after=<RFC3339 timestamp now + FAILURE_TTL_HOURS>`

On success: terminate immediately.

Use a shell `trap` / always-run step so terminate-or-tag still runs if pytest or deploy crashes mid-flight.

**Janitor:** a separate scheduled cleanup for past-due `ttl-delete-after` tags is expected later; not part of the v1 pipeline YAML.

## Repo layout

```text
.tekton/integration-tests/
  mta-cli-e2e-pipeline.yaml
docs/superpowers/specs/
  2026-08-10-mta-cli-e2e-tekton-design.md
```

## Comparison to operator FBC pipeline

| Aspect | Operator FBC E2E | CLI E2E (this design) |
|--------|------------------|------------------------|
| Trigger | `SNAPSHOT` | `SNAPSHOT` |
| Environment | Ephemeral Hypershift cluster (EAAS) | AWS EC2 from AMIs |
| Install | Operator from FBC CatalogSource | `misc-downstream` zips + `install_cli.py` over SSH |
| Tests | Cypress login (UI) | `kantra-cli-tests` tier0 pytest |
| Platforms | One cluster | Linux + Windows + Darwin in parallel |
| Teardown | Cluster lifecycle via EAAS | Terminate on pass; TTL tag on fail |

## Open implementation details (for the plan, not blockers)

- Exact Konflux component name / SNAPSHOT JSON path for the FBC image used by CLI stage builds.
- Whether Mac requires EC2 dedicated hosts and how that is expressed in the darwin task.
- Precise pytest JUnit flags/`--junitxml` path used by `kantra-cli-tests`.
- Secret names as registered in the target Konflux tenant namespace.
- Whether `prepare-artifacts` needs registry credentials to run `misc-downstream` Konflux extract scripts.
