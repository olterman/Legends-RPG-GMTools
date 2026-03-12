#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_ENV_FILE="${DEPLOY_ENV_FILE:-$ROOT_DIR/.env.deploy}"

if [[ -f "$DEPLOY_ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$DEPLOY_ENV_FILE"
fi

: "${DEPLOY_USER:?DEPLOY_USER is required (set in .env.deploy)}"
: "${DEPLOY_HOST:?DEPLOY_HOST is required (set in .env.deploy)}"
: "${DEPLOY_PATH:?DEPLOY_PATH is required (set in .env.deploy)}"
DEPLOY_PORT="${DEPLOY_PORT:-22}"

cd "$ROOT_DIR"

if ! git rev-parse --verify HEAD >/dev/null 2>&1; then
  exit 0
fi

CHANGED_FILES="$(git diff-tree --no-commit-id --name-only -r HEAD || true)"
VERSION_CHANGED=0
IMAGES_CHANGED=0

if grep -q "^VERSION$" <<<"$CHANGED_FILES"; then
  VERSION_CHANGED=1
fi
if grep -q "^images/" <<<"$CHANGED_FILES"; then
  IMAGES_CHANGED=1
fi

if [[ "$VERSION_CHANGED" -ne 1 || "$IMAGES_CHANGED" -ne 1 ]]; then
  exit 0
fi

SSH_TARGET="${DEPLOY_USER}@${DEPLOY_HOST}"

echo "Detected version bump + image changes. Uploading images to ${SSH_TARGET}:${DEPLOY_PATH}/images ..."
ssh -p "${DEPLOY_PORT}" "${SSH_TARGET}" "mkdir -p '${DEPLOY_PATH}/images'"
rsync -az --delete \
  -e "ssh -p ${DEPLOY_PORT}" \
  "${ROOT_DIR}/images/" "${SSH_TARGET}:${DEPLOY_PATH}/images/"

echo "Image upload complete."
