#!/usr/bin/env bash
set -euo pipefail

SRC="/srv/containers/media/appdata"
DEST="/mnt/media/backups/appdata"
TS="$(date +%F_%H%M%S)"
ARCHIVE="${DEST}/appdata_${TS}.tar.gz"

mkdir -p "$DEST"

tar -czf "$ARCHIVE" -C "$SRC" .

# keep last 14 days
find "$DEST" -type f -name "appdata_*.tar.gz" -mtime +14 -delete
