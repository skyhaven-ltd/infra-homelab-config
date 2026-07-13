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

`recyclarr-secrets` (SealedSecret) holds `SONARR_API_KEY` and `RADARR_API_KEY`,
injected as env and referenced from the config via `!env_var`.

Re-seal after rotating a key (kubeseal 0.38.4, strict scope):

```sh
printf '%s' "<api-key>" | kubeseal --cert <cert> --raw \
  --namespace recyclarr --name recyclarr-secrets
```

## Changing quality

Edit the `include:` templates in `configmap.yaml`. Template names come from the
[recyclarr config templates](https://recyclarr.dev/wiki/) repo. Changes apply on
the next scheduled run, or trigger one:

```sh
kubectl -n recyclarr create job --from=cronjob/recyclarr recyclarr-manual
```
