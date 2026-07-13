# buildarr

Declarative source of truth for **Prowlarr**: indexers, app sync connections
(Sonarr/Radarr), sync profiles, and the FlareSolverr proxy. Runs as a daemon that
reconciles Prowlarr against `configmap.yaml` on start and daily at 04:30.

Scope is deliberately Prowlarr-only. Sonarr/Radarr quality is owned by
[`recyclarr`](../recyclarr/README.md); the two do not overlap.

## How it runs

The base `callum027/buildarr` image bundles only the Sonarr/Radarr plugins, and no
Prowlarr-plugin image is published, so an init container installs the pinned
`buildarr-prowlarr==0.5.3` into a shared volume. Buildarr has no native env
interpolation, so `entrypoint.sh` renders `${VAR}` placeholders from
`buildarr-secrets` into `/config/buildarr.yml` before starting the daemon.

## Secrets

`buildarr-secrets` (SealedSecret): `PROWLARR_API_KEY`, `SONARR_API_KEY`,
`RADARR_API_KEY`. Re-seal after rotation (strict scope):

```sh
printf '%s' "<api-key>" | kubeseal --cert <cert> --raw \
  --namespace buildarr --name buildarr-secrets
```

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
  to make this file the sole source of truth.
- Managed public indexers: The Pirate Bay, LimeTorrents, Nyaa.si — each verified
  to pass Prowlarr's create-test. Cloudflare/DDoS-Guard sites (1337x, TorrentGalaxy,
  YTS) and legally-blocked ones (EZTV → HTTP 451) fail that test and abort the whole
  apply, so add those by hand in the Prowlarr UI. Public indexer *definitions* are
  maintained by Prowlarr and refreshed on Prowlarr updates — keep the image current.
- Productionization follow-up: bake a custom image with the plugin preinstalled to
  drop the runtime `pip install` (needs PyPI reachability on pod start).
