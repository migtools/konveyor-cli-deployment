# MTA CLI E2E Tekton Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Konflux-triggered Tekton pipeline that provisions AWS VMs from AMIs, deploys MTA CLI via existing remote tooling, runs tier0 pytest on Linux/Windows/Darwin in parallel, and fails the PipelineRun if any OS fails.

**Architecture:** Shared `parse-metadata` + `prepare-artifacts` (clone repos, run `misc-downstream` Konflux extract once), then three parallel OS lanes (provision EC2 → `install_cli.py` → `prepare_remote_host.py` → pytest tier0 → collect reports → terminate on pass / TTL-tag on fail), then `aggregate-results`. Shared shell lives under `.tekton/integration-tests/scripts/` so the three OS tasks stay thin wrappers.

**Tech Stack:** Tekton Pipelines v1, AWS CLI (EC2), Python 3 (`install_cli.py` / `prepare_remote_host.py`), Paramiko SSH, pytest (`kantra-cli-tests`), `misc-downstream` Konflux extract scripts.

## Global Constraints

- Pipeline file: `.tekton/integration-tests/mta-cli-e2e-pipeline.yaml`
- Trigger: Konflux IntegrationTestScenario with `SNAPSHOT`
- Platforms in one PipelineRun: linux, windows, darwin (parallel)
- Tests: tier0 only — default `pytest -s -v tests/tier0_tests.py --junitxml=junit.xml`
- VM lifecycle: terminate on success; on failure tag `ttl-delete-after` (+24h) and leave running
- One SSH key for all OSes; default user `ec2-user` (optional `SSH_USER_WINDOWS`)
- AMI baking and TTL janitor are out of scope
- Follow existing remote deploy CLI shape: `--mta_version`, `--build`, `--image`, `--dependency_file`, `--os`, `--platform`, `--ip_address`
- Do not commit secrets, AMI IDs that are personal, or large zip binaries

## File Structure

| Path | Responsibility |
|------|----------------|
| `remote_deployment.py` | Prefer `--image` / `--dependency_file` over stage/ga download path when those args are set (Konflux stage builds). |
| `tests/test_remote_deployment_precedence.py` | Unit tests for that precedence. |
| `.tekton/integration-tests/scripts/extract_version_from_image.sh` | Parse MTA version from FBC/image reference. |
| `.tekton/integration-tests/scripts/prepare_artifacts.sh` | Clone repos, write `config.json`, run Konflux zip generation, write zip path results. |
| `.tekton/integration-tests/scripts/provision_ec2.sh` | `aws ec2 run-instances` from AMI; emit instance id + public IP. |
| `.tekton/integration-tests/scripts/wait_for_ssh.sh` | Poll SSH until ready. |
| `.tekton/integration-tests/scripts/cleanup_ec2.sh` | Terminate on pass; tag TTL on fail. |
| `.tekton/integration-tests/scripts/run_os_e2e.sh` | One OS lane: provision → deploy → prepare → pytest → collect → cleanup. |
| `.tekton/integration-tests/scripts/aggregate_results.sh` | Fail if any OS status ≠ PASSED. |
| `.tekton/integration-tests/mta-cli-e2e-pipeline.yaml` | Tekton Pipeline wiring params, secrets volumes, tasks, results. |
| `docs/superpowers/specs/2026-08-10-mta-cli-e2e-tekton-design.md` | Already approved; do not rewrite unless behavior changes. |
| `README.md` | Short section: Konflux secrets, params, how to register IntegrationTestScenario. |

---

### Task 1: Fix remote deploy precedence for Konflux image + zip

**Files:**
- Modify: `remote_deployment.py`
- Create: `tests/test_remote_deployment_precedence.py`

**Interfaces:**
- Consumes: `run_remote_deployment(data)` dict keys already used by `install_cli.py`
- Produces: When `image` and/or `args_dependency_file` are set for MTA ≥ 8.1.0, use Konflux path even if `build` is `stage`/`candidate`/`ga`

Today, for version ≥ 8.1.0, `build == "stage"` always calls `pull_stage_ga_*` and ignores `--image` / `--dependency_file`. Manual Konflux stage deploys pass all three; the pipeline needs the image+zip path.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_remote_deployment_precedence.py
from unittest.mock import MagicMock, patch

import remote_deployment


def _base_data(**overrides):
    data = {
        "version": "8.1.3",
        "build": "stage",
        "image": "quay.io/example/art-fbc:v4.21__operator_nvr__mta-operator-container-8.1.3-build",
        "normalized_url": "",
        "args_image_output_file": None,
        "args_dependency_file": "/tmp/mta-8.1.3-cli-darwin-amd64.zip",
        "args_ip_address": "1.2.3.4",
        "args_os": "darwin",
        "args_platform": "amd64",
        "args_upstream": None,
        "install_path": None,
    }
    data.update(overrides)
    return data


@patch("remote_deployment.unpack_zip")
@patch("remote_deployment.get_target_dependency_path", return_value="/home/ec2-user/.kantra")
@patch("remote_deployment.generate_konflux_zip")
@patch("remote_deployment.pull_images_by_list")
@patch("remote_deployment.generate_konflux_images_list", return_value={"related_images": []})
@patch("remote_deployment.normalise_url", return_value="registry.stage.example/bundle")
@patch("remote_deployment.ensure_podman_running")
@patch("remote_deployment.remove_old_images")
@patch("remote_deployment.pull_stage_ga_images")
@patch("remote_deployment.pull_stage_ga_dependency_file")
@patch("remote_deployment.connect_ssh")
def test_image_and_dependency_file_win_over_stage_build(
    mock_ssh,
    mock_stage_zip,
    mock_stage_images,
    mock_remove,
    mock_podman,
    mock_norm,
    mock_img_list,
    mock_pull,
    mock_gen_zip,
    mock_target,
    mock_unpack,
):
    client = MagicMock()
    mock_ssh.return_value = client

    remote_deployment.run_remote_deployment(_base_data())

    mock_stage_zip.assert_not_called()
    mock_stage_images.assert_not_called()
    mock_unpack.assert_called_once()
    args, kwargs = mock_unpack.call_args
    assert args[0] == "/tmp/mta-8.1.3-cli-darwin-amd64.zip"
    assert kwargs.get("client") is client or args[2] is client
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_remote_deployment_precedence.py -v`

Expected: FAIL — `pull_stage_ga_dependency_file` was called (or unpack used stage zip), because current code takes the stage branch first.

- [ ] **Step 3: Implement minimal precedence fix**

In `remote_deployment.py`, inside the `version_tuple >= (8, 1, 0)` branch, change the condition so Konflux path runs when `image` or `arg_dependency_file` is set:

```python
            else:
                use_konflux = bool(image) or bool(arg_dependency_file)
                if (build == "stage" or build == "candidate" or build == "ga") and not use_konflux:
                    pull_stage_ga_images(version, build, client=client)
                    full_zip_name = pull_stage_ga_dependency_file(version, build, host_os, host_platform)
                else:
                    logging.info(f"Deploying MTA Version: {version}, image: {image}")
                    if not normalized_url or normalized_url == "":
                        normalized_url = normalise_url(version, image) if image else ""
                    if not arg_dependency_file:
                        if not image_output_file:
                            logging.info(f"Generating images list for {version}, image: {image}")
                            image_list = generate_konflux_images_list(url=normalized_url)
                        else:
                            logging.info(f"Using images list provided as CLI argument: {image_output_file}")
                            image_list = generate_konflux_images_list(file=image_output_file)
                        pull_images_by_list(version, image_list, client=client)
                        logging.info(f"Generating dependencies zip for {version}, image: {image}")
                        zip_folder_name = generate_konflux_zip(normalized_url)
                        zip_name = get_zip_name(version, host_os, host_platform)
                        full_zip_name = os.path.join(config.MISC_DOWNSTREAM_PATH, zip_folder_name, zip_name)
                    else:
                        if image:
                            if not normalized_url or normalized_url == "":
                                normalized_url = normalise_url(version, image)
                            if not image_output_file:
                                image_list = generate_konflux_images_list(url=normalized_url)
                            else:
                                image_list = generate_konflux_images_list(file=image_output_file)
                            pull_images_by_list(version, image_list, client=client)
                        full_zip_name = arg_dependency_file
                        logging.info(f"Using existing dependencies zip: {full_zip_name}")
```

Keep the `< 8.1.0` branch unchanged.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_remote_deployment_precedence.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add remote_deployment.py tests/test_remote_deployment_precedence.py
git commit -m "$(cat <<'EOF'
Prefer Konflux image/zip args over stage download path.

Remote deploy ignored --image/--dependency_file when --build stage;
CLI E2E and manual Konflux stage installs need those args to win.
EOF
)"
```

---

### Task 2: EC2 lifecycle scripts

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

### Task 3: Artifact prep, OS lane, and aggregate scripts

**Files:**
- Create: `.tekton/integration-tests/scripts/extract_version_from_image.sh`
- Create: `.tekton/integration-tests/scripts/prepare_artifacts.sh`
- Create: `.tekton/integration-tests/scripts/run_os_e2e.sh`
- Create: `.tekton/integration-tests/scripts/aggregate_results.sh`
- Modify: `tests/test_ec2_scripts_smoke.sh` (extend to syntax-check new scripts)
- Create: `tests/test_extract_version.sh`

**Interfaces:**
- `extract_version_from_image.sh <image-ref>` → prints `X.Y.Z` to stdout
- `prepare_artifacts.sh` env: `WORK_DIR`, `FBC_IMAGE`, `MTA_VERSION`, `SSH_USER`, `SSH_KEY`, `DEPLOY_REPO_URL`, `DEPLOY_REPO_REVISION`, `MISC_DOWNSTREAM_URL`
- Produces under `$WORK_DIR/artifacts/`: `linux.zip.path`, `windows.zip.path`, `darwin.zip.path`, `config.json`, cloned trees
- `run_os_e2e.sh` env: OS lane params + paths; writes `$RESULT_DIR/testStatus` (`PASSED`|`FAILED`) and copies reports to `$RESULT_DIR/reports/`
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

- [ ] **Step 5: Implement `prepare_artifacts.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
: "${WORK_DIR:?}" "${FBC_IMAGE:?}" "${MTA_VERSION:?}" "${SSH_USER:?}" "${SSH_KEY:?}"
DEPLOY_REPO_URL="${DEPLOY_REPO_URL:-https://github.com/migtools/konveyor-cli-deployment.git}"
DEPLOY_REPO_REVISION="${DEPLOY_REPO_REVISION:-main}"
MISC_DOWNSTREAM_URL="${MISC_DOWNSTREAM_URL:?misc-downstream git URL required}"

mkdir -p "$WORK_DIR"
cd "$WORK_DIR"
rm -rf konveyor-cli-deployment misc-downstream artifacts
git clone --depth 1 --branch "$DEPLOY_REPO_REVISION" "$DEPLOY_REPO_URL" konveyor-cli-deployment
git clone --depth 1 "$MISC_DOWNSTREAM_URL" misc-downstream

cat > konveyor-cli-deployment/config.json <<EOF
{
  "misc_downstream_path": "${WORK_DIR}/misc-downstream/",
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

mkdir -p "$WORK_DIR/tmp" "$WORK_DIR/artifacts"
cd konveyor-cli-deployment
pip3 install -r requirements.txt

# Generate Konflux zips once (all OS archives land under misc-downstream extract folder)
python3 - <<'PY'
import os, json
from config import set_config
import config
from utils.utils import normalise_url
from utils.zip import generate_konflux_zip, get_zip_name

work = os.environ["WORK_DIR"]
version = os.environ["MTA_VERSION"]
image = os.environ["FBC_IMAGE"]
with open("config.json") as f:
    set_config(json.load(f))
normalized = normalise_url(version, image)
folder = generate_konflux_zip(normalized)
assert folder, "generate_konflux_zip failed"
art = os.path.join(work, "artifacts")
for os_name in ("linux", "windows", "darwin"):
    z = os.path.join(config.MISC_DOWNSTREAM_PATH, folder, get_zip_name(version, os_name, "amd64"))
    assert os.path.isfile(z), f"missing zip {z}"
    with open(os.path.join(art, f"{os_name}.zip.path"), "w") as out:
        out.write(z)
print("artifacts ready")
PY

cp konveyor-cli-deployment/config.json "$WORK_DIR/artifacts/config.json"
echo "prepare_artifacts done"
```

- [ ] **Step 6: Implement `run_os_e2e.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
: "${WORK_DIR:?}" "${RESULT_DIR:?}" "${TARGET_OS:?}" "${AMI_ID:?}" "${INSTANCE_TYPE:?}"
: "${AWS_REGION:?}" "${KEY_NAME:?}" "${SSH_USER:?}" "${SSH_KEY:?}"
: "${FBC_IMAGE:?}" "${MTA_VERSION:?}" "${DEPENDENCY_ZIP:?}"
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
./install_cli.py \
  --mta_version "$MTA_VERSION" \
  --build stage \
  --image "$FBC_IMAGE" \
  --dependency_file "$DEPENDENCY_ZIP" \
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
bash -n .tekton/integration-tests/scripts/prepare_artifacts.sh
bash -n .tekton/integration-tests/scripts/run_os_e2e.sh
bash -n .tekton/integration-tests/scripts/aggregate_results.sh
```

Expected: all OK / exit 0

- [ ] **Step 9: Commit**

```bash
git add .tekton/integration-tests/scripts/ tests/test_extract_version.sh tests/test_ec2_scripts_smoke.sh
git commit -m "$(cat <<'EOF'
Add prepare, OS-lane, and aggregate scripts for CLI E2E.

Shared shell drives artifact generation and per-OS remote tier0
execution used by the Tekton pipeline.
EOF
)"
```

---

### Task 4: Pipeline YAML — skeleton, parse-metadata, prepare-artifacts

**Files:**
- Create: `.tekton/integration-tests/mta-cli-e2e-pipeline.yaml`
- Create: `tests/test_pipeline_yaml_structure.sh`

**Interfaces:**
- Pipeline params match the design table (`SNAPSHOT`, AMIs, region, instance types, `TEST_COMMAND`, `FAILURE_TTL_HOURS`, SSH users, `KEY_NAME`, `SECURITY_GROUP_ID`, `SUBNET_ID`, repo URLs)
- Workspace `shared-workspace` for artifacts between prepare and OS tasks
- Secret volumes: `aws-cli-e2e-credentials`, `aws-vm-ssh-key` (names documented; overridable later)

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
grep -q 'name: prepare-artifacts' "$YML"
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

- [ ] **Step 3: Create pipeline skeleton with parse-metadata + prepare-artifacts**

Create `.tekton/integration-tests/mta-cli-e2e-pipeline.yaml` with:

- `apiVersion: tekton.dev/v1` / `kind: Pipeline` / `metadata.name: mta-cli-e2e-pipeline`
- All params from the design (AMI_* default to empty string with description “set by IntegrationTestScenario”)
- Extra params: `KEY_NAME`, `SECURITY_GROUP_ID` (default `""`), `SUBNET_ID` (default `""`), `MISC_DOWNSTREAM_URL`, `DEPLOY_REPO_URL` (default migtools repo), `DEPLOY_REPO_REVISION` (default `main`)
- Results: `TEST_OUTPUT`, `LINUX_STATUS`, `WINDOWS_STATUS`, `DARWIN_STATUS`
- Workspace: `shared-workspace`
- Task `parse-metadata`: identical git resolver usage as the FBC pipeline (`konflux-ci/integration-examples` … `tasks/test_metadata.yaml` at revision `a1a70b0a1cfc96f5216d472fbd60f6b42780b3e5`)
- Task `prepare-artifacts` (`runAfter: [parse-metadata]`):
  - Image: `quay.io/migqe/migqe-base:latest` (or `registry.access.redhat.com/ubi9/ubi` + install git/python/pip/podman as needed — prefer migqe-base if it already has podman/python)
  - Mount workspace at `/workspace`
  - Mount SSH key secret at `/secrets/aws-vm-login-key.pem` (mode 0400)
  - Script: set `FBC_IMAGE` from `$(tasks.parse-metadata.results.component-container-image)`, derive version via `extract_version_from_image.sh` (scripts come from cloning deploy repo **or** embed a bootstrap clone first). Bootstrap:

```bash
#!/bin/bash
set -euo pipefail
cd /workspace
git clone --depth 1 --branch "$(params.DEPLOY_REPO_REVISION)" "$(params.DEPLOY_REPO_URL)" cli-deploy-bootstrap
export WORK_DIR=/workspace
export FBC_IMAGE="$(params resolved from parse-metadata result via env)"
export MTA_VERSION="$(cli-deploy-bootstrap/.tekton/integration-tests/scripts/extract_version_from_image.sh "$FBC_IMAGE")"
export SSH_USER="$(params.SSH_USER)"
export SSH_KEY=/secrets/aws-vm-login-key.pem
export MISC_DOWNSTREAM_URL="$(params.MISC_DOWNSTREAM_URL)"
export DEPLOY_REPO_URL="$(params.DEPLOY_REPO_URL)"
export DEPLOY_REPO_REVISION="$(params.DEPLOY_REPO_REVISION)"
cli-deploy-bootstrap/.tekton/integration-tests/scripts/prepare_artifacts.sh
# copy status marker
echo -n OK > $(results.prepareStatus.path)
```

  - Results: `prepareStatus`, and ensure zip path files exist under `/workspace/artifacts/`

Leave OS tasks as stubs that `echo SKIP` and write `PASSED` temporarily **only if** needed for YAML validity — prefer adding real OS tasks in Task 5 in the same PR sequence; for this task’s structure test, include stub task names `linux-e2e`, `windows-e2e`, `darwin-e2e`, `aggregate-results` with minimal scripts so the structure test passes.

Stub OS task body for this commit only:

```bash
#!/bin/bash
echo -n "PASSED" > $(results.testStatus.path)
```

- [ ] **Step 4: Run structure test — expect PASS**

Run: `bash tests/test_pipeline_yaml_structure.sh`

- [ ] **Step 5: Commit**

```bash
git add .tekton/integration-tests/mta-cli-e2e-pipeline.yaml tests/test_pipeline_yaml_structure.sh
git commit -m "$(cat <<'EOF'
Add MTA CLI E2E Tekton pipeline skeleton.

Wire SNAPSHOT parse-metadata and artifact preparation; OS lanes
stubbed for the next commit.
EOF
)"
```

---

### Task 5: Wire real OS lanes + aggregate

**Files:**
- Modify: `.tekton/integration-tests/mta-cli-e2e-pipeline.yaml`

**Interfaces:**
- Each OS task consumes workspace + AWS secret (`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` or shared credentials file under `/tekton/home/.aws`) + SSH key
- Results per OS: `testStatus`
- `aggregate-results` `runAfter: [linux-e2e, windows-e2e, darwin-e2e]`, maps pipeline results, exits non-zero on failure

- [ ] **Step 1: Replace linux-e2e stub with full taskSpec**

Params into the task: `ami`, `instanceType`, `targetOs`, `sshUser`, `fbcImage`, `mtaVersion`, plus shared AWS/SSH/KEY/SG/subnet/TTL/testCommand/pipelineRunName.

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
export FBC_IMAGE="$(params.fbcImage)"
export MTA_VERSION="$(params.mtaVersion)"
export DEPENDENCY_ZIP="$(cat /workspace/artifacts/linux.zip.path)"
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

Differences only: `TARGET_OS` / zip path / AMI param / instance type / `SSH_USER` (`SSH_USER_WINDOWS` for windows).

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

Each lane provisions an AMI-backed VM, deploys CLI, runs tier0,
and terminates or TTL-tags the instance based on outcome.
EOF
)"
```

---

### Task 6: README operator notes

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
3. Required IntegrationTestScenario params: `AMI_LINUX`, `AMI_WINDOWS`, `AMI_MAC`, `KEY_NAME`, `MISC_DOWNSTREAM_URL`, and usually `SECURITY_GROUP_ID` / `SUBNET_ID`
4. Behavior: parallel OS lanes; pipeline fails if any tier0 fails; VMs terminated on pass; failed VMs tagged `ttl-delete-after` for 24h
5. Link to design spec: `docs/superpowers/specs/2026-08-10-mta-cli-e2e-tekton-design.md`

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
| SNAPSHOT trigger / parse-metadata | Task 4 |
| AWS VMs from AMIs | Tasks 2, 5 |
| misc-downstream + existing Python deploy | Tasks 1, 3, 5 |
| Parallel linux/windows/darwin | Task 5 |
| Tier0 pytest | Task 3 (`run_os_e2e.sh`), Task 5 |
| JUnit + exit code | Task 3 |
| Fail PipelineRun if any OS fails | Tasks 3, 5 |
| Terminate on pass / TTL tag on fail | Tasks 2, 3 |
| Params + secrets | Tasks 4–6 |
| Pipeline under `.tekton/integration-tests/` | Task 4 |
| AMI baking / janitor out of scope | Not implemented (docs only) |

## Placeholder / consistency check

- Script paths and env var names are consistent across Tasks 2–5 (`RESULT_DIR`, `INSTANCE_ID`, `OUTCOME`, `ttl-delete-after`).
- Deploy CLI flags use `--ip_address` (not `--ip`).
- Secret names in YAML and README must match: `aws-cli-e2e-credentials`, `aws-vm-ssh-key`.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-11-mta-cli-e2e-tekton.md`. Two execution options:

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
