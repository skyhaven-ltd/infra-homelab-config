# infra-homelab-config

Monorepo for the Sky Haven homelab: Proxmox Terraform, Ansible, and Kubernetes
(k3s + Argo CD GitOps) manifests. Migration in progress — see
[`docs/k8s-gitops-migration-plan.md`](docs/k8s-gitops-migration-plan.md) and
[`docs/versions.md`](docs/versions.md).

## Layout

| Path             | Contents                                                          |
| ---------------- | ---------------------------------------------------------------- |
| `terraform/`     | Layer 1 — Proxmox VM provisioning (`bpg/proxmox`)                |
| `ansible/`       | Layer 2 — OS config → k3s → Argo CD bootstrap                    |
| `kubernetes/`    | Argo CD's territory — bootstrap, app-of-apps, infra, app manifests |
| `compose/`       | **Legacy** Docker Compose stack (retired at Phase 12)           |
| `scripts/`       | Helper scripts (media/appdata backup)                            |
| `systemd/`       | Units for the legacy compose backup                              |
| `docs/`          | Migration plan and resolved version pins                         |

`make` is the single entrypoint: `infra-plan` / `infra-apply` (Terraform),
`configure` / `bootstrap` (Ansible), `seal` (kubeseal).

## Legacy compose stack

The pre-migration Docker Compose stack (Plex, Sonarr, Radarr, Prowlarr,
qBittorrent, Audiobookshelf, Home Assistant, Pi-hole, Syncthing) now lives in
[`compose/compose.yaml`](compose/compose.yaml), with a scheduled appdata backup
via the `systemd/` units. It stays in service until cutover, then is removed in
Phase 12.
