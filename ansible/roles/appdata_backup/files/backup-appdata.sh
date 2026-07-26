#!/usr/bin/env bash
# Archive every container's persistent data into a timestamped tarball.
#
# Staging deliberately lives on the node's root disk, never on the media disk:
# a backup stored beside the data it protects is not a backup.
set -euo pipefail

SRC="${APPDATA_SRC:-/srv/appdata/local-path}"
SRC_MOUNT="${APPDATA_MOUNT:-/srv/appdata}"
STAGE="${BACKUP_STAGE:-/var/backups/appdata}"
KEEP="${BACKUP_LOCAL_KEEP:-3}"

export KUBECONFIG="${KUBECONFIG:-/etc/rancher/k3s/k3s.yaml}"

timestamp="$(date +%F_%H%M%S)"
archive="${STAGE}/appdata_${timestamp}.tar.gz"
manifest="${STAGE}/manifest_${timestamp}.json"

# Fail closed. An unmounted source would otherwise produce a valid-looking
# empty archive that silently replaces good backups.
if ! mountpoint -q "${SRC_MOUNT}"; then
  echo "ERROR: ${SRC_MOUNT} is not mounted; refusing to back up" >&2
  exit 1
fi
if [[ ! -d "${SRC}" ]]; then
  echo "ERROR: source directory ${SRC} does not exist" >&2
  exit 1
fi
if [[ -z "$(ls -A "${SRC}" 2>/dev/null)" ]]; then
  echo "ERROR: source directory ${SRC} is empty; refusing to back up" >&2
  exit 1
fi

mkdir -p "${STAGE}"
chmod 0700 "${STAGE}"

# The local-path provisioner encodes namespace and claim name in each directory
# name, but the manifest records claim sizes and volume bindings too, which is
# what makes a rebuilt cluster restorable.
if command -v kubectl >/dev/null 2>&1; then
  kubectl get pvc,pv -A -o json >"${manifest}" 2>/dev/null ||
    echo '{"error":"kubectl unavailable at backup time"}' >"${manifest}"
else
  echo '{"error":"kubectl not installed"}' >"${manifest}"
fi

# tar exits 1 when a file changed while being read. Containers are live, so that
# is expected and tolerable; anything above 1 is a real failure.
set +e
tar --warning=no-file-changed \
  -czf "${archive}" \
  -C "${SRC}" .
tar_rc=$?
set -e
if ((tar_rc > 1)); then
  echo "ERROR: tar failed with exit code ${tar_rc}" >&2
  rm -f "${archive}"
  exit "${tar_rc}"
fi

# Never let a truncated archive reach the remote.
if ! gzip -t "${archive}"; then
  echo "ERROR: archive ${archive} failed integrity check" >&2
  rm -f "${archive}"
  exit 1
fi

chmod 0600 "${archive}" "${manifest}"
echo "created ${archive} ($(du -h "${archive}" | cut -f1))"

# Local copies are only a staging buffer; OneDrive holds the real retention.
find "${STAGE}" -maxdepth 1 -type f -name 'appdata_*.tar.gz' -printf '%T@ %p\n' |
  sort -rn | tail -n "+$((KEEP + 1))" | cut -d' ' -f2- |
  while IFS= read -r stale; do
    echo "pruning local ${stale}"
    rm -f "${stale}" "${stale/appdata_/manifest_}"
  done

exit 0
