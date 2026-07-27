# recyclarr

Syncs TRaSH-Guides quality profiles and custom formats into Sonarr and Radarr.
This is the source of truth for **which releases score well** — edit
`recyclarr.yml`, not the Sonarr/Radarr UI.

*Quality definition sizes* are the one exception: they belong to
[`buildarr`](../buildarr/README.md). Both the TRaSH
`sonarr-quality-definition-series` and `radarr-quality-definition-movie`
templates leave maxSize unset on every quality above SD — the first let a single
season reach 50GB, the second let Radarr grab an 86GB Remux-2160p — so neither is
included here. Re-adding either would fight Buildarr nightly.

## What it does

A daily `CronJob` (04:00 UTC) runs `recyclarr sync`, which pulls the pinned
TRaSH templates and applies them to both apps over the cluster network:

- Sonarr → WEB-1080p quality profile + custom formats.
- Radarr → HD Bluray + WEB quality profile + custom formats.

A `recyclarr-sync` Job also runs as an Argo CD `PostSync` hook, so a rebuilt
cluster gets the profiles immediately instead of waiting for 04:00. Buildarr's
`wait-for-dependencies` init container blocks on those profiles existing, which
is what orders the two applications on a cold start.

Series and movies must actually be *assigned* the managed profile; Recyclarr
creates the profile but never moves anything onto it. The default in both apps is
`Any`, which applies no custom-format scoring at all — the
`SonarrSeriesOffManagedProfile` alert covers that gap for Sonarr, and Jellyseerr
pins the profile for anything requested through it.

`delete_old_custom_formats` and `replace_existing_custom_formats` are on, so
Recyclarr fully owns custom formats on both instances.

## Secrets

`recyclarr-secrets` (native Secret) holds `SONARR_API_KEY` and `RADARR_API_KEY`,
injected as env and referenced from the config via `!env_var`. Projected from
Azure Key Vault (`homelab-<service>-api-key`) by the `argocd_bootstrap` Ansible
role on every platform deploy; rotate the Key Vault secret and re-run the
Reconcile Platform workflow.

## Changing quality

Edit the `include:` templates in `recyclarr.yml`. Template names come from the
[recyclarr config templates](https://recyclarr.dev/wiki/) repo. Changes apply on
the next scheduled run, or trigger one:

```sh
kubectl -n recyclarr create job --from=cronjob/recyclarr recyclarr-manual
```
