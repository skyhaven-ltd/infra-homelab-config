TF_CLUSTER   := terraform/cluster
TF_TAILSCALE := terraform/tailscale
ANSIBLE_DIR  := ansible

TF_CLUSTER_VARS := vars/homelab.tfvars

# Azure remote state. These mirror the values .github/workflows/k8s-deploy.yml
# feeds the shared terraform-backend-init action; change them in both places.
# Every root shares one container and is separated by its own state key.
TF_BACKEND_RG        := rg-platform-prd-uks-01
TF_BACKEND_SA        := stplatformprduks02
TF_BACKEND_CONTAINER := infra-homelab-config
TF_BACKEND_SUB       := cefc8742-e1dd-4b24-90a9-07e3d3c80d88

# tf_init <root-dir> <state-key>. Requires an authenticated `az login`.
define tf_init
	terraform -chdir=$(1) init -input=false \
	  -backend-config="resource_group_name=$(TF_BACKEND_RG)" \
	  -backend-config="storage_account_name=$(TF_BACKEND_SA)" \
	  -backend-config="container_name=$(TF_BACKEND_CONTAINER)" \
	  -backend-config="key=$(2)" \
	  -backend-config="subscription_id=$(TF_BACKEND_SUB)"
endef

.PHONY: infra-init infra-plan infra-apply configure tailscale-apply bootstrap seal

infra-init:
	$(call tf_init,$(TF_CLUSTER),cluster.tfstate)

infra-plan: infra-init
	terraform -chdir=$(TF_CLUSTER) plan -var-file="$(TF_CLUSTER_VARS)"

infra-apply: infra-init
	terraform -chdir=$(TF_CLUSTER) apply -var-file="$(TF_CLUSTER_VARS)"

configure:
	cd $(ANSIBLE_DIR) && ansible-galaxy install -r requirements.yml && \
	ansible-playbook -i inventory/hosts.yml site.yml

# disable Tailscale key expiry for the node (run AFTER configure; node must be joined).
# needs TAILSCALE_API_KEY in env (never in Git) — see terraform/tailscale/_providers.tf.
tailscale-apply:
	$(call tf_init,$(TF_TAILSCALE),tailscale.tfstate)
	terraform -chdir=$(TF_TAILSCALE) apply

# installs Argo CD + app-of-apps root. Public repo => no repo secret needed.
# Idempotent: re-runs are no-ops once argocd-server + root Application exist.
bootstrap:
	cd $(ANSIBLE_DIR) && ansible-playbook -i inventory/hosts.yml site.yml --tags argocd

# usage: make seal FILE=secret.yaml OUT=kubernetes/apps/foo/sealedsecret.yaml
seal:
	kubeseal --controller-namespace sealed-secrets --format yaml < $(FILE) > $(OUT)
