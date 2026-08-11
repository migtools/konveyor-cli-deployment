# MTA CLI E2E Tekton Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Konflux-triggered Tekton pipeline that provisions AWS VMs from AMIs, deploys MTA CLI via existing remote tooling, runs tier0 pytest on Linux/Windows/Darwin in parallel, and fails the PipelineRun if any OS fails.

**Architecture:** Shared `parse-metadata` + `prepare-workspace` (clone this repo, write CI `config.json`, derive `MTA_VERSION` from SNAPSHOT image), then three parallel OS lanes (provision EC2 → `install_cli.py --mta_version … --build stage` via the **existing** local/remote stage path → `prepare_remote_host.py` → pytest tier0 → collect reports → terminate on pass / TTL-tag on fail), then `aggregate-results`. Shared shell lives under `.tekton/integration-tests/scripts/` so the three OS tasks stay thin wrappers.

**Tech Stack:** Tekton Pipelines v1, AWS CLI (EC2), Python 3 (`install_cli.py` / `prepare_remote_host.py`), Paramiko SSH, pytest (`kantra-cli-tests`).

## Decision log

- **2026-08-11 — Keep existing stage/`pull_stage_ga` flow.** Stage/GA zips and images are pre-published from FBC to the same download locations `pull_stage_ga_*` already uses. Do **not** change `remote_deployment.py` / `local_deployment.py` precedence. Local and remote stay on the same code paths. Pipeline install command is effectively `./install_cli.py --mta_version <ver> --build stage --os <os> --platform amd64 --ip_address <ip>` (plus SSH config). No in-pipeline `misc-downstream` Konflux zip generation for v1.

## Global Constraints

- Pipeline file: `.tekton/integration-tests/mta-cli-e2e-pipeline.yaml`
- Trigger: Konflux IntegrationTestScenario with `SNAPSHOT`
- Platforms in one PipelineRun: linux, windows, darwin (parallel)
- Tests: tier0 only — default `pytest -s -v tests/tier0_tests.py --junitxml=junit.xml`
- VM lifecycle: terminate on success; on failure tag `ttl-delete-after` (+24h) and leave running
- One SSH key for all OSes; default user `ec2-user` (optional `SSH_USER_WINDOWS`)
- AMI baking and TTL janitor are out of scope
- **Do not modify** deploy precedence in `local_deployment.py` / `remote_deployment.py`; keep local and remote flows identical
- Install via existing stage path: `--mta_version` + `--build stage` (+ `--os` / `--platform` / `--ip_address` for remote)
- Do not commit secrets, AMI IDs that are personal, or large zip binaries

## File Structure

| Path | Responsibility |
|------|----------------|
| `.tekton/integration-tests/scripts/extract_version_from_image.sh` | Parse MTA version from FBC/image reference in SNAPSHOT. |
| `.tekton/integration-tests/scripts/prepare_workspace.sh` | Clone this repo, write CI `config.json` (ssh_user/ssh_key), record `MTA_VERSION`. |
| `.tekton/integration-tests/scripts/provision_ec2.sh` | `aws ec2 run-instances` from AMI; emit instance id + public IP. |
| `.tekton/integration-tests/scripts/wait_for_ssh.sh` | Poll SSH until ready. |
| `.tekton/integration-tests/scripts/cleanup_ec2.sh` | Terminate on pass; tag TTL on fail. |
| `.tekton/integration-tests/scripts/run_os_e2e.sh` | One OS lane: provision → stage deploy → prepare → pytest → collect → cleanup. |
| `.tekton/integration-tests/scripts/aggregate_results.sh` | Fail if any OS status ≠ PASSED. |
| `.tekton/integration-tests/mta-cli-e2e-pipeline.yaml` | Tekton Pipeline wiring params, secrets volumes, tasks, results. |
| `docs/superpowers/specs/2026-08-10-mta-cli-e2e-tekton-design.md` | Design; amend install path note if it still describes in-pipeline zip generation. |
| `README.md` | Short section: Konflux secrets, params, how to register IntegrationTestScenario. |

---

### Task 1: EC2 lifecycle scripts

**Files:**
- Create: `.tekton/integration-tests/scripts/provision_ec2.sh`
- Create: `.tekton/integration-tests/scripts/wait_for_ssh.sh`
- Create: `.tekton/integration-tests/scripts/cleanup_ec2.sh`
- Create: `tests/test_ec2_scripts_smoke.sh`

**Interfaces:**
- Consumes: env `AWS_REGION`, `AMI_ID`, `INSTANCE_TYPE`, `KEY_NAME`, `SECURITY_GROUP_ID`, `SUBNET_ID` (optional), `SSH_USER`, `SSH_KEY`, `INSTANCE_ID`, `OUTCOME` (`PASSED`|`FAILED`), `FAILURE_TTL_HOURS`, `PIPELINE_RUN_NAME`
- Produces:
  - `provision_ec2.sh` prints `INSTANCE_ID=...` and `PUBLIC_IP=...` and writes them to paths in `$RESULT_DIR`
  - `cleanup_ec2.sh` terminates or tags; exit 0

- [ ] **Step 1: Write smoke test script (fail before files exist)**

```bash
# tests/test_ec2_scripts_smoke.sh
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPTS="$ROOT/.tekton/integration-tests/scripts"
test -x "$SCRIPTS/provision_ec2.sh"
test -x "$SCRIPTS/wait_for_ssh.sh"
test -x "$SCRIPTS/cleanup_ec2.sh"
# Syntax check only (no AWS calls)
bash -n "$SCRIPTS/provision_ec2.sh"
bash -n "$SCRIPTS/wait_for_ssh.sh"
bash -n "$SCRIPTS/cleanup_ec2.sh"
echo "OK"
```

- [ ] **Step 2: Run smoke test — expect fail (missing scripts)**

Run: `bash tests/test_ec2_scripts_smoke.sh`

Expected: FAIL with `No such file or directory`

- [ ] **Step 3: Implement `provision_ec2.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
: "${AWS_REGION:?}" "${AMI_ID:?}" "${INSTANCE_TYPE:?}" "${KEY_NAME:?}"
: "${RESULT_DIR:?}"
SECURITY_GROUP_ID="${SECURITY_GROUP_ID:-}"
SUBNET_ID="${SUBNET_ID:-}"

ARGS=(
  ec2 run-instances
  --region "$AWS_REGION"
  --image-id "$AMI_ID"
  --instance-type "$INSTANCE_TYPE"
  --key-name "$KEY_NAME"
  --count 1
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=mta-cli-e2e},{Key=mta-cli-e2e,Value=true},{Key=mta-cli-e2e-pipeline-run,Value=${PIPELINE_RUN_NAME:-unknown}}]"
  --query 'Instances[0].InstanceId'
  --output text
)
[[ -n "$SECURITY_GROUP_ID" ]] && ARGS+=(--security-group-ids "$SECURITY_GROUP_ID")
[[ -n "$SUBNET_ID" ]] && ARGS+=(--subnet-id "$SUBNET_ID")

INSTANCE_ID="$(aws "${ARGS[@]}")"
echo -n "$INSTANCE_ID" > "$RESULT_DIR/instance-id"
aws ec2 wait instance-running --region "$AWS_REGION" --instance-ids "$INSTANCE_ID"

PUBLIC_IP="$(aws ec2 describe-instances --region "$AWS_REGION" --instance-ids "$INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)"
echo -n "$PUBLIC_IP" > "$RESULT_DIR/public-ip"
echo "INSTANCE_ID=$INSTANCE_ID"
echo "PUBLIC_IP=$PUBLIC_IP"
```

- [ ] **Step 4: Implement `wait_for_ssh.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
: "${PUBLIC_IP:?}" "${SSH_USER:?}" "${SSH_KEY:?}"
RETRIES="${SSH_RETRIES:-60}"
for i in $(seq 1 "$RETRIES"); do
  if ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=5 \
      -i "$SSH_KEY" "${SSH_USER}@${PUBLIC_IP}" "echo ok" >/dev/null 2>&1; then
    echo "SSH ready on ${PUBLIC_IP}"
    exit 0
  fi
  echo "Waiting for SSH ($i/$RETRIES)..."
  sleep 10
done
echo "SSH not ready after retries" >&2
exit 1
```

- [ ] **Step 5: Implement `cleanup_ec2.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
: "${AWS_REGION:?}" "${INSTANCE_ID:?}" "${OUTCOME:?}"
FAILURE_TTL_HOURS="${FAILURE_TTL_HOURS:-24}"
PIPELINE_RUN_NAME="${PIPELINE_RUN_NAME:-unknown}"

if [[ "$OUTCOME" == "PASSED" ]]; then
  aws ec2 terminate-instances --region "$AWS_REGION" --instance-ids "$INSTANCE_ID"
  echo "Terminated $INSTANCE_ID"
  exit 0
fi

TTL="$(date -u -d "+${FAILURE_TTL_HOURS} hours" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null \
  || date -u -v+"${FAILURE_TTL_HOURS}"H +%Y-%m-%dT%H:%M:%SZ)"
aws ec2 create-tags --region "$AWS_REGION" --resources "$INSTANCE_ID" --tags \
  "Key=mta-cli-e2e,Value=true" \
  "Key=mta-cli-e2e-pipeline-run,Value=${PIPELINE_RUN_NAME}" \
  "Key=ttl-delete-after,Value=${TTL}"
echo "Left $INSTANCE_ID running; ttl-delete-after=$TTL"
```

- [ ] **Step 6: chmod +x and re-run smoke test**

```bash
chmod +x .tekton/integration-tests/scripts/*.sh
bash tests/test_ec2_scripts_smoke.sh
```

Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add .tekton/integration-tests/scripts/provision_ec2.sh \
  .tekton/integration-tests/scripts/wait_for_ssh.sh \
  .tekton/integration-tests/scripts/cleanup_ec2.sh \
  tests/test_ec2_scripts_smoke.sh
git commit -m "$(cat <<'EOF'
Add AWS EC2 provision, SSH wait, and cleanup helpers.

Scripts support terminate-on-pass and 24h TTL tagging on failure
for the MTA CLI E2E Tekton lanes.
EOF
)"
```

---

### Task 2: Workspace prep, OS lane, and aggregate scripts

**Files:**
- Create: `.tekton/integration-tests/scripts/extract_version_from_image.sh`
- Create: `.tekton/integration-tests/scripts/prepare_workspace.sh`
- Create: `.tekton/integration-tests/scripts/run_os_e2e.sh`
- Create: `.tekton/integration-tests/scripts/aggregate_results.sh`
- Modify: `tests/test_ec2_scripts_smoke.sh` (extend to syntax-check new scripts)
- Create: `tests/test_extract_version.sh`

**Interfaces:**
- `extract_version_from_image.sh <image-ref>` → prints `X.Y.Z` to stdout
- `prepare_workspace.sh` env: `WORK_DIR`, `FBC_IMAGE`, `SSH_USER`, `SSH_KEY`, `DEPLOY_REPO_URL`, `DEPLOY_REPO_REVISION`
- Produces under `$WORK_DIR/`: cloned `konveyor-cli-deployment`, `artifacts/config.json`, `artifacts/mta-version`
- `run_os_e2e.sh` env: OS lane params; writes `$RESULT_DIR/testStatus` (`PASSED`|`FAILED`) and copies reports to `$RESULT_DIR/reports/`
- `aggregate_results.sh` args: three status files; exit 1 if any ≠ `PASSED`

- [ ] **Step 1: Write version extraction test**

```bash
# tests/test_extract_version.sh
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$ROOT/.tekton/integration-tests/scripts/extract_version_from_image.sh"
IMG='quay.io/redhat-user-workloads/ocp-art-tenant/art-fbc:v4.21__operator_nvr__mta-operator-container-8.1.3-202607312122.p2.gf5b3f83.assembly.stream.el9'
got="$("$SCRIPT" "$IMG")"
[[ "$got" == "8.1.3" ]] || { echo "expected 8.1.3 got $got"; exit 1; }
echo "OK"
```

- [ ] **Step 2: Run — expect fail (missing script)**

Run: `bash tests/test_extract_version.sh`

Expected: FAIL missing script

- [ ] **Step 3: Implement `extract_version_from_image.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
IMAGE="${1:?image ref required}"
if [[ "$IMAGE" =~ mta-operator-container-([0-9]+\.[0-9]+\.[0-9]+) ]]; then
  echo "${BASH_REMATCH[1]}"
  exit 0
fi
if [[ "$IMAGE" =~ mta-([0-9]+\.[0-9]+\.[0-9]+) ]]; then
  echo "${BASH_REMATCH[1]}"
  exit 0
fi
echo "Could not parse MTA version from image: $IMAGE" >&2
exit 1
```

- [ ] **Step 4: Re-run version test — expect PASS**

Run: `bash tests/test_extract_version.sh`

- [ ] **Step 5: Implement `prepare_workspace.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
: "${WORK_DIR:?}" "${FBC_IMAGE:?}" "${SSH_USER:?}" "${SSH_KEY:?}"
DEPLOY_REPO_URL="${DEPLOY_REPO_URL:-https://github.com/migtools/konveyor-cli-deployment.git}"
DEPLOY_REPO_REVISION="${DEPLOY_REPO_REVISION:-main}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

mkdir -p "$WORK_DIR/artifacts" "$WORK_DIR/tmp"
cd "$WORK_DIR"
rm -rf konveyor-cli-deployment
git clone --depth 1 --branch "$DEPLOY_REPO_REVISION" "$DEPLOY_REPO_URL" konveyor-cli-deployment

MTA_VERSION="$("$SCRIPT_DIR/extract_version_from_image.sh" "$FBC_IMAGE")"
echo -n "$MTA_VERSION" > "$WORK_DIR/artifacts/mta-version"

# Stage/GA path does not need misc-downstream; keep placeholders so config.load still works.
cat > konveyor-cli-deployment/config.json <<EOF
{
  "misc_downstream_path": "${WORK_DIR}/tmp/misc-downstream/",
  "temp_dir": "${WORK_DIR}/tmp/",
  "extract_binary": "mta-cli-binary-extract.py",
  "extract_binary_konflux": "mta-cli-binary-extract-konflux.py",
  "get_images_output": "get-image-build-details.py ",
  "bundle": "--bundle mta-operator-bundle-container-",
  "no_brew": "--no-brew",
  "ssh_user": "${SSH_USER}",
  "ssh_key": "${SSH_KEY}"
}
EOF

cp konveyor-cli-deployment/config.json "$WORK_DIR/artifacts/config.json"
cd konveyor-cli-deployment
pip3 install -r requirements.txt
echo "prepare_workspace done (MTA_VERSION=$MTA_VERSION)"
```

- [ ] **Step 6: Implement `run_os_e2e.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
: "${WORK_DIR:?}" "${RESULT_DIR:?}" "${TARGET_OS:?}" "${AMI_ID:?}" "${INSTANCE_TYPE:?}"
: "${AWS_REGION:?}" "${KEY_NAME:?}" "${SSH_USER:?}" "${SSH_KEY:?}" "${MTA_VERSION:?}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TEST_COMMAND="${TEST_COMMAND:-pytest -s -v tests/tier0_tests.py --junitxml=junit.xml}"
FAILURE_TTL_HOURS="${FAILURE_TTL_HOURS:-24}"
PLATFORM="${PLATFORM:-amd64}"
OUTCOME="FAILED"
INSTANCE_ID=""

cleanup() {
  if [[ -n "${INSTANCE_ID}" ]]; then
    OUTCOME="$OUTCOME" INSTANCE_ID="$INSTANCE_ID" AWS_REGION="$AWS_REGION" \
      FAILURE_TTL_HOURS="$FAILURE_TTL_HOURS" PIPELINE_RUN_NAME="${PIPELINE_RUN_NAME:-unknown}" \
      "$SCRIPT_DIR/cleanup_ec2.sh" || true
  fi
  echo -n "$OUTCOME" > "$RESULT_DIR/testStatus"
}
trap cleanup EXIT

mkdir -p "$RESULT_DIR/reports" "$RESULT_DIR/ec2"
RESULT_DIR="$RESULT_DIR/ec2" AWS_REGION="$AWS_REGION" AMI_ID="$AMI_ID" INSTANCE_TYPE="$INSTANCE_TYPE" \
  KEY_NAME="$KEY_NAME" SECURITY_GROUP_ID="${SECURITY_GROUP_ID:-}" SUBNET_ID="${SUBNET_ID:-}" \
  PIPELINE_RUN_NAME="${PIPELINE_RUN_NAME:-unknown}" \
  "$SCRIPT_DIR/provision_ec2.sh"
INSTANCE_ID="$(cat "$RESULT_DIR/ec2/instance-id")"
PUBLIC_IP="$(cat "$RESULT_DIR/ec2/public-ip")"

PUBLIC_IP="$PUBLIC_IP" SSH_USER="$SSH_USER" SSH_KEY="$SSH_KEY" "$SCRIPT_DIR/wait_for_ssh.sh"

cd "$WORK_DIR/konveyor-cli-deployment"
# Same stage flow as local/remote today: pull_stage_ga_* via --build stage
./install_cli.py \
  --mta_version "$MTA_VERSION" \
  --build stage \
  --os "$TARGET_OS" \
  --platform "$PLATFORM" \
  --ip_address "$PUBLIC_IP"

./prepare_remote_host.py --ip_address "$PUBLIC_IP" --os "$TARGET_OS"

# shellcheck disable=SC2086
ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i "$SSH_KEY" \
  "${SSH_USER}@${PUBLIC_IP}" "cd kantra-cli-tests && ${TEST_COMMAND}"

scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i "$SSH_KEY" -r \
  "${SSH_USER}@${PUBLIC_IP}:kantra-cli-tests/junit.xml" \
  "${SSH_USER}@${PUBLIC_IP}:kantra-cli-tests/htmlcov" \
  "$RESULT_DIR/reports/" 2>/dev/null || true

OUTCOME="PASSED"
```

- [ ] **Step 7: Implement `aggregate_results.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
LINUX_STATUS="$(cat "${1:?}")"
WINDOWS_STATUS="$(cat "${2:?}")"
DARWIN_STATUS="$(cat "${3:?}")"
OUT="${4:?}"
{
  echo "linux=$LINUX_STATUS"
  echo "windows=$WINDOWS_STATUS"
  echo "darwin=$DARWIN_STATUS"
} | tee "$OUT"
if [[ "$LINUX_STATUS" != PASSED || "$WINDOWS_STATUS" != PASSED || "$DARWIN_STATUS" != PASSED ]]; then
  echo "One or more OS lanes failed" >&2
  exit 1
fi
```

- [ ] **Step 8: chmod, extend smoke syntax checks, run tests**

```bash
chmod +x .tekton/integration-tests/scripts/*.sh tests/*.sh
bash tests/test_extract_version.sh
bash -n .tekton/integration-tests/scripts/prepare_workspace.sh
bash -n .tekton/integration-tests/scripts/run_os_e2e.sh
bash -n .tekton/integration-tests/scripts/aggregate_results.sh
```

Expected: all OK / exit 0

- [ ] **Step 9: Commit**

```bash
git add .tekton/integration-tests/scripts/ tests/test_extract_version.sh tests/test_ec2_scripts_smoke.sh
git commit -m "$(cat <<'EOF'
Add workspace prep, OS-lane, and aggregate scripts for CLI E2E.

Uses existing --build stage deploy path on each VM; no in-pipeline
misc-downstream zip generation.
EOF
)"
```

---

### Task 3: Pipeline YAML — skeleton, parse-metadata, prepare-workspace

**Files:**
- Create: `.tekton/integration-tests/mta-cli-e2e-pipeline.yaml`
- Create: `tests/test_pipeline_yaml_structure.sh`

**Interfaces:**
- Pipeline params match the design table (`SNAPSHOT`, AMIs, region, instance types, `TEST_COMMAND`, `FAILURE_TTL_HOURS`, SSH users, `KEY_NAME`, `SECURITY_GROUP_ID`, `SUBNET_ID`, repo URLs)
- Workspace `shared-workspace` for cloned deploy tree between prepare and OS tasks
- Secret volumes: `aws-cli-e2e-credentials`, `aws-vm-ssh-key` (names documented; overridable later)
- No `MISC_DOWNSTREAM_URL` param for v1

- [ ] **Step 1: Write structure test**

```bash
# tests/test_pipeline_yaml_structure.sh
#!/usr/bin/env bash
set -euo pipefail
YML=".tekton/integration-tests/mta-cli-e2e-pipeline.yaml"
test -f "$YML"
grep -q 'name: mta-cli-e2e-pipeline' "$YML"
grep -q 'name: SNAPSHOT' "$YML"
grep -q 'name: parse-metadata' "$YML"
grep -q 'name: prepare-workspace' "$YML"
grep -q 'name: linux-e2e' "$YML"
grep -q 'name: windows-e2e' "$YML"
grep -q 'name: darwin-e2e' "$YML"
grep -q 'name: aggregate-results' "$YML"
grep -q 'AMI_LINUX' "$YML"
grep -q 'FAILURE_TTL_HOURS' "$YML"
echo "OK"
```

- [ ] **Step 2: Run — expect fail**

Run: `bash tests/test_pipeline_yaml_structure.sh`

Expected: missing YAML

- [ ] **Step 3: Create pipeline skeleton with parse-metadata + prepare-workspace**

Create `.tekton/integration-tests/mta-cli-e2e-pipeline.yaml` with:

- `apiVersion: tekton.dev/v1` / `kind: Pipeline` / `metadata.name: mta-cli-e2e-pipeline`
- Params from the design (AMI_* default empty; set by IntegrationTestScenario)
- Extra params: `KEY_NAME`, `SECURITY_GROUP_ID` (default `""`), `SUBNET_ID` (default `""`), `DEPLOY_REPO_URL`, `DEPLOY_REPO_REVISION` (default `main`)
- Results: `TEST_OUTPUT`, `LINUX_STATUS`, `WINDOWS_STATUS`, `DARWIN_STATUS`
- Workspace: `shared-workspace`
- Task `parse-metadata`: same git resolver as FBC pipeline (`konflux-ci/integration-examples` … `tasks/test_metadata.yaml` at revision `a1a70b0a1cfc96f5216d472fbd60f6b42780b3e5`)
- Task `prepare-workspace` (`runAfter: [parse-metadata]`):
  - Mount workspace + SSH key secret
  - Bootstrap-clone or use scripts already expected after first clone; call `prepare_workspace.sh` with `FBC_IMAGE` from parse-metadata result
  - Write `prepareStatus` result

Stub OS tasks (`linux-e2e`, `windows-e2e`, `darwin-e2e`) and `aggregate-results` with minimal `PASSED` writers so the structure test passes; real wiring in Task 4.

- [ ] **Step 4: Run structure test — expect PASS**

Run: `bash tests/test_pipeline_yaml_structure.sh`

- [ ] **Step 5: Commit**

```bash
git add .tekton/integration-tests/mta-cli-e2e-pipeline.yaml tests/test_pipeline_yaml_structure.sh
git commit -m "$(cat <<'EOF'
Add MTA CLI E2E Tekton pipeline skeleton.

Wire SNAPSHOT parse-metadata and workspace preparation; OS lanes
stubbed for the next commit.
EOF
)"
```

---

### Task 4: Wire real OS lanes + aggregate

**Files:**
- Modify: `.tekton/integration-tests/mta-cli-e2e-pipeline.yaml`

**Interfaces:**
- Each OS task consumes workspace + AWS secret (`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` or shared credentials file under `/tekton/home/.aws`) + SSH key
- Results per OS: `testStatus`
- `aggregate-results` `runAfter: [linux-e2e, windows-e2e, darwin-e2e]`, maps pipeline results, exits non-zero on failure

- [ ] **Step 1: Replace linux-e2e stub with full taskSpec**

Params into the task: `ami`, `instanceType`, `targetOs`, `sshUser`, `mtaVersion`, plus shared AWS/SSH/KEY/SG/subnet/TTL/testCommand/pipelineRunName.

Script outline:

```bash
#!/bin/bash
set -euo pipefail
export WORK_DIR=/workspace
export RESULT_DIR=/workspace/results/linux
export TARGET_OS=linux
export AMI_ID="$(params.ami)"
export INSTANCE_TYPE="$(params.instanceType)"
export SSH_USER="$(params.sshUser)"
export SSH_KEY=/secrets/aws-vm-login-key.pem
export MTA_VERSION="$(params.mtaVersion)"
export AWS_REGION="$(params.awsRegion)"
export KEY_NAME="$(params.keyName)"
export SECURITY_GROUP_ID="$(params.securityGroupId)"
export SUBNET_ID="$(params.subnetId)"
export TEST_COMMAND="$(params.testCommand)"
export FAILURE_TTL_HOURS="$(params.failureTtlHours)"
export PIPELINE_RUN_NAME="$(context.pipelineRun.name)"
mkdir -p "$RESULT_DIR"
/workspace/konveyor-cli-deployment/.tekton/integration-tests/scripts/run_os_e2e.sh
cp "$RESULT_DIR/testStatus" "$(results.testStatus.path)"
```

Mount AWS credentials as env from secret `aws-cli-e2e-credentials` keys `aws_access_key_id` / `aws_secret_access_key` (document exact key names in README).

- [ ] **Step 2: Duplicate for windows-e2e and darwin-e2e**

Differences only: `TARGET_OS` / AMI param / instance type / `SSH_USER` (`SSH_USER_WINDOWS` for windows).

- [ ] **Step 3: Implement aggregate-results task**

```bash
#!/bin/bash
set -euo pipefail
/workspace/konveyor-cli-deployment/.tekton/integration-tests/scripts/aggregate_results.sh \
  "$(params.linuxStatus)" \
  "$(params.windowsStatus)" \
  "$(params.darwinStatus)" \
  "$(results.summary.path)"
```

Pass status via params from `$(tasks.linux-e2e.results.testStatus)` etc. Also set pipeline-level results from those task results.

- [ ] **Step 4: Re-run structure + syntax checks**

```bash
bash tests/test_pipeline_yaml_structure.sh
# optional if python-yq/yamllint available:
# yamllint -d relaxed .tekton/integration-tests/mta-cli-e2e-pipeline.yaml
```

Expected: OK

- [ ] **Step 5: Commit**

```bash
git add .tekton/integration-tests/mta-cli-e2e-pipeline.yaml
git commit -m "$(cat <<'EOF'
Wire parallel Linux/Windows/Darwin E2E lanes and aggregate.

Each lane provisions an AMI-backed VM, deploys CLI via --build stage,
runs tier0, and terminates or TTL-tags the instance based on outcome.
EOF
)"
```

---

### Task 5: README operator notes

**Files:**
- Modify: `README.md`

**Interfaces:**
- Documents secret names, required params, IntegrationTestScenario pointer, failure TTL behavior

- [ ] **Step 1: Append section to README**

Add a section titled `## Konflux / Tekton CLI E2E` covering:

1. Pipeline path: `.tekton/integration-tests/mta-cli-e2e-pipeline.yaml`
2. Required secrets in the Konflux namespace:
   - `aws-cli-e2e-credentials` (`aws_access_key_id`, `aws_secret_access_key`)
   - `aws-vm-ssh-key` (key `ssh-privatekey` or file mount as documented in the YAML)
3. Required IntegrationTestScenario params: `AMI_LINUX`, `AMI_WINDOWS`, `AMI_MAC`, `KEY_NAME`, and usually `SECURITY_GROUP_ID` / `SUBNET_ID`
4. Install path: existing `--mta_version` + `--build stage` (same as local/remote today; stage/GA artifacts pre-published)
5. Behavior: parallel OS lanes; pipeline fails if any tier0 fails; VMs terminated on pass; failed VMs tagged `ttl-delete-after` for 24h
6. Link to design spec: `docs/superpowers/specs/2026-08-10-mta-cli-e2e-tekton-design.md`

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "$(cat <<'EOF'
Document Konflux secrets and params for CLI E2E pipeline.

Operators need AMI/SSH/AWS configuration to register the
IntegrationTestScenario against stage CLI builds.
EOF
)"
```

---

## Spec coverage (self-review)

| Spec requirement | Task |
|------------------|------|
| SNAPSHOT trigger / parse-metadata | Task 3 |
| AWS VMs from AMIs | Tasks 1, 4 |
| Existing stage deploy (`pull_stage_ga_*`) | Tasks 2, 4 |
| Parallel linux/windows/darwin | Task 4 |
| Tier0 pytest | Task 2 (`run_os_e2e.sh`), Task 4 |
| JUnit + exit code | Task 2 |
| Fail PipelineRun if any OS fails | Tasks 2, 4 |
| Terminate on pass / TTL tag on fail | Tasks 1, 2 |
| Params + secrets | Tasks 3–5 |
| Pipeline under `.tekton/integration-tests/` | Task 3 |
| No deploy-path divergence local vs remote | Decision log (Task 1 precedence fix cancelled) |
| AMI baking / janitor / in-pipeline misc-downstream | Out of scope |

## Placeholder / consistency check

- Script paths and env var names are consistent across Tasks 1–4 (`RESULT_DIR`, `INSTANCE_ID`, `OUTCOME`, `ttl-delete-after`).
- Deploy CLI flags use `--ip_address` (not `--ip`) and `--build stage` without requiring `--image` / `--dependency_file`.
- Secret names in YAML and README must match: `aws-cli-e2e-credentials`, `aws-vm-ssh-key`.

## Execution Handoff

Plan updated 2026-08-11 (keep stage flow; no deploy precedence change). Saved to `docs/superpowers/plans/2026-08-11-mta-cli-e2e-tekton.md`.

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks

**2. Inline Execution** — execute tasks in this session with checkpoints

Which approach? (User already chose 1; start at Task 1 = EC2 scripts.)

