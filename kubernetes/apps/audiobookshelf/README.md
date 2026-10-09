# Audiobookshelf

Hosts the audiobook library for BookPlayer at
`https://audiobookshelf.lab.skyhaven.ltd`. Requests and completed download imports
are handled by [Shelfmark](../shelfmark/README.md), using the existing Prowlarr and
qBittorrent services.

## Deployment and storage

Argo CD discovers `app-audiobookshelf.yaml` through the existing app-of-apps.
The deployment pins Audiobookshelf 2.37.1 by digest and runs as UID/GID 1000.
Ansible must create `/mnt/media/library/audiobooks` before the pod starts.
Run the normal platform deployment after merging so directory and secret
provisioning accompany the Argo CD sync.

| Container path | Storage | Purpose |
| --- | --- | --- |
| `/config` | `audiobookshelf-config` PVC | Database, users, listening progress |
| `/metadata` | `audiobookshelf-metadata` PVC | Covers, metadata, logs, application backups |
| `/audiobooks` | `/mnt/media/library/audiobooks` | Completed audiobook library |

The local-path PVCs are included in the existing nightly appdata archive.
Media files under `/mnt/media` are not included in that backup. The archive is
captured while applications run; use Audiobookshelf's application backup before
migration and confirm restore integrity rather than assuming a live SQLite copy
is transactionally consistent.

## First run

1. Open the HTTPS address on the LAN or through Tailscale and create the root
   account before sharing access.
2. Create an audiobook library whose folder is `/audiobooks`.
3. Enable periodic library scans. For multi-file imports, disable the file
   watcher and scan after Shelfmark reports completion; scanning mid-import can
   group files incorrectly.
4. Create a non-admin listening user with download permission.
5. In BookPlayer, add an Audiobookshelf connection using the HTTPS address and
   that user. Browse and download a book to the device for offline playback.

Existing books downloaded on an iPhone remain local until explicitly exported
and imported into this server. BookPlayer's server download support does not
establish bidirectional listening-progress sync.

## Verification

Complete the end-to-end check in [Shelfmark's setup guide](../shelfmark/README.md).
Confirm BookPlayer can download and play the result, including chapters where
present. Remote library access requires the existing LAN/Tailscale route and DNS.

Upstream: [installation](https://www.audiobookshelf.org/docs/documentation/install/docker/)
and [scanning](https://www.audiobookshelf.org/docs/faq/server/).
