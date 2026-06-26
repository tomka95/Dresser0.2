#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

cd "$ROOT"
source "$ROOT/.venv/bin/activate"
exec uvicorn main:app --reload --host 0.0.0.0 --port 8000
