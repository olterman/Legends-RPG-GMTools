#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODULE_ID="legends-gmtools-bridge"
SOURCE_DIR="${PROJECT_ROOT}/Plugins/foundryVTT/module"
TARGET_ROOT="/home/olterman/.local/share/FoundryVTT/Data/modules"
TARGET_DIR="${TARGET_ROOT}/${MODULE_ID}"

if [[ ! -d "${SOURCE_DIR}" ]]; then
  echo "Source module folder not found: ${SOURCE_DIR}" >&2
  exit 1
fi

mkdir -p "${TARGET_ROOT}"
rm -rf "${TARGET_DIR}"
mkdir -p "${TARGET_DIR}"

cp -R "${SOURCE_DIR}/." "${TARGET_DIR}/"

echo "Installed Foundry module:"
echo "  Source: ${SOURCE_DIR}"
echo "  Target: ${TARGET_DIR}"
