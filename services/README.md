# Services

This directory contains personal application and MCP source that is developed and deployed with the homelab. Deployment-specific configuration remains under `kubernetes/apps`, while each service directory keeps portable application defaults and local development files.

| Service | Imported from | Import commit | History |
| --- | --- | --- | --- |
| `bookbuddy-web` | `skyhaven-ltd/app-bookbuddy-web` | `7b67ce00b3f59e729ad967edf820cc2b412b9645` | Preserved in this repository |
| `knowledge-mcp` | Developed in this repository | Not applicable | Native history |
| `stockalert-monitor` | `skyhaven-ltd/app-stockalert-monitor` | `f54ba2e7f2bd7a5ad13c914067b802975677e97f` | Pending preservation |

The commit references above identify the source snapshots used for the initial working-tree import. The source repositories must not be deleted until the new CI images have been published, the Kubernetes image digests have been migrated, and either full Git history has been merged or an intentional archive has been retained.
