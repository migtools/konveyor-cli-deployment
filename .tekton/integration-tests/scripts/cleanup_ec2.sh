#!/usr/bin/env bash
set -euo pipefail
: "${AWS_REGION:?}" "${INSTANCE_ID:?}" "${OUTCOME:?}"
FAILURE_TTL_HOURS="${FAILURE_TTL_HOURS:-24}"
if ! [[ "$FAILURE_TTL_HOURS" =~ ^[0-9]+$ ]]; then
  echo "warn: invalid FAILURE_TTL_HOURS='$FAILURE_TTL_HOURS'; using 24" >&2
  FAILURE_TTL_HOURS=24
fi
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
