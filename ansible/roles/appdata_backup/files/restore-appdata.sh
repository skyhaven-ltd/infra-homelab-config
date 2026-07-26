#!/usr/bin/env bash
# Restore container appdata from a backup archive.
#
# The local-path provisioner names each directory pvc-<uid>_<namespace>_<claim>.
# PVC UIDs change when a cluster is rebuilt, so restore matches on the
# <namespace>_<claim> suffix rather than on the full directory name.
#
# Usage:
#   restore-appdata.sh --archive <file.tar.gz> --list
#   restore-appdata.sh --archive <file.tar.gz> --claim plex_plex-config [--apply]
#
# Without --apply the script only reports what it would do.
set -euo pipefail

ARCHIVE=""
CLAIM=""
APPLY="false"
LIST="false"
DEST_ROOT="${APPDATA_SRC:-/srv/appdata/local-path}"

usage() {
  sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --archive) ARCHIVE="${2:?--archive needs a path}"; shift 2 ;;
    --claim)   CLAIM="${2:?--claim needs a value}";     shift 2 ;;
    --apply)   APPLY="true";                            shift ;;
    --list)    LIST="true";                             shift ;;
    -h|--help) usage 0 ;;
    *) echo "unknown argument: $1" >&2; usage 1 ;;
  esac
done

[[ -n "${ARCHIVE}" ]] || { echo "ERROR: --archive is required" >&2; usage 1; }
[[ -r "${ARCHIVE}" ]] || { echo "ERROR: cannot read ${ARCHIVE}" >&2; exit 1; }

if ! gzip -t "${ARCHIVE}"; then
  echo "ERROR: ${ARCHIVE} failed its integrity check" >&2
  exit 1
fi

if [[ "${LIST}" == "true" ]]; then
  echo "claims present in ${ARCHIVE}:"
  tar -tzf "${ARCHIVE}" |
    sed -n 's|^\./\(pvc-[0-9a-f-]*_\)\{0,1\}\([^/]*\)/.*|\2|p' |
    sort -u
  exit 0
fi

[[ -n "${CLAIM}" ]] || { echo "ERROR: --claim is required (or use --list)" >&2; usage 1; }

# Locate the archive member and the live destination for this claim.
src_dir="$(tar -tzf "${ARCHIVE}" | grep -oE "^\./[^/]*${CLAIM}[^/]*/" | head -1 || true)"
[[ -n "${src_dir}" ]] || { echo "ERROR: claim ${CLAIM} not found in archive" >&2; exit 1; }

dest_dir="$(find "${DEST_ROOT}" -maxdepth 1 -type d -name "*_${CLAIM}" | head -1 || true)"
[[ -n "${dest_dir}" ]] || { echo "ERROR: no live directory matching *_${CLAIM} under ${DEST_ROOT}" >&2; exit 1; }

echo "archive member : ${src_dir}"
echo "destination    : ${dest_dir}"

if [[ "${APPLY}" != "true" ]]; then
  echo
  echo "DRY RUN - nothing written. Re-run with --apply to restore."
  echo "Scale the owning workload to zero first, or the running container will"
  echo "overwrite the restored files on shutdown."
  exit 0
fi

backup_of_current="${dest_dir}.pre-restore-$(date +%F_%H%M%S)"
echo "preserving current contents at ${backup_of_current}"
cp -a "${dest_dir}" "${backup_of_current}"

tmp="$(mktemp -d)"
trap 'rm -rf "${tmp}"' EXIT
tar -xzf "${ARCHIVE}" -C "${tmp}" "${src_dir%/}"

rm -rf "${dest_dir:?}"/*
cp -a "${tmp}/${src_dir%/}/." "${dest_dir}/"

echo "restored ${CLAIM}. Previous contents kept at ${backup_of_current}"
echo "Scale the workload back up, then verify before deleting that copy."
