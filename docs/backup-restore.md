# Container appdata backup and restore

Every container's persistent data lives in `local-path` PersistentVolumes under
`/srv/appdata/local-path` on `lnsvrk8s01`. A nightly systemd timer archives that
directory and uploads it to OneDrive.

## What is and is not protected

| Data | Location | Protected by |
| --- | --- | --- |
| Container configuration and databases | `/srv/appdata/local-path` | nightly archive to OneDrive |
| Media library | `/mnt/media` on the passed-through 1 TB disk | not backed up - re-downloadable by design |

The media disk holds media only. Backups are deliberately staged on the node's
root disk and shipped off-box: a backup stored beside the data it protects is
not a backup.

## Schedule

`appdata-backup.timer` fires at 03:15 daily with `Persistent=true`, so a missed
night runs at next boot rather than being skipped.

```
appdata-backup.service
  ExecStart      backup-appdata.sh                # archive + integrity check
  ExecStartPost  sync-backups-to-onedrive.sh      # upload (only if archive succeeded)
```

Retention is 3 archives locally and 30 days on OneDrive.

Archives worth keeping regardless of age live in the sibling folder
`07 - Digital/Container Backups Archive`, which pruning never touches. That is
where the pre-migration (docker-compose era) archives are kept. Anything moved
there is permanent until removed by hand.

## Safety properties

These are deliberate, and regressions here defeat the whole mechanism:

- **`rclone copy`, never `rclone sync`.** Sync mirrors deletions, so an empty or
  unmounted staging directory would erase every remote backup.
- **Remote pruning is age-bounded, capped and depth-limited** via `--min-age`,
  `--max-delete` and `--max-depth 1`. `rclone delete` recurses by default, so
  without the depth limit a prune would reach into `Container Backups Archive`
  and delete the very archives kept there for being old.
- **A prune failure never fails the unit.** By the time pruning runs the archive
  is already uploaded; failing there would mask a successful backup and leave
  the service red every night while a legitimate backlog drains.
- **`RequiresMountsFor=/srv/appdata`** plus an explicit mountpoint and
  non-empty check in the script, so an unmounted source fails loudly instead of
  producing a valid-looking empty archive.
- **`gzip -t` before upload**, so a truncated archive never reaches OneDrive.

## One-time setup: authorise rclone against OneDrive

The OAuth token cannot be minted non-interactively. Run this once on a machine
with a browser, then store the result in Key Vault.

```bash
rclone authorize "onedrive"
```

Copy the JSON token it prints, then find the drive ID:

```bash
rclone config          # create a temporary remote, or reuse the token
rclone about onedrive: # confirms the drive resolves
```

Store both values in `kv-platform-prd-uks-02`:

| Secret | Contents |
| --- | --- |
| `homelab-rclone-onedrive-token` | the JSON token from `rclone authorize` |
| `homelab-rclone-onedrive-drive-id` | the OneDrive drive ID |

`Reconcile Platform` injects them as `RCLONE_ONEDRIVE_TOKEN` and
`RCLONE_ONEDRIVE_DRIVE_ID`, and the `appdata_backup` role templates
`/root/.config/rclone/rclone.conf` (mode `0600`) from them. Until both secrets
exist the timer is installed but uploads fail loudly.

## Verifying

```bash
systemctl list-timers appdata-backup.timer
systemctl start appdata-backup.service     # run now
journalctl -u appdata-backup.service -n 50
ls -lh /var/backups/appdata
```

## Credentials not covered by this mechanism

The Grafana admin password lives in **Bitwarden**, not Key Vault, and the
`grafana-admin` Secret it populates is not reconciled by Ansible. The
kube-prometheus-stack Grafana subchart renders a new random admin password on
every Helm render, so `grafana.admin.existingSecret` in
`kubernetes/infrastructure/monitoring/values.yaml` points at a secret we own
instead. Recreate it by hand after a cluster rebuild - Grafana will not start
while the secret is missing:

```bash
kubectl -n monitoring create secret generic grafana-admin \
  --from-literal=admin-user=admin \
  --from-literal=admin-password='<from Bitwarden>'
```

Cluster Secrets in general are not backed up: k3s keeps them in its SQLite
datastore at `/var/lib/rancher/k3s/server/db/state.db`, which this job does not
archive.

## Restoring

List the claims inside an archive:

```bash
restore-appdata.sh --archive /var/backups/appdata/appdata_<ts>.tar.gz --list
```

Restore one claim. Scale the owning workload to zero first, or the running
container will overwrite the restored files when it shuts down:

```bash
kubectl -n sonarr scale deploy/sonarr --replicas=0
restore-appdata.sh --archive <file> --claim sonarr_sonarr-config          # dry run
restore-appdata.sh --archive <file> --claim sonarr_sonarr-config --apply
kubectl -n sonarr scale deploy/sonarr --replicas=1
```

The script copies the current directory to `<dir>.pre-restore-<timestamp>`
before writing. Verify the app, then delete that copy.

Claim directories are named `pvc-<uid>_<namespace>_<claim>`. UIDs change when a
cluster is rebuilt, so restore matches on the `<namespace>_<claim>` suffix. Each
archive also carries a `manifest_<ts>.json` dump of `kubectl get pvc,pv -A`
recording claim sizes and bindings.

## Restoring pre-2026-07-26 archives

These live in `onedrive:07 - Digital/Container Backups Archive` and are exempt
from pruning. Fetch one with:

```bash
rclone copy "onedrive:07 - Digital/Container Backups Archive/appdata_2026-07-05_031508.tar.gz" /var/backups/appdata/
```

They were produced by the docker-compose stack and have a flatter layout -
`./sonarr/...` rather than `./pvc-<uid>_sonarr_sonarr-config/...`. The contents
map directly onto the current claims:

| Archive path | Current claim |
| --- | --- |
| `./plex/Library/...` | `plex_plex-config` |
| `./sonarr` | `sonarr_sonarr-config` |
| `./radarr` | `radarr_radarr-config` |
| `./prowlarr` | `prowlarr_prowlarr-config` |
| `./qbittorrent` | `qbittorrent_qbittorrent-config` |
| `./pihole` | `pihole_pihole-etc` |

`./homeassistant`, `./syncthing` and `./audiobookshelf` have no equivalent in
the current cluster.

Extract the wanted subtree and copy it into the live claim directory with the
workload scaled to zero. Note that Buildarr owns Prowlarr configuration and
Recyclarr owns quality profiles, so restoring those two may be reverted at the
next reconcile.
