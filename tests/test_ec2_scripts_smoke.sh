#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPTS="$ROOT/.tekton/integration-tests/scripts"
test -x "$SCRIPTS/provision_ec2.sh"
test -x "$SCRIPTS/wait_for_ssh.sh"
test -x "$SCRIPTS/cleanup_ec2.sh"
test -x "$SCRIPTS/extract_version_from_image.sh"
test -x "$SCRIPTS/prepare_workspace.sh"
test -x "$SCRIPTS/run_os_e2e.sh"
test -x "$SCRIPTS/art_pytest_excludes.sh"
test -x "$SCRIPTS/aggregate_results.sh"
test -x "$SCRIPTS/verify_results.sh"
test -x "$SCRIPTS/fetch_fbc_related_images.sh"
test -x "$SCRIPTS/extract_fbc_cli_zip.sh"
# Syntax check only (no AWS calls)
bash -n "$SCRIPTS/provision_ec2.sh"
bash -n "$SCRIPTS/fetch_fbc_related_images.sh"
bash -n "$SCRIPTS/extract_fbc_cli_zip.sh"
grep -q -- '--build fbc' "$SCRIPTS/run_os_e2e.sh"
grep -q 'fetch_fbc_related_images.sh' "$SCRIPTS/run_os_e2e.sh"
if grep -qE -- '--build stage' "$SCRIPTS/run_os_e2e.sh"; then
  echo "run_os_e2e.sh must use --build fbc (not stage) for pipeline" >&2
  exit 1
fi

# Guard against accidental line concatenation (set -u + adjacent echo expands unbound INSTANCE_ID).
if grep -qE 'INSTANCE_ID="\$\(aws[^"]*\)"echo' "$SCRIPTS/provision_ec2.sh"; then
  echo "provision_ec2.sh: INSTANCE_ID assignment must be on its own line" >&2
  exit 1
fi
grep -qE '^INSTANCE_ID="\$\(aws "\$\{ARGS\[@\]\}"\)"$' "$SCRIPTS/provision_ec2.sh"
bash -n "$SCRIPTS/wait_for_ssh.sh"
bash -n "$SCRIPTS/cleanup_ec2.sh"
bash -n "$SCRIPTS/extract_version_from_image.sh"
bash -n "$SCRIPTS/prepare_workspace.sh"
bash -n "$SCRIPTS/run_os_e2e.sh"
bash -n "$SCRIPTS/art_pytest_excludes.sh"
bash -n "$SCRIPTS/aggregate_results.sh"
bash -n "$SCRIPTS/verify_results.sh"
echo "OK"
