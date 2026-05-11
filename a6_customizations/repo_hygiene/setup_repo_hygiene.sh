#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ENV_NAME="${1:-qlib_predictor}"
FILTER_SCRIPT="${ROOT_DIR}/a6_customizations/repo_hygiene/repo_hygiene.py"

if ! git -C "${ROOT_DIR}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Skipping repo hygiene setup because ${ROOT_DIR} is not a git worktree."
  exit 0
fi

echo "Configuring local git notebook clean filter"
git -C "${ROOT_DIR}" config --local filter.qlib-notebook-clean.clean "python3 \"${FILTER_SCRIPT}\" clean-stdin"
git -C "${ROOT_DIR}" config --local filter.qlib-notebook-clean.smudge cat
git -C "${ROOT_DIR}" config --local filter.qlib-notebook-clean.required true

echo "Installing pre-commit hook"
conda run -n "${ENV_NAME}" pre-commit install --hook-type pre-commit --config "${ROOT_DIR}/.pre-commit-config.yaml"
