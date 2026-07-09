# infra-homelab-config

Monorepo for the Sky Haven homelab, provisioning and configuring a single-node k3s cluster (`lnsvrk8s01`) end to end. Terraform creates the Proxmox VM, Ansible configures the OS and installs k3s plus Argo CD, and Argo CD then syncs the `kubernetes/` manifests (self-hosted media, DNS, and utility apps) via GitOps. `make` is the entrypoint for the plan/apply, configure/bootstrap, and secret-sealing steps.

## Terraform roots

Each root keeps its own state file in the `infra-homelab-config` container of the
shared Azure backend, separated by state key.

| Root | State key | Applied by |
| --- | --- | --- |
| `terraform/cluster` | `cluster.tfstate` | CI (`k8s-deploy.yml`) or `make infra-apply` |
| `terraform/tailscale` | `tailscale.tfstate` | `make tailscale-apply` |
| `terraform/runner` | `runner.tfstate` | operator only — `make runner-apply` |

`terraform/runner` is a **bootstrap root**: it provisions the self-hosted runner
that CI executes on, so CI must never apply it. This is not circular. Terraform
needs two kinds of access and only one is private — the Azure state backend is a
public endpoint, while the Proxmox API is LAN/tailnet-only. A workstation has
both, so it can create the runner with state already living in Azure.

## Pipelines

| Workflow | Trigger | Runner | Does |
| --- | --- | --- | --- |
| `lint.yml` | PR | GitHub-hosted | Shared MegaLinter |
| `k8s-validate.yml` | PR | GitHub-hosted | `terraform fmt`/`validate` per root, `kustomize build` + `kubeconform` over every manifest, `ansible-lint` |
| `k8s-deploy.yml` | push to `main`, `workflow_dispatch` | `[self-hosted, homelab]` | Terraform plan (apply only on dispatch), Ansible, then waits for every Argo CD Application to be Synced and Healthy |
| `tag.yml` | PR merge | GitHub-hosted | Shared tagging |

Validation never touches the private network, so it is safe on `pull_request`.
Deployment does, so `pull_request` is not one of its triggers and its `homelab`
environment only releases secrets to workflows on `main`. A push to `main` only
plans; applying is a deliberate `workflow_dispatch`.

Argo CD owns everything under `kubernetes/`, so the deploy workflow never
`kubectl apply`s an application manifest. It does only what Argo cannot: VM
lifecycle, host configuration, and verifying the result.

## Documentation

- [`docs/gha-runner.md`](docs/gha-runner.md) — the self-hosted runner: shape, why
  registration is persistent rather than ephemeral, bootstrapping, and rebuilds.
- [`docs/terraform-state-migration.md`](docs/terraform-state-migration.md) —
  one-time runbook for moving local state onto the Azure backend.
- [`docs/ssh-access-setup.md`](docs/ssh-access-setup.md) — admin user and SSH access.
- [`docs/versions.md`](docs/versions.md) — every pinned artifact and environment fact.
