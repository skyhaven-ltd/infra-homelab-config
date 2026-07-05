# infra-homelab-config

Monorepo for the Sky Haven homelab: Proxmox Terraform, Ansible, and Kubernetes
(k3s + Argo CD GitOps) manifests. The workload runs on the k3s cluster
(`lnsvrk8s01`, `192.168.1.3`); the old Docker Compose VM was decommissioned at
Phase 12. See [`docs/k8s-gitops-migration-plan.md`](docs/k8s-gitops-migration-plan.md)
and [`docs/versions.md`](docs/versions.md).

## Layout

| Path             | Contents                                                          |
| ---------------- | ---------------------------------------------------------------- |
| `terraform/`     | Layer 1 — Proxmox VM provisioning (`bpg/proxmox`)                |
| `ansible/`       | Layer 2 — OS config → k3s → Argo CD bootstrap                    |
| `kubernetes/`    | Argo CD's territory — bootstrap, app-of-apps, infra, app manifests |
| `scripts/`       | Legacy compose-era backup helpers (superseded by restic — pending removal) |
| `systemd/`       | Legacy compose-era backup units (superseded by restic — pending removal) |
| `docs/`          | Migration plan and resolved version pins                         |

`make` is the single entrypoint: `infra-plan` / `infra-apply` (Terraform),
`configure` / `bootstrap` (Ansible), `seal` (kubeseal).

The pre-migration `compose/` stack was removed at Phase 12 (Git history preserves
it). Cluster backups are handled by the `restic` timer in `ansible/roles/base`
(Phase 13); the remaining `scripts/` + `systemd/` legacy backup helpers targeted
the retired Docker host and can be deleted or repurposed.
