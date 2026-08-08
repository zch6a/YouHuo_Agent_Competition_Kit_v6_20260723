#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONPATH="$PWD/backend"
mkdir -p data
python -m uvicorn youhuo.api:app --host 127.0.0.1 --port 8000 --app-dir backend
