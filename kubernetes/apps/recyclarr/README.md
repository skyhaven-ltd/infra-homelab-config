# recyclarr

Syncs TRaSH-Guides quality definitions, quality profiles, and custom formats into
Sonarr and Radarr. This is the source of truth for **download video quality** — edit
`configmap.yaml`, not the Sonarr/Radarr UI.

## What it does

A daily `CronJob` (04:00 UTC) runs `recyclarr sync`, which pulls the pinned
TRaSH templates and applies them to both apps over the cluster network:

- Sonarr → WEB-1080p quality profile + custom formats.
- Radarr → HD Bluray + WEB quality profile + custom formats.

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
