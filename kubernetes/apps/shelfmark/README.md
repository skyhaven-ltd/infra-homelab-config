# Shelfmark

Audiobook search and requests at `https://shelfmark.lab.skyhaven.ltd`.
Shelfmark searches the existing Prowlarr indexers, sends releases to qBittorrent,
and imports completed downloads into Audiobookshelf's library. BookPlayer remains
the listening app; requests happen in Shelfmark.

## Managed configuration

The deployment pins Shelfmark v1.4.0 by digest, runs as UID/GID 1000, and uses
local authentication from startup. Its configuration and user database persist
in `shelfmark-config`, covered by the existing nightly appdata backup.

| Setting | Value |
| --- | --- |
| Prowlarr | `http://prowlarr.prowlarr.svc.cluster.local:9696` |
| qBittorrent | `http://qbittorrent.qbittorrent.svc.cluster.local:8080` |
| Torrent category | `audiobooks` |
| Download directory | `/data/downloads/complete/audiobooks` |
| Completed library | `/data/library/audiobooks` |
| Audiobook naming template | `{Author}/{Title}/{Title}` |

Both Shelfmark and qBittorrent mount `/mnt/media` at `/data`, so downloaded paths
resolve without remote path mappings. Audiobookshelf sees only the completed
library at `/audiobooks`. The import copies files and can extract archives; this
preserves torrent data for seeding but uses additional disk space while both
copies remain. Keep qBittorrent's existing share limits.

Ansible creates the media directories and projects the existing Prowlarr API key
into `shelfmark-secrets`. No new Key Vault value is required. Run the normal
platform deployment after merging; Argo CD sync alone does not create the
required directories or Secret.

## First run

Shelfmark v1.4.0 does not create an admin automatically when `AUTH_METHOD=builtin`.
Create one through the running container's user database API, keeping web
authentication enabled throughout. Run this from a terminal with cluster access;
the password is prompted without echo and is not passed in process arguments:

```sh
kubectl -n shelfmark exec -it deployment/shelfmark -- python -c '
from getpass import getpass
from shelfmark.core.user_db import UserDB
from werkzeug.security import generate_password_hash
users = UserDB("/config/users.db")
users.initialize()
if users.has_admin_with_password():
    raise SystemExit("An admin already exists; use the web login.")
username = input("Admin username: ").strip()
password = getpass("Admin password (at least 12 characters): ")
if not username or len(password) < 12 or password != getpass("Repeat password: "):
    raise SystemExit("Invalid username, short password, or passwords differ.")
users.create_user(username=username, password_hash=generate_password_hash(password), role="admin")
print("Admin created.")
'
```

1. Sign in at the HTTPS address and complete onboarding. Environment-managed
   settings are the source of truth; preserve the configured paths and local auth.
2. In download-client settings, enter the existing qBittorrent Web UI username
   and password, then test the connection. These credentials are saved in the
   persistent Shelfmark configuration; never put them in Git.
3. Test Prowlarr and select indexers supporting audiobook categories. qBittorrent
   search plugins are separate and do not populate Prowlarr automatically.
4. Confirm the `audiobooks` category in qBittorrent saves to
   `/data/downloads/complete/audiobooks`. Shelfmark supplies that category and path
   for its downloads. Do not repoint movie or TV categories.
5. Finish [Audiobookshelf setup](../audiobookshelf/README.md). Create additional
   Shelfmark users and configure request approvals if sharing the request site.

## End-to-end verification

Use a small audiobook you are authorized to download:

1. Search in Shelfmark's audiobook tab and select a Prowlarr release.
2. Confirm qBittorrent receives category `audiobooks` with the intended save path.
3. Wait for completion and Shelfmark import. Confirm the library contains a
   separate book folder with every chapter, and torrent data remains available
   for seeding. Existing manual qBittorrent downloads are not automatically
   adopted by Shelfmark; import those separately.
4. Scan Audiobookshelf after import. Confirm title, author, chapters, and duration.
5. Connect BookPlayer to Audiobookshelf, download the book, and play it offline.
6. Restart both deployments and confirm accounts, settings, and library remain.

Until first-run credentials, indexers, and the Audiobookshelf library are
configured, the deployments can be healthy without the request flow being ready.

Upstream: [Shelfmark](https://github.com/calibrain/shelfmark/tree/v1.4.0)
and [versioned settings](https://github.com/calibrain/shelfmark/blob/v1.4.0/docs/environment-variables.md).
