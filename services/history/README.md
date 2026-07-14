# Source repository archives

These Git bundles preserve the complete refs, objects, tags, and commit history of the application repositories that were consolidated here. Verify or restore an archive with standard Git commands:

```powershell
git bundle verify services/history/app-bookbuddy-web.bundle
git clone services/history/app-bookbuddy-web.bundle app-bookbuddy-web
```

| Archive | Original default branch tip | SHA-256 |
| --- | --- | --- |
| `app-bookbuddy-web.bundle` | `7b67ce00b3f59e729ad967edf820cc2b412b9645` | `ef2e0902a028c69b27125300d8eb6bfe5e63ffcc9e57536c6c2cb764dafa42bf` |
| `app-stockalert-monitor.bundle` | `f54ba2e7f2bd7a5ad13c914067b802975677e97f` | `44cd523c68898fb44added52fa1695d0bcf6db4a0248fb7810e74798b0ae9bb3` |
