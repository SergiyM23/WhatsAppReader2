#!/usr/bin/env bash
# Sync WhatsAppReader application code from Development to Production.
# Usage: bash scripts/deploy.sh [--dry-run|--apply]
set -euo pipefail

MODE="${1:---dry-run}"
if [[ "$MODE" != "--dry-run" && "$MODE" != "--apply" ]]; then
    echo "Usage: bash scripts/deploy.sh [--dry-run|--apply]" >&2
    exit 2
fi

SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="/opt/whatsappreader"

for tool in rsync flock; do
    command -v "$tool" >/dev/null || { echo "Missing tool: $tool" >&2; exit 1; }
done
[[ -d "$TARGET/whatsappreader" && -x "$TARGET/.venv/bin/python" ]] || {
    echo "Production installation not found at $TARGET" >&2
    exit 1
}

# Lock against concurrent WhatsAppReader runs while deploying.
# Dry-run leaves the Production filesystem untouched.
if [[ "$MODE" == "--apply" ]]; then
    exec 9>>"$TARGET/data/orchestrator.lock"
    flock -n 9 || { echo "An orchestrator run is active; deploy after it finishes." >&2; exit 1; }
fi

REQUIREMENTS_CHANGED=0
if ! cmp -s "$SOURCE/requirements.txt" "$TARGET/requirements.txt"; then
    REQUIREMENTS_CHANGED=1
fi

RSYNC_OPTIONS=(--recursive --times --checksum --itemize-changes \
    --exclude='__pycache__/' --exclude='*.pyc' --exclude='*.pyo')
if [[ "$MODE" == "--dry-run" ]]; then
    RSYNC_OPTIONS+=(--dry-run)
    echo "DRY RUN — no files will be changed."
else
    echo "Deploying application code to $TARGET"
fi

# Deliberately whitelist application source and requirements only.
# Never synchronize app.yaml, .env, SQLite, browser profiles, data, or logs.
sudo rsync "${RSYNC_OPTIONS[@]}" "$SOURCE/whatsappreader/" "$TARGET/whatsappreader/"
sudo rsync "${RSYNC_OPTIONS[@]}" "$SOURCE/requirements.txt" "$TARGET/requirements.txt"

if [[ "$MODE" == "--dry-run" ]]; then
    echo "Review changes above, then run: bash scripts/deploy.sh --apply"
    exit 0
fi

if (( REQUIREMENTS_CHANGED )); then
    echo "Requirements changed; updating Production virtual environment..."
    sudo "$TARGET/.venv/bin/python" -m pip install -r "$TARGET/requirements.txt"
fi

# Web Console is long-lived and must reload new Python code.
# Each orchestrator execution starts a new process and loads the latest code.
sudo systemctl restart whatsappreader-web.service
sudo systemctl is-active --quiet whatsappreader-web.service

echo "Deployment completed. Production data and configuration were not modified."
