#!/usr/bin/env bash
set -euo pipefail

LOCAL="/mnt/media/backups/appdata"
REMOTE="onedrive:07 - Digital/Container Backups"

rclone sync "$LOCAL" "$REMOTE" --progress --transfers 4 --checkers 8
