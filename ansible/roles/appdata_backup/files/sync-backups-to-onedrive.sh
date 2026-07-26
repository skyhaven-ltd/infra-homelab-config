#!/usr/bin/env bash
# Upload staged appdata archives to OneDrive.
#
# This uses `rclone copy`, never `rclone sync`. Sync mirrors deletions, so an
# empty or unmounted staging directory would erase every remote backup - which
# is precisely the failure this whole mechanism exists to survive.
set -euo pipefail

STAGE="${BACKUP_STAGE:-/var/backups/appdata}"
REMOTE="${BACKUP_REMOTE:?BACKUP_REMOTE must be set}"
RETAIN_DAYS="${BACKUP_REMOTE_RETAIN_DAYS:-30}"
MAX_DELETE="${BACKUP_REMOTE_MAX_DELETE:-5}"

export RCLONE_CONFIG="${RCLONE_CONFIG:-/root/.config/rclone/rclone.conf}"

if ! command -v rclone >/dev/null 2>&1; then
  echo "ERROR: rclone is not installed" >&2
  exit 1
fi
if [[ ! -r "${RCLONE_CONFIG}" ]]; then
  echo "ERROR: rclone config ${RCLONE_CONFIG} is missing or unreadable" >&2
  exit 1
fi
if [[ ! -d "${STAGE}" ]] || [[ -z "$(ls -A "${STAGE}" 2>/dev/null)" ]]; then
  echo "ERROR: staging directory ${STAGE} is missing or empty; nothing to upload" >&2
  exit 1
fi

echo "uploading ${STAGE} -> ${REMOTE}"
rclone copy "${STAGE}" "${REMOTE}" \
  --transfers 4 \
  --checkers 8 \
  --retries 3 \
  --log-level INFO

# Retention on the remote is an explicit, age-bounded delete with a hard cap on
# how many objects a single run may remove.
#
# --max-depth 1 keeps this confined to the top level. Archives worth keeping
# regardless of age live in a sibling folder, and pruning must never reach them:
# rclone delete recurses by default.
#
# Pruning is housekeeping, not the point of this job. The archive is already
# uploaded by now, so a prune failure - including deliberately tripping the
# --max-delete guard - is reported and tolerated rather than failing the unit
# and masking a successful backup.
echo "pruning remote objects older than ${RETAIN_DAYS} days (max ${MAX_DELETE})"
if rclone delete "${REMOTE}" \
  --min-age "${RETAIN_DAYS}d" \
  --include 'appdata_*.tar.gz' \
  --include 'manifest_*.json' \
  --max-depth 1 \
  --max-delete "${MAX_DELETE}" \
  --log-level INFO; then
  echo "prune completed"
else
  echo "WARNING: prune exited $? - backup upload already succeeded." >&2
  echo "WARNING: if the --max-delete cap was hit, check what is accumulating." >&2
fi

echo "remote now holds:"
rclone lsf "${REMOTE}" --include 'appdata_*.tar.gz' --max-depth 1 | sort | tail -5

exit 0
