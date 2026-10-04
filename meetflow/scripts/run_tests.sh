#!/usr/bin/env bash
# Локальный прогон всех тестов: bash scripts/run_tests.sh [маркер]
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONIOENCODING=utf-8
if [ "${1:-}" != "" ]; then
  python -m pytest tests -q -m "$1" -p no:cacheprovider -W ignore::DeprecationWarning
else
  python -m pytest tests -q -p no:cacheprovider -W ignore::DeprecationWarning
fi
