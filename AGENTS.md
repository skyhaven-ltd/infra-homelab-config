# Repository agent guide

This repository manages the Sky Haven homelab: Proxmox infrastructure, a single-node k3s cluster, GitOps workloads, and locally developed services. Use this guide with the user's global agent instructions. Treat repository configuration and live inspection as authoritative when documentation drifts.

## Homelab access: connect through WSL Ubuntu

When the user asks to investigate or fix something on the homelab, connect and perform the requested work. Do not ask the user to run routine diagnostics or reconfirm SSH access. Keep changes within the requested scope and verify the result on the affected host or service.

On Windows, run SSH through **WSL `Ubuntu-24.04`**, not Windows OpenSSH or the `docker-desktop` distribution. Existing credentials and SSH configuration live inside Ubuntu. From an Ubuntu shell, use the same SSH commands without the `wsl.exe -d Ubuntu-24.04 --` prefix.

| Target | Address | SSH user | Repository inventory |
| --- | --- | --- | --- |
| k3s node `lnsvrk8s01` | `192.168.1.3` | `ops` | `ansible/inventory/hosts.yml` |
| Proxmox host `lnproxlab01` | `192.168.1.2` | `root` | `ansible/inventory/proxmox.yml` |
| GitHub Actions runner `lnsvrgha01` | `192.168.1.5` | `root` | `ansible/inventory/runner.yml` |

These commands were verified from Windows host `wnwslab01` on 2026-10-11. Run them from PowerShell:

```powershell
wsl.exe -d Ubuntu-24.04 -- ssh -i /home/lgoodchild-a/.ssh/homelab_ops_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=10 ops@192.168.1.3 hostname
wsl.exe -d Ubuntu-24.04 -- ssh -o BatchMode=yes -o ConnectTimeout=10 proxmox hostname
```

Expected hostnames are `lnsvrk8s01` and `lnproxlab01`. The WSL `proxmox` alias supplies the address, user, and identity. Use the explicit `homelab_ops_ed25519` identity for k3s; the existing `k8s` alias selects a different key. The runner address above comes from inventory; its login was not verified as part of this guide.

Run Kubernetes diagnostics on the node through the same connection:

```powershell
wsl.exe -d Ubuntu-24.04 -- ssh -i /home/lgoodchild-a/.ssh/homelab_ops_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=10 ops@192.168.1.3 'sudo -n k3s kubectl get nodes'
wsl.exe -d Ubuntu-24.04 -- ssh -i /home/lgoodchild-a/.ssh/homelab_ops_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=10 ops@192.168.1.3 'sudo -n k3s kubectl get pods -A'
```

Replace the remote command with the required diagnostic or repair. Use `sudo -n` for privileged commands so unavailable privileges fail instead of waiting for a password. Check the namespace and resource name before making changes.

The absolute key path is specific to this workstation. On another machine, inspect `wsl.exe --list --quiet`, the Ubuntu username, and SSH configuration before selecting credentials. Do not assume access is unavailable merely because native Windows SSH fails. Avoid unquoted `~` in PowerShell arguments; it can expand to a Windows path. For complex quoting, use a temporary Bash script with LF line endings and run it through WSL rather than nesting several shells.

Never print or commit private keys, kubeconfigs, tokens, or decoded Secrets. If access fails, report the exact connection error and inspect the existing configuration before changing authentication. See [SSH access setup](docs/ssh-access-setup.md) for bootstrap details; use the verified WSL commands above for this workstation.

## Repository map

| Location | Responsibility |
| --- | --- |
| `terraform/cluster/` | Proxmox k3s VM and generated k3s Ansible inventory |
| `terraform/runner/` | Proxmox runner container and generated runner inventory |
| `terraform/tailscale/` | Tailnet device key, subnet routes, and DNS |
| `ansible/site.yml`, `ansible/roles/` | Host users, base OS, k3s, Tailscale, Argo CD bootstrap, backups, metrics, runner, and Proxmox disk monitoring |
| `kubernetes/argocd-apps/` | Root Argo CD application and child application definitions |
| `kubernetes/apps/` | Application manifests, Kustomize resources, and deployment-specific configuration |
| `kubernetes/infrastructure/` | Monitoring, ingress-nginx, cert-manager, and certificate issuers |
| `kubernetes/bootstrap/argocd/` | Argo CD bootstrap resources |
| `services/` | Python application source, tests, Dockerfiles, and local development configuration |
| `.github/workflows/` | Validation, image publishing, platform reconciliation, and repository automation |
| `.github/validation/` | Shared lint configuration and validation tests |
| `.github/workflows/linters/` | Lychee link-check configuration |
| `docs/` | Operational runbooks |
| `Makefile` | Terraform initialization/plans/applies, Ansible configuration, bootstrap, and secret sealing shortcuts |

Keep the existing layout conventions when adding files:

- Terraform roots keep scaffolding in underscore-prefixed files (`_data.tf`, `_locals.tf`, `_outputs.tf`, `_providers.tf`, `_terraform.tf`, `_variables.tf`), resources in files named for what they manage, and values in `vars/*.tfvars`.
- Ansible roles use the standard `defaults/`, `files/`, `handlers/`, `tasks/`, and `templates/` directories, with `main.yml` entry points and `.j2` templates.
- Kubernetes apps name manifests for their kind beside `kustomization.yaml` (`deployment.yaml`, `service.yaml`, `ingress.yaml`, `pvc.yaml`, `sealedsecret.yaml`), add a purpose prefix when an app has more than one of a kind (`service-lan.yaml`, `reconcile-job.yaml`), and put scripts and configuration consumed by `configMapGenerator` under `files/`.
- Argo CD definitions use `app-<name>.yaml` for workloads, `infra-<name>.yaml` for platform components, and `root-app.yaml` for the app-of-apps root.

The only local service is `stockalert-monitor`, which deploys under `kubernetes/apps/stockalert`.

Other workloads cover media requests/downloads/playback, audiobooks, home automation, Pi-hole, and openGym. Discover the affected app under `kubernetes/apps/` and its Argo CD definition instead of assuming every workload has source under `services/`.

## Change and deployment ownership

- Diagnose live state first: relevant Argo CD application status, pods, events, bounded logs, and host systemd units. Follow the affected service's README or runbook.
- Put persistent fixes in the owning Terraform, Ansible, application source, or Kubernetes configuration. A live repair alone is incomplete when reconciliation would undo it. Record any temporary live changes and reconcile them with the repository.
- Argo CD's root application tracks `main` and enables automated pruning and self-healing. Inspect the affected child application's source and sync policy before applying changes. Removing managed resources can delete them from the cluster.
- `.github/workflows/platform-deploy.yml` runs platform reconciliation on every push to `main`, including documentation-only merges. A feature-branch push does not deploy that branch through the root Argo CD application.
- Terraform uses Azure Blob remote state with separate `cluster.tfstate`, `runner.tfstate`, and `tailscale.tfstate` keys. Use the existing Makefile/workflow backend settings. Plan before applying and inspect replacements or deletions. Do not run concurrent applies against the same state.
- `ansible/inventory/hosts.yml` and `ansible/inventory/runner.yml` are generated by Terraform. Change their Terraform inputs/templates when changing infrastructure, rather than relying on manual inventory edits.
- Use the appropriate Ansible inventory and role tags. The default k3s inventory does not include Proxmox or the runner.
- Most Kubernetes images are digest-pinned. Preserve that convention where present. StockAlert currently uses `:latest` with workflow-driven deployment refreshes; check the service workflow before assuming a source change updates the running image.
- Buildarr owns Prowlarr configuration and Sonarr/Radarr size limits, root folders, free-space limits, and renaming. Recyclarr owns quality profiles and custom formats. Jellyseerr service links are reconciled by a PostSync job. Change the owning configuration to avoid competing reconcilers.
- Keep portable service defaults in `services/` and homelab deployment configuration in `kubernetes/apps/`. Preserve existing whitespace and line endings on unchanged code. Do not add code comments or unrelated cleanup.

## Verification

Use the affected workflow as the source of exact tool versions and checks. Run focused checks for the change; do not apply infrastructure merely to validate syntax.

| Change | Checks |
| --- | --- |
| Terraform | `terraform fmt -check -recursive terraform/<root>`, `terraform -chdir=terraform/<root> init -backend=false -input=false`, then `terraform -chdir=terraform/<root> validate`; use a separate working directory from an initialized live backend when needed |
| Kubernetes | Render the affected directory with `kustomize build`; run the strict `kubeconform` checks and CRD schema settings from `platform-validate.yml` |
| Ansible | From `ansible/`, install `requirements.yml` collections and run `ansible-lint site.yml`; use the correct inventory for any targeted check-mode run |
| StockAlert | In `services/stockalert-monitor`, install `requirements.txt` and the workflow's pytest version, then run `python -m pytest` |
| Documentation | Check referenced paths, command accuracy, and `git diff --check` |

The service workflow uses Python 3.12. Use an isolated environment for each service. For deployed fixes, verify rollout or unit status and the actual affected behavior; a successful SSH connection or command exit alone does not prove recovery.

## Operational references

- [Backup and restore](docs/backup-restore.md): app data under `/srv/appdata/local-path`, nightly archives, and OneDrive uploads. Preserve mount/integrity checks and bounded retention. Backups use `rclone copy`, not `rclone sync`. Media under `/mnt/media` is not backed up by this mechanism.
- [Observability](docs/observability.md): Grafana Homelab dashboards, Prometheus/Alertmanager, ntfy, host metrics, disk monitoring, and Tailscale/API access.
- [GitHub Actions runner](docs/gha-runner.md): runner provisioning and operation.
- [Home automation](docs/home-automation.md): Home Assistant, MQTT, and Zigbee2MQTT.
- [Media configuration](docs/arr-quality-types.md) and [private indexers/Usenet](docs/private-indexers-and-usenet.md): media stack conventions.
- [Buildarr](kubernetes/apps/buildarr/README.md), [Recyclarr](kubernetes/apps/recyclarr/README.md), and [Jellyseerr](kubernetes/apps/jellyseerr/README.md): reconciliation ownership and prerequisites.
- [Shelfmark](kubernetes/apps/shelfmark/README.md) and [Audiobookshelf](kubernetes/apps/audiobookshelf/README.md): book requests and audiobook hosting.
- [Orca remote server](docs/orca-remote-server.md): remote-server design and rollout context; confirm live implementation before assuming a planned component exists.

## Git and handoff

Keep changes scoped to the request and preserve unrelated work. Create branches only under `patch/`, `minor/`, or `major/`. Use the installed `git-commit-push` skill for authorized commits/pushes and `create-pr` for authorized pull requests. Do not include agent attribution in remote messages, commits, or documentation. Follow the user's global Orca workflow only when an Orca phase is requested.

Report what changed, the verification evidence, and material remaining risks. Distinguish repository changes, live repairs, and deployed changes; do not claim a branch push has deployed a fix.
