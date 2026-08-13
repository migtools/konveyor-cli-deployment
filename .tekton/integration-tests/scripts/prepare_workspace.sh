#!/usr/bin/env bash
set -euo pipefail
: "${WORK_DIR:?}" "${FBC_IMAGE:?}" "${SSH_USER:?}" "${SSH_KEY:?}"
DEPLOY_REPO_URL="${DEPLOY_REPO_URL:-https://github.com/migtools/konveyor-cli-deployment.git}"
DEPLOY_REPO_REVISION="${DEPLOY_REPO_REVISION:-main}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

mkdir -p "$WORK_DIR/artifacts" "$WORK_DIR/tmp"
cd "$WORK_DIR"
rm -rf konveyor-cli-deployment
git clone --depth 1 --branch "$DEPLOY_REPO_REVISION" "$DEPLOY_REPO_URL" konveyor-cli-deployment

MTA_VERSION="$("$SCRIPT_DIR/extract_version_from_image.sh" "$FBC_IMAGE")"
echo -n "$MTA_VERSION" > "$WORK_DIR/artifacts/mta-version"

# Stage/GA path does not need misc-downstream; keep placeholders so config.load still works.
cat > konveyor-cli-deployment/config.json <<EOF
{
  "misc_downstream_path": "${WORK_DIR}/tmp/misc-downstream/",
  "temp_dir": "${WORK_DIR}/tmp/",
  "extract_binary": "mta-cli-binary-extract.py",
  "extract_binary_konflux": "mta-cli-binary-extract-konflux.py",
  "get_images_output": "get-image-build-details.py ",
  "bundle": "--bundle mta-operator-bundle-container-",
  "no_brew": "--no-brew",
  "ssh_user": "${SSH_USER}",
  "ssh_key": "${SSH_KEY}"
}
EOF

cp konveyor-cli-deployment/config.json "$WORK_DIR/artifacts/config.json"
cd konveyor-cli-deployment
pip3 install -r requirements.txt
echo "prepare_workspace done (MTA_VERSION=$MTA_VERSION)"
