# Design: self-hosted GitHub Actions runners and Kubernetes pipelines

**Issue:** [infra-homelab-config#10](https://github.com/skyhaven-ltd/infra-homelab-config/issues/10)
**Status:** Draft — awaiting review
**Date:** 2026-07-07

## Problem

The homelab Kubernetes environment (`lnsvrk8s01`, k3s on Proxmox host
`lnproxlab01`) sits on a private network. GitHub-hosted runners cannot reach
it, so this repo has no pipeline that can plan or apply the Terraform (Proxmox
VM lifecycle), run the Ansible configuration (`site.yml`), or verify the
cluster. Today those all run manually from the operator's WSL2 workstation via
the `Makefile`.

Argo CD (bootstrapped by `ansible/roles/argocd_bootstrap`, app-of-apps rooted
at `kubernetes/argocd-apps/root-app.yaml`, tracking `main`) already reconciles
all application and platform manifests from Git. **Runners are therefore not
needed to deploy apps.** They are needed only for what Argo cannot do:

- cluster/VM lifecycle (Terraform against the Proxmox API)
- host and k3s configuration (Ansible over SSH)
- post-change verification (are all Argo applications Synced/Healthy?)

Everything Argo reconciles is **out of scope** for the deploy pipeline.

## Decision 1 — Runner form factor

**Recommendation: one small standalone runner in a dedicated LXC container on
`lnproxlab01`, outside the k3s cluster.** Actions Runner Controller (ARC) on
the cluster is deliberately deferred.

- The runner must survive the cluster being down, rebuilt, or upgraded —
  that is exactly when the deploy pipeline is needed. ARC-only would be a
  chicken-and-egg: the thing that rebuilds the cluster would live on the
  cluster.
- Job volume is tiny (occasional Terraform/Ansible runs); one always-on LXC
  (1 vCPU / 1–2 GiB) is enough and costs little on the 12-core host.
- ARC can be added later for day-2 workloads if job volume ever justifies it;
  nothing in this design blocks that.
- LXC over VM: lighter on the RAM-constrained host (23 GiB total). The runner
  needs no nested virtualisation — jobs run Terraform, Ansible, kubectl, gh.

## Decision 2 — Registration scope

**Recommendation: repo-level runner registered to `infra-homelab-config`
only.**

- Narrowest blast radius: no other repo's workflows can schedule jobs onto a
  machine inside the home network.
- Org-level registration with a restricted runner group adds a moving part in
  `infra-github-platform` for zero current benefit — only this repo needs
  private-network access. Revisit if a second repo ever needs the runner.

## Decision 3 — Security controls

All repos are private, but the runner sits inside the home network, so treat
it as a sensitive ingress point:

1. **Labels and gating.** Runner labels `[self-hosted, homelab]`. Only the
   deploy job targets those labels; lint and validation stay on
   GitHub-hosted runners.
2. **Triggers.** No `pull_request`-triggered job ever runs on the self-hosted
   runner — deploy runs on push to `main` and `workflow_dispatch` only. PR
   code never executes inside the network boundary.
3. **Environment protection.** The deploy job uses a `homelab` environment.
   Environment secrets are then only released to jobs on `main` (and
   optionally after required-reviewer approval — operator's choice).
4. **Secrets.**
   - Kubernetes access: a least-privilege ServiceAccount kubeconfig stored as
     a `homelab` environment secret — not the cluster-admin kubeconfig, and
     not a file baked onto the runner. Verification needs only `get/list` on
     `applications.argoproj.io` and core health objects.
   - Proxmox API token (`TF_VAR_proxmox_api_token`) and SSH key for Ansible:
     environment secrets, injected per-job, never written to the runner image.
   - Terraform state currently lives on the workstation (local backend) —
     see Open questions.
5. **Runner hardening.**
   - Run as a dedicated non-root user via the `actions/runner` systemd unit.
   - `--ephemeral` registration: the runner takes one job, deregisters, and
     the service re-registers with a fresh just-in-time token — no residue
     between jobs.
   - Auto-update left enabled (default).
   - Egress from the LXC restricted to GitHub endpoints plus the Proxmox API,
     the k8s VM, and package mirrors (nftables on the LXC; best-effort, not a
     gate for phase 1).

## Decision 4 — Provisioning as code

**Recommendation: Terraform + Ansible in this repo, mirroring the existing
pattern.**

- `terraform/`: a `proxmox_lxc`/`proxmox_virtual_environment_container`
  resource (bpg/proxmox provider already in use) for the runner container.
- `ansible/roles/gha_runner`: installs the `actions/runner` tarball, creates
  the service user, registers via the systemd unit, `--ephemeral` flag per
  Decision 3. Wired into `site.yml` behind a `gha_runner` tag, same as
  `argocd_bootstrap`.
- **Registration token:** minted at configure time via the org's existing
  `sky-haven-ci` GitHub App (installation already holds `administration:
  write`, which covers `POST /repos/{owner}/{repo}/actions/runners/
  registration-token`). The Ansible role takes a short-lived registration
  token as a variable; a small helper script (or the operator) mints it with
  the App credentials from Key Vault. No PAT is created or stored.

## Decision 5 — Pipeline shape

| Workflow | Trigger | Runner | Does |
| --- | --- | --- | --- |
| `lint.yml` (exists) | PR | GitHub-hosted | Shared `reusable-lint.yml`, unchanged |
| `k8s-validate.yml` (new) | PR | GitHub-hosted | `kubeconform` schema validation and `kustomize build` render of every app under `kubernetes/`; `terraform fmt -check` + `terraform validate` (no backend/cluster access needed) |
| `k8s-deploy.yml` (new) | push to `main` (paths: `terraform/**`, `ansible/**`) + `workflow_dispatch` | `[self-hosted, homelab]`, environment `homelab` | `terraform plan` (apply only via explicit `workflow_dispatch` input, mirroring the org's plan/apply convention); `ansible-playbook site.yml --check` then run; finally verify Argo CD: all Applications Synced/Healthy within a timeout |
| `tag.yml` (exists) | push to `main` | GitHub-hosted | unchanged |

Notes:

- The deploy job **never** `kubectl apply`s anything under `kubernetes/` —
  Argo owns that. The pipeline's cluster interaction is read-only
  verification.
- Terraform `apply` for VM lifecycle is deliberately not automatic on merge
  (destroying/resizing the VM from a push is too sharp); `plan` runs on merge
  for drift visibility, `apply` is a gated dispatch. This can be loosened
  later if it proves annoying.
- All actions pinned by full commit SHA, zizmor-clean, per org convention.

## Decision 6 — Out of scope

- App deployments and platform charts (`kubernetes/**`) — Argo CD reconciles
  these; the only pipeline touch is validation (PR) and health verification
  (post-deploy).
- ARC / in-cluster runners — deferred until job volume justifies it.
- Org-level runner groups — repo-level only for now.
- Backup/DR automation (migration-plan Phase 13) — separate work.

## Open questions for review

1. **Terraform state location.** State for `terraform/` is currently local to
   the operator's WSL2 workstation. For the pipeline to plan/apply, state
   needs a shared home: the org's Azure Storage backend (matches every other
   repo, but couples homelab to Azure) or state kept on the runner LXC
   (simple, but single copy inside the blast radius). Recommend the Azure
   backend for consistency; needs OIDC/credential wiring identical to the
   other repos.
2. **Approval gate.** Should the `homelab` environment require manual
   approval for `apply` dispatches, or is branch-restriction enough given a
   single operator?
3. **Ansible SSH reachability.** The runner LXC needs SSH to `lnsvrk8s01`
   (and the Proxmox API). Confirm no VLAN/firewall segmentation is planned
   that would separate the runner from the targets.

## Acceptance criteria for implementation (Phase 3, after approval)

- [ ] Runner LXC provisioned by Terraform, configured by Ansible, visible as
      `[self-hosted, homelab]` in repo runner settings; rebuild documented in
      `docs/`.
- [ ] `k8s-validate.yml` green on PRs with no private-network access.
- [ ] `k8s-deploy.yml` runs on the homelab runner, gated to main/dispatch
      with the `homelab` environment, and verifies Argo health.
- [ ] Security controls from Decision 3 in place.
