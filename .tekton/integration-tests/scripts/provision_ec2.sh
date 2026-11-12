#!/usr/bin/env bash
set -euo pipefail
: "${AWS_REGION:?}" "${AMI_ID:?}" "${INSTANCE_TYPE:?}" "${KEY_NAME:?}"
: "${RESULT_DIR:?}"
SECURITY_GROUP_ID="${SECURITY_GROUP_ID:-}"
SUBNET_ID="${SUBNET_ID:-}"
# Root EBS size in GiB (instance type does not control disk). Never shrink below AMI snapshot.
ROOT_VOLUME_GB="${ROOT_VOLUME_GB:-100}"

if [[ -z "$AMI_ID" || -z "$KEY_NAME" ]]; then
  echo "ERROR: AMI_ID and KEY_NAME must be non-empty (set AMI_* and KEY_NAME on the IntegrationTestScenario)" >&2
  echo "AMI_ID='${AMI_ID}' KEY_NAME='${KEY_NAME}' AWS_REGION='${AWS_REGION}'" >&2
  exit 1
fi

ROOT_DEVICE="$(aws ec2 describe-images --region "$AWS_REGION" --image-ids "$AMI_ID" \
  --query 'Images[0].RootDeviceName' --output text)"
AMI_ROOT_GB="$(aws ec2 describe-images --region "$AWS_REGION" --image-ids "$AMI_ID" \
  --query "Images[0].BlockDeviceMappings[?DeviceName=='${ROOT_DEVICE}'].Ebs.VolumeSize | [0]" \
  --output text)"
if [[ -z "$ROOT_DEVICE" || "$ROOT_DEVICE" == "None" ]]; then
  echo "ERROR: could not resolve root device for AMI ${AMI_ID}" >&2
  exit 1
fi
if [[ -z "$AMI_ROOT_GB" || "$AMI_ROOT_GB" == "None" ]]; then
  AMI_ROOT_GB=0
fi
if (( ROOT_VOLUME_GB < AMI_ROOT_GB )); then
  EFFECTIVE_ROOT_GB="$AMI_ROOT_GB"
else
  EFFECTIVE_ROOT_GB="$ROOT_VOLUME_GB"
fi

ARGS=(
  ec2 run-instances
  --region "$AWS_REGION"
  --image-id "$AMI_ID"
  --instance-type "$INSTANCE_TYPE"
  --key-name "$KEY_NAME"
  --count 1
  --block-device-mappings "DeviceName=${ROOT_DEVICE},Ebs={VolumeSize=${EFFECTIVE_ROOT_GB},VolumeType=gp3,DeleteOnTermination=true}"
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=mta-cli-e2e},{Key=mta-cli-e2e,Value=true},{Key=mta-cli-e2e-pipeline-run,Value=${PIPELINE_RUN_NAME:-unknown}}]"
  --query 'Instances[0].InstanceId'
  --output text
)
[[ -n "$SECURITY_GROUP_ID" ]] && ARGS+=(--security-group-ids "$SECURITY_GROUP_ID")
[[ -n "$SUBNET_ID" ]] && ARGS+=(--subnet-id "$SUBNET_ID")
# Windows Podman (Hyper-V/WSL2) needs nested virtualization; c4/t3 cannot provide it.
NESTED_FLAG="false"
if [[ "${NESTED_VIRTUALIZATION:-}" == "true" || "${TARGET_OS:-}" == "windows" ]]; then
  NESTED_FLAG="true"
  ARGS+=(--cpu-options "NestedVirtualization=enabled")
  echo "Enabling NestedVirtualization for instance type ${INSTANCE_TYPE}"
fi

echo "Provisioning EC2: region=${AWS_REGION} ami=${AMI_ID} type=${INSTANCE_TYPE} key=${KEY_NAME} sg=${SECURITY_GROUP_ID:-default} subnet=${SUBNET_ID:-default} nested=${NESTED_FLAG} root=${ROOT_DEVICE}:${EFFECTIVE_ROOT_GB}GiB"
INSTANCE_ID="$(aws "${ARGS[@]}")"
echo "aws ec2 run-instances returned INSTANCE_ID=${INSTANCE_ID}"
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
