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
