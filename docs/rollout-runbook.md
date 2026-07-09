# Rollout runbook — self-hosted runner and pipelines

One-time sequence to take issue #10 from three open pull requests to a working
pipeline. Run it from the **WSL2 checkout**, which is the only machine that has
both the current Terraform state and tailnet reachability to Proxmox.

Each stage ends in a **Gate**. If a gate fails, stop and fix it there — later
stages assume the earlier ones held.

Detail lives in [`terraform-state-migration.md`](terraform-state-migration.md)
and [`gha-runner.md`](gha-runner.md); this document is the order of operations.

## Contents

| Stage | Does | Reversible? |
| --- | --- | --- |
| 0 | Preflight | n/a |
| 1 | Land the Azure prerequisite (PR #31) | yes |
| 2 | Land the Terraform restructure (PR #13) and migrate state | yes, from backup |
| 3 | Create the `homelab` environment secrets | yes |
| 4 | Land the runner and pipelines (PR #14) | yes |
| 5 | Bootstrap the runner | yes — `terraform destroy` the runner root |
| 6 | First pipeline run | plan first, then apply |

---

## Stage 0 — Preflight

Set these once per shell. Every later stage assumes them.

```bash
export HOMELAB=~/repos/infra-homelab-config      # adjust to your paths
export LANDINGZONE=~/repos/infra-landingzone-platform
export NODE_IP=192.168.1.3                       # lnsvrk8s01
export RUNNER_IP=192.168.1.5                     # lnsvrgha01
export REPO=skyhaven-ltd/infra-homelab-config
```

Tools:

`kubectl` is needed only for the Stage 3 gate; everything else is used throughout.

```bash
for c in az gh terraform ansible-playbook ssh-add ssh-keygen jq base64 curl kubectl; do
  command -v "$c" >/dev/null || echo "MISSING: $c"
done
terraform version | head -1     # must be >= 1.9
```

Authentication and reachability:

```bash
az account show --query '{subscription:name, user:user.name}' -o jsonc
gh auth status

# Proxmox answers on 8006 with a self-signed cert, hence -k. Any HTTP code is a
# reachable API; a timeout means you have no tailnet route.
curl -sk --max-time 5 -o /dev/null -w 'Proxmox API: HTTP %{http_code}\n' \
  https://100.82.112.92:8006/ || echo "NO Proxmox route"
```

The `bpg/proxmox` provider uses `ssh { agent = true }`, so the Proxmox SSH key
must be loaded or every apply fails late, after it has already talked to the API:

```bash
ssh-add -l | grep -q proxmox || ssh-add ~/.ssh/id_ed25519_proxmox
```

The Proxmox API token is never in Git. Pull it from Bitwarden into the shell:

```bash
export TF_VAR_proxmox_api_token='terraform@pve!tf=...'
```

**Gate.** `az account show` names the right tenant, `gh auth status` is logged
in, the Proxmox port check succeeds, and `ssh-add -l` lists the Proxmox key.

---

## Stage 1 — Land the Azure prerequisite (PR #31)

Without this there is no federated credential, and every CI `terraform init`
fails at authentication.

```bash
gh pr merge 31 --repo skyhaven-ltd/infra-landingzone-platform --squash --delete-branch
cd "$LANDINGZONE" && git checkout main && git pull
```

Re-run the bootstrap. It is idempotent: it creates the `homelab` GitHub
environment, its federated credential `fc-infra-homelab-config-homelab`, the
`AZURE_*` variables, and a `main`-only deployment branch policy. Everything else
it touches already exists and is skipped.

```bash
./scripts/bootstrap-platform.sh
```

**Gate.** All three must be true:

```bash
gh api "repos/$REPO/environments" --jq '.environments[].name'
# expect: homelab

gh api "repos/$REPO/environments/homelab/deployment-branch-policies" \
  --jq '.branch_policies[].name'
# expect: main    <-- if this is empty, the environment is claimable from ANY branch

gh variable list --repo "$REPO" --env homelab
# expect: AZURE_CLIENT_ID, AZURE_TENANT_ID, AZURE_SUBSCRIPTION_ID, AZURE_PLATFORM_SUBSCRIPTION_ID
```

---

## Stage 2 — Land the restructure and migrate state (PR #13)

```bash
gh pr merge 13 --repo "$REPO" --squash --delete-branch
cd "$HOMELAB" && git checkout main && git pull
```

Confirm you are in the checkout that actually holds the state. A different clone
would upload nothing and a later plan would offer to rebuild the VM:

```bash
test -f terraform/terraform.tfstate \
  && echo "state present — correct checkout" \
  || { echo "WRONG CHECKOUT — no local state here"; }
```

Back it up before touching anything:

```bash
cp terraform/terraform.tfstate            ~/homelab-cluster.tfstate.bak
cp terraform/tailscale/terraform.tfstate  ~/homelab-tailscale.tfstate.bak
```

Create the state container (once). If `--auth-mode login` is refused, you lack
the Storage Blob data role; drop the flag to fall back to the account key.

```bash
az storage container create \
  --name infra-homelab-config \
  --account-name stplatformprduks02 \
  --auth-mode login
```

The `.tf` files moved to `terraform/cluster/`, but your untracked state file did
not follow them. Move it, and clear the stale provider caches:

```bash
mv terraform/terraform.tfstate        terraform/cluster/terraform.tfstate
mv terraform/terraform.tfstate.backup terraform/cluster/ 2>/dev/null || true
rm -rf terraform/.terraform terraform/tailscale/.terraform
```

Migrate each root. Answer `yes` at the prompt.

```bash
BACKEND=(
  -backend-config="resource_group_name=rg-platform-prd-uks-01"
  -backend-config="storage_account_name=stplatformprduks02"
  -backend-config="container_name=infra-homelab-config"
  -backend-config="subscription_id=cefc8742-e1dd-4b24-90a9-07e3d3c80d88"
)

terraform -chdir=terraform/cluster   init -migrate-state "${BACKEND[@]}" -backend-config="key=cluster.tfstate"
terraform -chdir=terraform/tailscale init -migrate-state "${BACKEND[@]}" -backend-config="key=tailscale.tfstate"
```

**Gate — the most important one in this document.** Both plans must report **no
changes**. A plan proposing to *create* `proxmox_virtual_environment_vm.k8s`
means the state did not migrate, and one `apply` away is a duplicate VM. Stop and
restore from the backups above.

```bash
terraform -chdir=terraform/cluster plan -var-file="vars/homelab.tfvars"
TAILSCALE_API_KEY='tskey-api-...' terraform -chdir=terraform/tailscale plan
```

Then clean up the local copies (the backups in `~` stay for a week):

```bash
rm -f terraform/cluster/terraform.tfstate terraform/cluster/terraform.tfstate.backup
rm -f terraform/tailscale/terraform.tfstate terraform/tailscale/terraform.tfstate.backup
```

From here `make infra-plan` inits against Azure by itself.

---

## Stage 3 — Create the `homelab` environment secrets

Three secrets. None is in Key Vault, on purpose: they grant nothing in Azure, and
reading them from a vault would mean putting the Azure CLI on the runner and
giving it data-plane access it has no other reason to hold.

### 3a. `PROXMOX_API_TOKEN`

```bash
gh secret set PROXMOX_API_TOKEN --repo "$REPO" --env homelab --body "$TF_VAR_proxmox_api_token"
```

### 3b. `ANSIBLE_SSH_PRIVATE_KEY`

Ansible connects to the k3s node as `ops`, whose authorised key is the
`ssh_public_key` in `terraform/cluster/vars/homelab.tfvars`. You need its private
half. Find which of your keys matches rather than guessing:

```bash
WANT=$(awk '/^ssh_public_key/ {print $4}' terraform/cluster/vars/homelab.tfvars | tr -d '"')
for k in ~/.ssh/id_*; do
  case "$k" in *.pub) continue;; esac
  if [ "$(ssh-keygen -y -f "$k" 2>/dev/null | awk '{print $2}')" = "$WANT" ]; then
    export OPS_KEY="$k"; echo "MATCH: $OPS_KEY"
  fi
done
```

Sanity-check it actually logs in, then store it:

```bash
ssh -i "$OPS_KEY" -o BatchMode=yes "ops@${NODE_IP}" true && echo "ssh ok"
gh secret set ANSIBLE_SSH_PRIVATE_KEY --repo "$REPO" --env homelab < "$OPS_KEY"
```

### 3c. `ARGOCD_KUBECONFIG`

Not the cluster-admin `k3s.yaml`. That file's server is `127.0.0.1:6443`, which
on the runner would resolve to the runner. Create a read-only ServiceAccount and
build a kubeconfig pointing at the node's LAN address — `tls-san` in the k3s role
already covers it, so the certificate will validate.

These objects are applied out of band and are not in the repo, so Argo CD does
not manage or prune them.

```bash
ssh "ops@${NODE_IP}" 'sudo tee /tmp/argocd-ro.yaml >/dev/null' <<'EOF'
apiVersion: v1
kind: ServiceAccount
metadata:
  name: argocd-readonly
  namespace: argocd
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: argocd-readonly
  namespace: argocd
rules:
  - apiGroups: ["argoproj.io"]
    resources: ["applications"]
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: argocd-readonly
  namespace: argocd
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: argocd-readonly
subjects:
  - kind: ServiceAccount
    name: argocd-readonly
    namespace: argocd
---
apiVersion: v1
kind: Secret
metadata:
  name: argocd-readonly-token
  namespace: argocd
  annotations:
    kubernetes.io/service-account.name: argocd-readonly
type: kubernetes.io/service-account-token
EOF

ssh "ops@${NODE_IP}" 'sudo k3s kubectl apply -f /tmp/argocd-ro.yaml && rm -f /tmp/argocd-ro.yaml'
```

Assemble the kubeconfig locally:

```bash
set -euo pipefail
umask 077
TOKEN=$(ssh "ops@${NODE_IP}" "sudo k3s kubectl -n argocd get secret argocd-readonly-token -o jsonpath='{.data.token}'" | base64 -d)
CA=$(ssh   "ops@${NODE_IP}" "sudo k3s kubectl -n argocd get secret argocd-readonly-token -o jsonpath='{.data.ca\.crt}'")

[ -n "$TOKEN" ] && [ -n "$CA" ] || { echo "token or CA empty — the Secret has not been populated yet, retry in a few seconds"; }

cat > /tmp/argocd-kubeconfig <<EOF
apiVersion: v1
kind: Config
clusters:
  - name: homelab
    cluster:
      server: https://${NODE_IP}:6443
      certificate-authority-data: ${CA}
users:
  - name: argocd-readonly
    user:
      token: ${TOKEN}
contexts:
  - name: homelab
    context:
      cluster: homelab
      user: argocd-readonly
      namespace: argocd
current-context: homelab
EOF
```

**Gate.** It can read Applications, and nothing else:

```bash
KUBECONFIG=/tmp/argocd-kubeconfig kubectl -n argocd get applications.argoproj.io
KUBECONFIG=/tmp/argocd-kubeconfig kubectl -n argocd get secrets 2>&1 | head -1
# expect: the first succeeds, the second is Forbidden
```

Store it and shred the copy:

```bash
gh secret set ARGOCD_KUBECONFIG --repo "$REPO" --env homelab < /tmp/argocd-kubeconfig
shred -u /tmp/argocd-kubeconfig
gh secret list --repo "$REPO" --env homelab
```

---

## Stage 4 — Land the runner and pipelines (PR #14)

```bash
gh pr merge 14 --repo "$REPO" --squash --delete-branch
cd "$HOMELAB" && git checkout main && git pull
```

This also closes issue #10.

---

## Stage 5 — Bootstrap the runner

`terraform/runner` is a bootstrap root: it provisions the machine CI runs on, so
CI must never apply it. You are standing inside the network boundary, which is
what makes this possible without a runner already existing.

```bash
make runner-plan     # expect: 2 to add (the template download + the container)
make runner-apply
```

Terraform writes `ansible/inventory/runner.yml`. Confirm the container answers:

```bash
ssh -o BatchMode=yes "root@${RUNNER_IP}" 'hostnamectl --static'   # expect: lnsvrgha01
```

Configure it. The registration token is short-lived (one hour) and is needed only
on this first run — afterwards the runner persists its own credentials, so
nothing long-lived is ever stored on the container.

```bash
GHA_RUNNER_TOKEN="$(gh api --method POST \
  "repos/${REPO}/actions/runners/registration-token" --jq .token)" \
  make runner-configure
```

**Gate.** The runner is online with both labels:

```bash
gh api "repos/${REPO}/actions/runners" \
  --jq '.runners[] | "\(.name) \(.status) \(.labels | map(.name) | join(","))"'
# expect: lnsvrgha01 online self-hosted,homelab
```

If it is `offline`, look at the unit on the box:

```bash
ssh "root@${RUNNER_IP}" 'systemctl status "actions.runner.*" --no-pager -l | head -30'
```

---

## Stage 6 — First pipeline run

Plan first. A push to `main` only ever plans; applying is always a deliberate
dispatch, because this manages physical infrastructure.

```bash
gh workflow run Deploy --repo "$REPO" --ref main -f terraform_action=plan
sleep 5 && gh run watch "$(gh run list --repo "$REPO" --workflow Deploy --limit 1 --json databaseId --jq '.[0].databaseId')"
```

**Gate.** The plan reports **no changes**. That proves four things at once: OIDC
worked, the backend resolved, the runner reached the Proxmox API, and the
migrated state matches reality.

Only then apply. This runs Ansible against the node and waits for every Argo CD
Application to report Synced and Healthy.

```bash
gh workflow run Deploy --repo "$REPO" --ref main -f terraform_action=apply
```

---

## If something goes wrong

**A state lease is stuck** after a cancelled run. The runner has no Azure CLI, so
break it from here. Terraform prints the lock ID in the failure message:

```bash
LOCK_ID=...   # from the "Lock Info: ID:" line in the failed run
terraform -chdir=terraform/cluster force-unlock "$LOCK_ID"
```

**State was clobbered.** Blob versioning and 30-day soft delete are on:

```bash
az storage blob list --account-name stplatformprduks02 \
  --container-name infra-homelab-config --include v --auth-mode login -o table
```

Then `az storage blob copy start` the wanted version over the current blob.

**The plan wants to create the VM.** The state did not migrate. Do not apply.
Restore `~/homelab-cluster.tfstate.bak` and redo Stage 2.

**The runner is compromised, or you want it gone.** It is disposable and its
state is in Azure, not on it:

```bash
RUNNER_ID=$(gh api "repos/${REPO}/actions/runners" --jq '.runners[] | select(.name=="lnsvrgha01") | .id')
gh api --method DELETE "repos/${REPO}/actions/runners/${RUNNER_ID}"
terraform -chdir=terraform/runner destroy -var-file="vars/homelab.tfvars"
```

Rebuilding is Stage 5 again; `config.sh --replace` reclaims the runner name.

**Rolling back a stage.** Stages 1, 3 and 4 are plain Git or GitHub state and can
be reverted. Stage 2 is the only one that touches live state, which is why it has
backups and a hard gate. Stage 5 creates one LXC and nothing else.
