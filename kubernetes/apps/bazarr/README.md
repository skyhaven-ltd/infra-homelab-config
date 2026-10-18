# Bazarr

Automatic English subtitles for Sonarr and Radarr media at
`https://bazarr.lab.skyhaven.ltd`.

## Deployment

The LinuxServer image pins Bazarr v1.6.2-ls367 by digest. `/config` persists in
`bazarr-config` and is included in nightly appdata backups. `/mnt/media` mounts
at `/data`, matching Sonarr and Radarr, with UID/GID 1000 for subtitle writes.
Subtitle files live beside media on the media disk and are not backed up.

Ansible projects the existing Sonarr and Radarr API keys from Key Vault into
`bazarr-secrets`. No new provider account or Key Vault secret is required.
The normal platform deployment must run after merge; Argo CD alone does not
create this Secret. The root application tracks `main`, so branch changes do
not deploy automatically.

The ingress allows only `192.168.1.0/24`, including the existing subnet router's
SNAT traffic. It does not change Plex, DNS, or VPN addressing. Enable Bazarr's
native authentication during first-run setup as well; the network allowlist
is the initial access restriction.

## Managed settings

The PostSync job connects to `sonarr.sonarr.svc.cluster.local:8989` and
`radarr.radarr.svc.cluster.local:7878`. It creates or updates the `English`
language profile for full English subtitles, including English-audio titles.
Forced-only and hearing-impaired-only subtitles are not requested. Existing
embedded English subtitles can satisfy Bazarr's default subtitle detection.

The job sets this profile as the default before enabling the integrations,
so newly synchronized titles inherit it. It also assigns English to existing
titles without a profile. Other profiles and explicit title assignments remain
unchanged. Both monitored and unmonitored library files are eligible.

TVSubtitles and YIFY Subtitles are enabled when no providers are configured.
Both are account-free providers bundled with the pinned release. Existing
provider selections and credentials remain unchanged on subsequent syncs.
Provider availability, throttling, and subtitle coverage can limit downloads;
the application being healthy does not prove every title has subtitles.

Language suffixes remain enabled, and subtitles are written alongside media.
Matching paths mean no Sonarr/Radarr path mapping is needed. Scheduled missing
subtitle searches handle the backlog without forcing a full-library search at
every deployment. Change managed defaults in `files/reconcile-settings.py`.

## First run and verification

1. Open the HTTPS address from the LAN or existing VPN subnet route. Enable form
   authentication in Settings > General with a unique username and password.
2. Confirm Sonarr and Radarr connection tests pass and both libraries populate.
3. Confirm the English profile, defaults, and provider selections. For titles
   with a deliberately assigned different profile, use Mass Edit to opt them
   into English if desired.
4. Search for missing subtitles on one movie and one episode. Check the history
   for successful downloads, then play both in Plex and verify language/timing.
   Plex client subtitle preferences control whether subtitles display by default.
5. Confirm the scheduled missing-subtitle searches are enabled. Restart Bazarr
   and verify settings and subtitles remain available.

```sh
kubectl -n bazarr rollout status deployment/bazarr --timeout=300s
kubectl -n bazarr logs job/bazarr-reconcile-settings
kubectl -n bazarr logs deployment/bazarr --tail=100
```

The PostSync job retries failures for up to 15 minutes. If it fails, check the
Secret, Sonarr/Radarr connectivity, and its logs, then resync the application.
It uses Bazarr's generated API key from the mounted configuration without
printing credentials. Do not publish configuration files or Secret contents.

Upstream: [Bazarr setup](https://wiki.bazarr.media/Getting-Started/Setup-Guide/)
and [LinuxServer image](https://docs.linuxserver.io/images/docker-bazarr/).
