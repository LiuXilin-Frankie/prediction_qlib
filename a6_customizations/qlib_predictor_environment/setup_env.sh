#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ENV_NAME="qlib_predictor"
ENV_FILE="${ROOT_DIR}/a6_customizations/environment.yml"
SMOKE_TEST="${ROOT_DIR}/a6_customizations/qlib_predictor_environment/smoke_test_environment.py"

cd "${ROOT_DIR}"

if conda env list | awk '{print $1}' | grep -qx "${ENV_NAME}"; then
  echo "Updating conda env: ${ENV_NAME}"
  conda env update -n "${ENV_NAME}" -f "${ENV_FILE}" --prune
else
  echo "Creating conda env: ${ENV_NAME}"
  conda env create -f "${ENV_FILE}"
fi

echo "Installing local Qlib source tree in editable mode"
conda run -n "${ENV_NAME}" python -m pip install --no-build-isolation -e "${ROOT_DIR}"

echo "Running smoke test"
conda run -n "${ENV_NAME}" python "${SMOKE_TEST}"
