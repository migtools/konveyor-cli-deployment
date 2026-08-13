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
