# Services

This directory contains personal application source that is developed and deployed with the homelab. Deployment-specific configuration remains under `kubernetes/apps`, while each service directory keeps portable application defaults and local development files.

| Service | Imported from | Import commit | History |
| --- | --- | --- | --- |
| `stockalert-monitor` | `skyhaven-ltd/app-stockalert-monitor` | `f54ba2e7f2bd7a5ad13c914067b802975677e97f` | Archived in `history/app-stockalert-monitor.bundle` |

The commit references above identify the source snapshots used for the initial working-tree import. The source repositories must not be deleted until the new CI images have been published, the Kubernetes image digests have been migrated, and either full Git history has been merged or an intentional archive has been retained.
