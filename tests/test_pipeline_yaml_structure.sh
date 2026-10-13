#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
YML="$ROOT/.tekton/integration-tests/mta-cli-e2e-pipeline.yaml"
TASKS="$ROOT/.tekton/tasks"

test -f "$YML"
grep -q 'name: mta-cli-e2e-pipeline' "$YML"
grep -q 'name: SNAPSHOT' "$YML"
grep -q 'name: parse-metadata' "$YML"
grep -q 'name: verify-image-pullable' "$YML"
grep -q 'name: prepare-workspace' "$YML"
grep -q 'name: linux-e2e' "$YML"
grep -q 'name: windows-e2e' "$YML"
grep -q 'name: darwin-e2e' "$YML"
grep -q 'name: aggregate-results' "$YML"
grep -q 'name: verify-results' "$YML"
grep -q 'AMI_LINUX' "$YML"
grep -q 'FAILURE_TTL_HOURS' "$YML"
grep -q 'IMAGE_VERIFICATION' "$YML"
grep -q 'resolver: git' "$YML"
grep -q '\.tekton/tasks/verify-image-pullable.yaml' "$YML"
grep -q '\.tekton/tasks/prepare-workspace.yaml' "$YML"
grep -q '\.tekton/tasks/run-os-e2e.yaml' "$YML"
grep -q '\.tekton/tasks/aggregate-results.yaml' "$YML"
grep -q '\.tekton/tasks/verify-results.yaml' "$YML"

for task in verify-image-pullable prepare-workspace run-os-e2e aggregate-results verify-results; do
  f="$TASKS/${task}.yaml"
  test -f "$f"
  grep -q 'kind: Task' "$f"
done

grep -q 'name: verificationStatus' "$TASKS/verify-image-pullable.yaml"
grep -q 'name: prepareStatus' "$TASKS/prepare-workspace.yaml"
grep -q 'name: testStatus' "$TASKS/run-os-e2e.yaml"
grep -q 'name: summary' "$TASKS/aggregate-results.yaml"
grep -q 'name: mtaVersion' "$TASKS/prepare-workspace.yaml"
grep -q 'sshRetries' "$TASKS/run-os-e2e.yaml"

# Konflux ITS does not bind Pipeline workspaces (FBC E2E has none).
if grep -qE '^[[:space:]]*workspaces:' "$YML"; then
  echo "pipeline must not declare workspaces" >&2
  exit 1
fi
if grep -qE '^[[:space:]]*workspaces:' "$TASKS/prepare-workspace.yaml" \
  || grep -qE '^[[:space:]]*workspaces:' "$TASKS/run-os-e2e.yaml" \
  || grep -qE '^[[:space:]]*workspaces:' "$TASKS/aggregate-results.yaml" \
  || grep -qE '^[[:space:]]*workspaces:' "$TASKS/verify-results.yaml"; then
  echo "tasks must not require Pipeline workspaces" >&2
  exit 1
fi
# prepare-workspace must not mount secrets (missing secret → Pending, empty logs).
if grep -qE 'secretName:[[:space:]]*aws-vm-ssh-key' "$TASKS/prepare-workspace.yaml"; then
  echo "prepare-workspace must not mount aws-vm-ssh-key" >&2
  exit 1
fi
# Timeout must live on PipelineTask, not Task.spec (Konflux rejects Task.spec.timeout).
if grep -qE '^[[:space:]]*timeout:' "$TASKS/prepare-workspace.yaml"; then
  echo "prepare-workspace Task must not set spec.timeout" >&2
  exit 1
fi
grep -qE '^[[:space:]]*timeout:[[:space:]]*"20m"' "$YML"
grep -qE '^[[:space:]]*timeout:[[:space:]]*"2h"' "$YML"
grep -q 'emptyDir' "$TASKS/run-os-e2e.yaml"
# Pinned ubi9/python-311 patch tags are often GC'd (ImagePullBackOff).
grep -q 'ubi9/python-311:latest' "$TASKS/run-os-e2e.yaml"
grep -q 'ubi9/python-311:latest' "$TASKS/aggregate-results.yaml"
grep -q 'ubi9/python-311:latest' "$TASKS/prepare-workspace.yaml"
if grep -rE 'ubi9/python-311:[0-9]' "$TASKS" --include='*.yaml'; then
  echo "tasks must not pin ubi9/python-311 patch tags" >&2
  exit 1
fi
# Non-root image has no microdnf; git/ssh already present.
if grep -qE 'microdnf[[:space:]]+install' "$TASKS/run-os-e2e.yaml"; then
  echo "run-os-e2e must not microdnf install (non-root, no microdnf)" >&2
  exit 1
fi
# OS lanes must set MTA_VERSION before prepare_workspace.sh (skip catalog extract).
grep -q 'Using provided MTA_VERSION' "$ROOT/.tekton/integration-tests/scripts/prepare_workspace.sh"
grep -q 'AMI_ID and KEY_NAME must be non-empty' "$ROOT/.tekton/integration-tests/scripts/provision_ec2.sh"

echo "OK"
