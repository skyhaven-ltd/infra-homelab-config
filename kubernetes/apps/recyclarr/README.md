# recyclarr

Syncs TRaSH-Guides quality profiles and custom formats into Sonarr and Radarr.
This is the source of truth for **which releases score well** — edit
`configmap.yaml`, not the Sonarr/Radarr UI.

Sonarr *quality definition sizes* are the one exception: they belong to
[`buildarr`](../buildarr/README.md). The TRaSH `sonarr-quality-definition-series`
template leaves maxSize unlimited on every HD quality, which let a single season
reach 50GB, so it is deliberately not included here. Re-adding it would fight
Buildarr nightly.

## What it does

A daily `CronJob` (04:00 UTC) runs `recyclarr sync`, which pulls the pinned
TRaSH templates and applies them to both apps over the cluster network:

- Sonarr → WEB-1080p quality profile + custom formats.
- Radarr → HD Bluray + WEB quality profile + custom formats, plus the movie
  quality definition sizes.

Series must actually be *assigned* the WEB-1080p profile; Recyclarr creates the
profile but never moves series onto it. Sonarr's default is `Any`, which applies
no custom-format scoring at all — the `SonarrSeriesOffManagedProfile` alert
covers that gap.

`delete_old_custom_formats` and `replace_existing_custom_formats` are on, so
Recyclarr fully owns custom formats on both instances.

## Secrets

`recyclarr-secrets` (native Secret) holds `SONARR_API_KEY` and `RADARR_API_KEY`,
injected as env and referenced from the config via `!env_var`. Projected from
Azure Key Vault (`homelab-<service>-api-key`) by the `argocd_bootstrap` Ansible
role on every platform deploy; rotate the Key Vault secret and re-run the
Reconcile Platform workflow.

## Changing quality

Edit the `include:` templates in `configmap.yaml`. Template names come from the
[recyclarr config templates](https://recyclarr.dev/wiki/) repo. Changes apply on
the next scheduled run, or trigger one:

```sh
kubectl -n recyclarr create job --from=cronjob/recyclarr recyclarr-manual
```
