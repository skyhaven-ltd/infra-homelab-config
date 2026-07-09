# Terraform state migration runbook

One-time operator task. Moves the two existing Terraform roots from local state
on the WSL2 workstation to the shared Azure backend, so the homelab pipeline can
plan and apply.

**Run this once, by hand, from the WSL2 checkout** — the one that has applied the
homelab before. That is the only place `terraform.tfstate` exists; other clones
(for example a Windows checkout) have no state and would upload nothing. CI
cannot do it either: `terraform init -migrate-state` is interactive.

This one constraint — local state lives on one box — is *why* the migration is
tied to that checkout, and it is the last such tie. Every secret the plan needs
(the Proxmox token, the Tailscale key) comes from the platform Key Vault, so once
state is in Azure the ordinary operator tasks run from anywhere with `az login`
and a tailnet route. See [`gha-runner.md`](gha-runner.md) for the vault layout.

Confirm you are in the right checkout before starting:

```bash
test -f terraform/terraform.tfstate || echo "wrong checkout — no local state here"
```

## Why Azure and not the runner

Terraform needs two different kinds of access, and only one of them is private:

| Needs | Endpoint | Reachable from |
| --- | --- | --- |
| Read/write state | `stplatformprduks02.blob.core.windows.net` | anywhere, with Azure credentials |
| Manage the VM | Proxmox API on `100.82.112.92` | LAN/tailnet only |

State was never the private half. Keeping it on the runner LXC would put the only
copy of `runner.tfstate` on the machine that state describes, so losing the LXC
would lose the record of how to rebuild it. Azure Blob has versioning and 30-day
soft delete enabled by `bootstrap-platform.sh`.

## Layout after migration

Every root shares one container, `infra-homelab-config`, separated by state key:

| Root | State key | Applied by |
| --- | --- | --- |
| `terraform/cluster` | `cluster.tfstate` | CI (`k8s-deploy.yml`) |
| `terraform/tailscale` | `tailscale.tfstate` | CI (`k8s-deploy.yml`) |
| `terraform/runner` | `runner.tfstate` | operator only — bootstrap root |

`terraform/runner` is deliberately never applied by CI: it provisions the runner
that CI runs on. Bootstrapping it from the workstation is what breaks the
circularity, and it changes rarely.

## Prerequisites

- `az login`, with Storage Account Contributor on `stplatformprduks02`
  (`spn-personal` and the operator both have it), and **Key Vault Secrets User**
  on `kv-platform-prd-uks-02` to read the plan's secrets (the operator also holds
  **Key Vault Secrets Officer** there to set and rotate them).
- [skyhaven-ltd/infra-landingzone-platform#31](https://github.com/skyhaven-ltd/infra-landingzone-platform/pull/31)
  merged and `bootstrap-platform.sh` re-run, so the `homelab` GitHub environment
  and its federated credential exist.
- The state container exists:

  ```bash
  az storage container create \
    --name infra-homelab-config \
    --account-name stplatformprduks02 \
    --auth-mode login
  ```

## Step 1 — Back up the current state

Do this before anything else. Keep the copies until step 4 passes.

```bash
cp terraform/terraform.tfstate            ~/homelab-cluster.tfstate.bak
cp terraform/tailscale/terraform.tfstate  ~/homelab-tailscale.tfstate.bak
```

## Step 2 — Move the cluster state next to its relocated configuration

The `.tf` files moved from `terraform/` to `terraform/cluster/`, but your local
state file is untracked, so Git left it behind. Move it yourself, and discard the
stale provider cache so `init` rebuilds it.

```bash
mv terraform/terraform.tfstate        terraform/cluster/terraform.tfstate
mv terraform/terraform.tfstate.backup terraform/cluster/ 2>/dev/null || true
rm -rf terraform/.terraform
```

The `tailscale` root did not move, so its state is already in the right place.
Only its provider cache needs clearing:

```bash
rm -rf terraform/tailscale/.terraform
```

## Step 3 — Migrate each root

`init -migrate-state` detects the local state, uploads it to the new backend, and
prompts for confirmation. Answer `yes`.

```bash
terraform -chdir=terraform/cluster init -migrate-state \
  -backend-config="resource_group_name=rg-platform-prd-uks-01" \
  -backend-config="storage_account_name=stplatformprduks02" \
  -backend-config="container_name=infra-homelab-config" \
  -backend-config="key=cluster.tfstate" \
  -backend-config="subscription_id=cefc8742-e1dd-4b24-90a9-07e3d3c80d88"

terraform -chdir=terraform/tailscale init -migrate-state \
  -backend-config="resource_group_name=rg-platform-prd-uks-01" \
  -backend-config="storage_account_name=stplatformprduks02" \
  -backend-config="container_name=infra-homelab-config" \
  -backend-config="key=tailscale.tfstate" \
  -backend-config="subscription_id=cefc8742-e1dd-4b24-90a9-07e3d3c80d88"
```

## Step 4 — Verify no drift

This is the check that the move lost nothing. Both plans must report **no
changes**. A plan proposing to create the VM means the state did not migrate and
you are one `apply` away from a duplicate — stop and restore from step 1.

```bash
export TF_VAR_proxmox_api_token="$(az keyvault secret show \
  --vault-name kv-platform-prd-uks-02 --name homelab-proxmox-api-token --query value -o tsv)"
export TAILSCALE_API_KEY="$(az keyvault secret show \
  --vault-name kv-platform-prd-uks-02 --name homelab-tailscale-api-key --query value -o tsv)"

terraform -chdir=terraform/cluster   plan -var-file="vars/homelab.tfvars"
terraform -chdir=terraform/tailscale plan
```

## Step 5 — Clean up

Once both plans are clean, remove the now-unused local state and keep the backups
for a week.

```bash
rm -f terraform/cluster/terraform.tfstate terraform/cluster/terraform.tfstate.backup
rm -f terraform/tailscale/terraform.tfstate terraform/tailscale/terraform.tfstate.backup
```

From here `make infra-plan`, `make infra-apply`, and `make tailscale-apply` init
against Azure automatically. They run a plain `init`, not `-migrate-state`, so
this runbook is not needed again.

## Recovery

Blob versioning and 30-day soft delete are on. To recover a clobbered state:

```bash
az storage blob list --account-name stplatformprduks02 \
  --container-name infra-homelab-config --include v \
  --auth-mode login --output table
```

Then `az storage blob copy start` the wanted version over the current blob. If a
run is interrupted and leaves a lease, the deploy workflow's `break-tfstate-lease`
step clears it; locally, `terraform force-unlock <lock-id>`.
