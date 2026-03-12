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

SSH_TARGET="${DEPLOY_USER}@${DEPLOY_HOST}"

echo "Syncing project to ${SSH_TARGET}:${DEPLOY_PATH} ..."
rsync -az --delete \
  --exclude ".git/" \
  --exclude ".venv/" \
  --exclude "__pycache__/" \
  --exclude ".pytest_cache/" \
  --exclude ".mypy_cache/" \
  --exclude ".DS_Store" \
  "${ROOT_DIR}/" "${SSH_TARGET}:${DEPLOY_PATH}/"

echo "Deploying containers on remote host ..."
ssh -p "${DEPLOY_PORT}" "${SSH_TARGET}" "cd '${DEPLOY_PATH}' && docker compose up -d --build"

echo "Deploy complete. App should be available on port ${APP_PORT:-5000}."
