#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

git config core.hooksPath .githooks
echo "Git hooks configured: core.hooksPath=.githooks"
echo "Post-commit hook will upload images when both VERSION and images/ changed in a commit."
