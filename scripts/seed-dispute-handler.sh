#!/usr/bin/env bash
# Thin wrapper preserving the seed-dispute-handler.sh name referenced in
# TestPlan_V1.md §4f and earlier docs. Real logic lives in the idempotent
# Python script, which is the thing you should edit.
set -eu
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$SCRIPT_DIR/seed-dispute-handler.py" "$@"
