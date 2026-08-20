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
mkdir -p "$RESULT_DIR"
echo -n "$INSTANCE_ID" > "$RESULT_DIR/instance-id"
aws ec2 wait instance-running --region "$AWS_REGION" --instance-ids "$INSTANCE_ID"

PUBLIC_IP="$(aws ec2 describe-instances --region "$AWS_REGION" --instance-ids "$INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)"
if [[ -z "$PUBLIC_IP" || "$PUBLIC_IP" == "None" ]]; then
  echo "Instance $INSTANCE_ID has no public IP address" >&2
  exit 1
fi
echo -n "$PUBLIC_IP" > "$RESULT_DIR/public-ip"
echo "INSTANCE_ID=$INSTANCE_ID"
echo "PUBLIC_IP=$PUBLIC_IP"
