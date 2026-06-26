#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="$HOME/.local/node-v22.14.0-darwin-arm64/bin:$HOME/.local/bin:$PATH"

cd "$ROOT"
exec npm run dev
