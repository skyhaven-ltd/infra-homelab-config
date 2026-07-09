# GitHub Actions self-hosted runner

The homelab Kubernetes environment is private, so GitHub-hosted runners cannot
reach it. `lnsvrgha01` is an LXC container on `lnproxlab01` that can, and it is
where `k8s-deploy.yml` executes.

Argo CD already reconciles everything under `kubernetes/` from Git, so **the
runner is not needed to deploy applications.** It exists only for the work Argo
cannot do: Proxmox VM lifecycle (Terraform), host and k3s configuration
(Ansible), and post-change verification.

## Shape

| | |
| --- | --- |
| Form | LXC container, `vmid` 300, on `lnproxlab01` |
| Address | `192.168.1.5` (static) |
| Guest | Ubuntu 24.04, unprivileged, nesting off |
| Size | 2 vCPU, 2 GiB RAM, 512 MiB swap, 16 GiB disk |
| Labels | `self-hosted`, `homelab` |
| Scope | this repository only |
| Service account | `ghrunner`, not in `sudo` |

It sits **outside** the k3s cluster on purpose. The runner has to survive the
cluster being down, rebuilt, or upgraded — which is exactly when the deploy
pipeline is needed. A runner inside the cluster it rebuilds is a chicken-and-egg.
Actions Runner Controller was deferred for the same reason; nothing here blocks
adding it later for day-2 workloads.

## Why registration is persistent, not ephemeral

`--ephemeral` deregisters the runner after a single job. To come back it must
re-register, which needs a fresh registration token, which needs a token-minting
credential (a GitHub App private key or a PAT) stored permanently on the LXC.
That credential holds `administration: write` across the org — strictly broader
than the repo-scoped runner registration it would be protecting. Ephemeral would
therefore *increase* the value of what an attacker gets by compromising the box.

The isolation ephemeral buys is instead obtained by narrowing who can run on it:

- Repo-scoped registration: no other repository can schedule onto it.
- No `pull_request`-triggered job ever targets the `homelab` label, so unreviewed
  fork or branch code never executes inside the network boundary.
- The `homelab` GitHub environment releases its secrets only to workflows on
  `main` (enforced by a custom deployment branch policy, because this org
  protects `main` with a repository ruleset rather than classic branch
  protection, and the built-in "protected branches" option ignores rulesets).
- `actions/checkout` cleans the workspace at the start of every job.

Only reviewed code on `main` ever runs on this machine.

## Bootstrapping

`terraform/runner` is a **bootstrap root**: applied by the operator, never by CI.
CI runs *on* the runner, so a pipeline apply of this root would be a job
destroying the machine executing it.

This is not circular. Terraform needs two kinds of access and only one is
private: the Azure state backend is a public endpoint reachable with credentials,
while the Proxmox API is LAN/tailnet-only. Your workstation has both, so it can
create the runner with state already living in Azure. Nothing needs to exist
first.

```bash
# 1. Provision the container. Needs tailnet reachability to the Proxmox API.
export TF_VAR_proxmox_api_token='terraform@pve!tf=...'
make runner-plan
make runner-apply
```

Terraform writes `ansible/inventory/runner.yml`. It is a separate inventory from
`hosts.yml` because `terraform/cluster` owns that file, and two roots writing one
file would clobber each other. `site.yml` selects on the `gha_runner` group, so
its plays are inert under the default inventory.

```bash
# 2. Configure it. The registration token is short-lived (1 hour) and only
#    needed on the FIRST run — the runner persists its own credentials after
#    that, so nothing long-lived is ever stored on the container.
GHA_RUNNER_TOKEN="$(gh api --method POST \
  repos/skyhaven-ltd/infra-homelab-config/actions/runners/registration-token \
  --jq .token)" make runner-configure
```

Re-running `make runner-configure` without a token is safe: the role sees
`.runner` and skips registration, so it stays usable for upgrades and drift
correction.

Confirm it appeared:

```bash
gh api repos/skyhaven-ltd/infra-homelab-config/actions/runners \
  --jq '.runners[] | "\(.name) \(.status) \(.labels | map(.name) | join(","))"'
```

## Secrets the deploy workflow needs

Three secrets on the `homelab` GitHub environment. They are **not** in the
platform Key Vault: none of them grants anything in Azure, and reading them from
Key Vault would mean installing the Azure CLI on this runner and giving it Key
Vault data-plane access it has no other reason to hold. Azure is used for
Terraform state alone, authenticated by the azurerm backend's native OIDC.

| Secret | What it is |
| --- | --- |
| `PROXMOX_API_TOKEN` | `terraform@pve!tf=<uuid>`, becomes `TF_VAR_proxmox_api_token` |
| `ANSIBLE_SSH_PRIVATE_KEY` | private key whose public half is in `ansible/roles/users/files/authorized_keys.d/` |
| `ARGOCD_KUBECONFIG` | least-privilege ServiceAccount kubeconfig, read-only on Argo CD Applications |

```bash
gh secret set PROXMOX_API_TOKEN       --repo skyhaven-ltd/infra-homelab-config --env homelab
gh secret set ANSIBLE_SSH_PRIVATE_KEY --repo skyhaven-ltd/infra-homelab-config --env homelab < ~/.ssh/homelab_deploy
gh secret set ARGOCD_KUBECONFIG       --repo skyhaven-ltd/infra-homelab-config --env homelab < ./argocd-kubeconfig
```

`ARGOCD_KUBECONFIG` must not be the cluster-admin `/etc/rancher/k3s/k3s.yaml`
verbatim. That file points its server at `127.0.0.1:6443`, which on the runner
resolves to the runner. Rewrite the server to the node's LAN address and use a
ServiceAccount token that can only `get`/`list` `applications.argoproj.io`.

The `AZURE_CLIENT_ID`, `AZURE_TENANT_ID` and `AZURE_PLATFORM_SUBSCRIPTION_ID`
*variables* on the same environment are created by `bootstrap-platform.sh` in
`infra-landingzone-platform`; they are GUIDs, not secrets.

## Rebuilding

The container is disposable. `make runner-apply` recreates it and
`make runner-configure` re-registers; `config.sh --replace` reclaims the existing
runner name rather than colliding with the stale registration left in GitHub.

Because `runner.tfstate` lives in Azure and not on the container, losing the LXC
loses nothing. That is the whole argument against keeping state on the runner.

## Upgrading the runner

GitHub auto-updates the runner binary by default. To move the pinned floor, bump
both values in `ansible/roles/gha_runner/defaults/main.yml` together:

```bash
gh api repos/actions/runner/releases/latest --jq .tag_name
gh api repos/actions/runner/releases/latest --jq .body \
  | grep -oP '(?<=<!-- BEGIN SHA linux-x64 -->)[a-f0-9]{64}'
```

Record the new version in `docs/versions.md`, then `make runner-configure`.

## Notes

- The admin `liam` user is not created on the runner: `make runner-configure`
  runs only the `gha_runner` tag. Terraform installs the operator's public key
  for `root`, so `ssh root@192.168.1.5` is the access path. Add `--tags
  gha_runner,users` if you want the standard admin account there too.
- Jobs install `terraform` and `ansible` themselves, so those versions live in
  Git rather than in a hand-built container image. The container only carries
  `git`, `python3`, `acl` and the runner's own .NET dependencies.
