#!/usr/bin/env bash
set -euo pipefail
: "${PUBLIC_IP:?}" "${SSH_USER:?}" "${SSH_KEY:?}"
RETRIES="${SSH_RETRIES:-60}"
SLEEP_SECONDS="${SSH_RETRY_SLEEP:-10}"
KNOWN_HOSTS="${KNOWN_HOSTS:-}"

mkdir -p "$(dirname "${KNOWN_HOSTS:-/tmp/known_hosts}")"
if [[ -n "$KNOWN_HOSTS" ]]; then
  : > "$KNOWN_HOSTS"
fi

for i in $(seq 1 "$RETRIES"); do
  if [[ -n "$KNOWN_HOSTS" ]]; then
    # Pin host keys once sshd is up, then verify subsequent SSH with StrictHostKeyChecking=yes.
    tmp="$(mktemp)"
    if ssh-keyscan -T 5 -H "$PUBLIC_IP" >"$tmp" 2>/dev/null && [[ -s "$tmp" ]]; then
      cat "$tmp" > "$KNOWN_HOSTS"
      rm -f "$tmp"
      if ssh -o UserKnownHostsFile="$KNOWN_HOSTS" -o StrictHostKeyChecking=yes -o ConnectTimeout=5 \
          -i "$SSH_KEY" "${SSH_USER}@${PUBLIC_IP}" "echo ok" >/dev/null 2>&1; then
        echo "SSH ready on ${PUBLIC_IP} (host key pinned)"
        exit 0
      fi
    else
      rm -f "$tmp"
    fi
  else
    if ssh -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/tmp/mta-cli-e2e-known_hosts \
        -o ConnectTimeout=5 -i "$SSH_KEY" "${SSH_USER}@${PUBLIC_IP}" "echo ok" >/dev/null 2>&1; then
      echo "SSH ready on ${PUBLIC_IP}"
      exit 0
    fi
  fi
  echo "Waiting for SSH ($i/$RETRIES)..."
  sleep "$SLEEP_SECONDS"
done
echo "SSH not ready after retries" >&2
exit 1
