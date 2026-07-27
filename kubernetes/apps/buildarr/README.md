# buildarr

Declarative source of truth for **Prowlarr**: indexers, app sync connections
(Sonarr/Radarr), sync profiles, and the FlareSolverr proxy. Runs as a daemon that
reconciles Prowlarr against `buildarr.yml.tmpl` on start and daily at 04:30.

It also owns **Sonarr and Radarr quality definition sizes** (the
megabytes-per-minute caps), their root folders, and their minimum free space.
Everything else about Sonarr and Radarr quality — profiles and custom formats —
is owned by [`recyclarr`](../recyclarr/README.md); the two do not overlap.

Buildarr is used for the sizes because Recyclarr can only apply a whole TRaSH
quality-definition template, and both the series and movie templates leave
maxSize unset on every quality above SD. Buildarr merges each definition over the
current remote object, so Sonarr's `preferredSize` is preserved, and it leaves
any attribute not named in `buildarr.yml.tmpl` alone (`check_unmanaged` defaults
to false). The Radarr plugin can set `preferred` as well, so Radarr's preferred
sizes sit below the max rather than at it.

Sizes are megabytes per minute of runtime; the UI shows GiB/hour (multiply by 60,
divide by 1024).

## How it runs

The base `callum027/buildarr` image bundles only the Sonarr/Radarr plugins, and no
Prowlarr-plugin image is published, so an init container installs the pinned
`buildarr-prowlarr==0.5.3` into a shared volume. Buildarr has no native env
interpolation, so `entrypoint.sh` renders `${VAR}` placeholders from
`buildarr-secrets` into `/config/buildarr.yml` before starting the daemon.

A second init container, `wait-for-dependencies`, blocks startup until Radarr and
Sonarr have the quality profiles this config references and Prowlarr has
authentication enabled. Buildarr aborts its entire apply if either is untrue, and
on a rebuild both are untrue until Recyclarr and the `argocd_bootstrap` Ansible
role have run.

The config files are loaded through kustomize's `configMapGenerator`, so the
ConfigMap name carries a content hash and editing a config file rolls the
Deployment. A plain ConfigMap syncs without restarting the pod, which previously
left the old config running until someone noticed.

## Secrets

`buildarr-secrets` (native Secret): `PROWLARR_API_KEY`, `SONARR_API_KEY`,
`RADARR_API_KEY`. Projected from Azure Key Vault (`homelab-<service>-api-key`)
by the `argocd_bootstrap` Ansible role on every platform deploy; rotate the
Key Vault secret and re-run the Reconcile Platform workflow.

## Validate before trusting a config change

Indexer `type` strings must match Prowlarr's definition IDs, and category names
must match Prowlarr's list — a mismatch makes Buildarr reject the whole config (it
fails safe: no partial apply). Validate config edits before merging:

```sh
kubectl -n buildarr exec deploy/buildarr -- \
  sh -c 'buildarr test-config /config/buildarr.yml'
```

## Notes

- `delete_unmanaged: false` everywhere: Buildarr reconciles the named definitions
  but leaves hand-added indexers/apps alone. Flip to `true` on the `indexers` block
  to make `buildarr.yml.tmpl` the sole source of truth.
- The FlareSolverr proxy uses the `flaresolverr` tag. Assign the same tag to each
  hand-added indexer that should use it. Prowlarr invokes FlareSolverr only when it
  detects a supported challenge on an indexer with a matching tag.
- Managed public indexers: The Pirate Bay, LimeTorrents, Nyaa.si — each verified
  to pass Prowlarr's create-test. Cloudflare/DDoS-Guard sites (1337x, TorrentGalaxy,
  YTS) and legally-blocked ones (EZTV → HTTP 451) fail that test and abort the whole
  apply, so add those by hand in the Prowlarr UI. Public indexer *definitions* are
  maintained by Prowlarr and refreshed on Prowlarr updates — keep the image current.
- Productionization follow-up: bake a custom image with the plugin preinstalled to
  drop the runtime `pip install` (needs PyPI reachability on pod start).
