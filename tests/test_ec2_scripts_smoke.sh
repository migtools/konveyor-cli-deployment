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
