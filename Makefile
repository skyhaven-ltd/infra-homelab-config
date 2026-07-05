TF_DIR      := terraform
TS_DIR      := terraform/tailscale
ANSIBLE_DIR := ansible

.PHONY: infra-init infra-plan infra-apply configure tailscale-apply bootstrap seal

infra-init:
	cd $(TF_DIR) && terraform init

infra-plan:
	cd $(TF_DIR) && terraform plan

infra-apply:
	cd $(TF_DIR) && terraform apply

configure:
	cd $(ANSIBLE_DIR) && ansible-galaxy install -r requirements.yml && \
	ansible-playbook -i inventory/hosts.yml site.yml

# disable Tailscale key expiry for the node (run AFTER configure; node must be joined).
# needs TAILSCALE_OAUTH_CLIENT_ID / TAILSCALE_OAUTH_CLIENT_SECRET in env (never in Git).
tailscale-apply:
	cd $(TS_DIR) && terraform init && terraform apply

# first run creates the Argo CD repo deploy-key secret:
#   make bootstrap ARGOCD_REPO_KEY=/tmp/argocd-repo-key   (then `shred -u` the key)
# subsequent runs are no-ops (secret already in-cluster) — ARGOCD_REPO_KEY optional.
bootstrap:
	cd $(ANSIBLE_DIR) && ansible-playbook -i inventory/hosts.yml site.yml --tags argocd \
	  $(if $(ARGOCD_REPO_KEY),-e argocd_repo_key_path=$(ARGOCD_REPO_KEY))

# usage: make seal FILE=secret.yaml OUT=kubernetes/apps/foo/sealedsecret.yaml
seal:
	kubeseal --controller-namespace sealed-secrets --format yaml < $(FILE) > $(OUT)
