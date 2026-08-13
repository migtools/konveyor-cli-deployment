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
PUBLIC_IP=""

cleanup() {
  # Best-effort report collection (even when pytest failed). Do not change OUTCOME on scp failure.
  if [[ -n "${PUBLIC_IP}" && -n "${SSH_USER}" && -n "${SSH_KEY}" ]]; then
    mkdir -p "$RESULT_DIR/reports"
    scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i "$SSH_KEY" -r \
      "${SSH_USER}@${PUBLIC_IP}:kantra-cli-tests/junit.xml" \
      "${SSH_USER}@${PUBLIC_IP}:kantra-cli-tests/htmlcov" \
      "$RESULT_DIR/reports/" \
      || echo "warn: report scp failed" >&2
  fi
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

# Lane-private deploy tree — avoid parallel lanes clobbering shared config.json ssh_user.
CLI_DEPLOY_DIR="$RESULT_DIR/cli-deploy"
rm -rf "$CLI_DEPLOY_DIR"
mkdir -p "$CLI_DEPLOY_DIR"
cp -a "$WORK_DIR/konveyor-cli-deployment/." "$CLI_DEPLOY_DIR/"
export CLI_DEPLOY_DIR
python3 - <<'PY'
import json, os
path = os.path.join(os.environ["CLI_DEPLOY_DIR"], "config.json")
with open(path) as f:
    cfg = json.load(f)
cfg["ssh_user"] = os.environ["SSH_USER"]
with open(path, "w") as f:
    json.dump(cfg, f, indent=2)
    f.write("\n")
PY

cd "$CLI_DEPLOY_DIR"
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

OUTCOME="PASSED"
