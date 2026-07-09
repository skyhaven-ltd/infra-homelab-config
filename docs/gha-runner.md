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
# 1. Provision the container. Needs tailnet reachability to the Proxmox API and
#    the Proxmox SSH key in your agent (see docs/rollout-runbook.md Stage 0). The
#    API token comes from Key Vault, so this works from any authenticated box.
export TF_VAR_proxmox_api_token="$(az keyvault secret show \
  --vault-name kv-platform-prd-uks-02 --name homelab-proxmox-api-token \
  --query value -o tsv)"
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

Every homelab secret lives in the platform Key Vault, `kv-platform-prd-uks-02`.
One copy, one source of truth: the operator populates and rotates it from any
authenticated workstation, and both CI and the operator read it back — nothing is
copied into a GitHub environment secret or a Bitwarden entry to drift out of sync.

The deploy workflow reads what it needs at job time with the shared
`keyvault-secrets` action — the same pattern every other Skyhaven pipeline uses.
The runner already has `id-token: write` and authenticates to Azure by OIDC; one
`azure/login` at the top of the job establishes the session, and the action reads
the vault under it:

```yaml
- name: Azure Login
  uses: azure/login@532459ea530d8321f2fb9bb10d1e0bcf23869a43
  with:
    client-id: ${{ vars.AZURE_CLIENT_ID }}
    tenant-id: ${{ vars.AZURE_TENANT_ID }}
    subscription-id: ${{ vars.AZURE_PLATFORM_SUBSCRIPTION_ID }}

- name: Fetch secrets from Key Vault
  uses: skyhaven-ltd/pipeline-engineering-github-actions/actions/keyvault-secrets@6cfa143b42ff464e4101d69c09945db9fac369e5
  with:
    keyvault_name: kv-platform-prd-uks-02
    login: "false"        # the job already logged in above
    secrets: |
      TF_VAR_proxmox_api_token=homelab-proxmox-api-token
      ANSIBLE_SSH_PRIVATE_KEY=homelab-ansible-ssh-private-key
      ARGOCD_KUBECONFIG=homelab-argocd-kubeconfig
```

The action masks each value (line by line, so multiline PEM keys and kubeconfigs
stay hidden) and exports it to `$GITHUB_ENV` for later steps.

Two things this pattern costs, both one-time:

- **The runner carries the Azure CLI.** `azure/login` and the action's
  `az keyvault secret show` need it, and this container is minimal by design. It
  is installed by the `gha_runner` Ansible role, so the dependency is in Git, not
  a hand-built image.
- **The federated identity needs read access to the vault.** The
  `homelab` environment's federated credential (`fc-infra-homelab-config-homelab`)
  must hold **Key Vault Secrets User** on `kv-platform-prd-uks-02`. That role is
  assigned in `infra-landingzone-platform` alongside the vault, not here. It is
  strictly read-only and scoped to this one vault.

The secrets themselves (all under the `homelab-` prefix):

| Key Vault secret | Read by | What it is |
| --- | --- | --- |
| `homelab-proxmox-api-token` | CI + operator | `terraform@pve!tf=<uuid>`, becomes `TF_VAR_proxmox_api_token` |
| `homelab-ansible-ssh-private-key` | CI + operator | private key whose public half is in `ansible/roles/users/files/authorized_keys.d/` |
| `homelab-argocd-kubeconfig` | CI + operator | least-privilege ServiceAccount kubeconfig, read-only on Argo CD Applications |
| `homelab-proxmox-ssh-private-key` | operator only | `id_ed25519_proxmox`; the `bpg/proxmox` provider's `ssh-agent` key at apply time. CI reaches Proxmox over the API, not host SSH, so the deploy workflow never fetches this |
| `homelab-tailscale-api-key` | operator only | `TAILSCALE_API_KEY` for the `terraform/tailscale` root, which CI does not run |

Populate or rotate any of them from an authenticated workstation. `--file` keeps
multiline values (private keys, kubeconfigs) intact where `--value` would mangle
newlines:

```bash
az keyvault secret set --vault-name kv-platform-prd-uks-02 \
  --name homelab-proxmox-api-token --value 'terraform@pve!tf=...'
az keyvault secret set --vault-name kv-platform-prd-uks-02 \
  --name homelab-ansible-ssh-private-key --file ~/.ssh/homelab_deploy
az keyvault secret set --vault-name kv-platform-prd-uks-02 \
  --name homelab-argocd-kubeconfig --file ./argocd-kubeconfig
```

`homelab-argocd-kubeconfig` must not be the cluster-admin
`/etc/rancher/k3s/k3s.yaml` verbatim. That file points its server at
`127.0.0.1:6443`, which on the runner resolves to the runner. Rewrite the server
to the node's LAN address and use a ServiceAccount token that can only
`get`/`list` `applications.argoproj.io`.

The `AZURE_CLIENT_ID`, `AZURE_TENANT_ID` and `AZURE_PLATFORM_SUBSCRIPTION_ID`
*variables* on the `homelab` environment are created by `bootstrap-platform.sh`
in `infra-landingzone-platform`; they are GUIDs, not secrets, and drive the
`azure/login` above.

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
  Git rather than in a hand-built container image. The container carries `git`,
  `python3`, `acl`, the Azure CLI (for the Key Vault fetch — installed by the
  `gha_runner` role) and the runner's own .NET dependencies.
