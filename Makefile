TF_CLUSTER   := terraform/cluster
TF_RUNNER    := terraform/runner
TF_TAILSCALE := terraform/tailscale
ANSIBLE_DIR  := ansible

TF_CLUSTER_VARS := vars/homelab.tfvars
TF_RUNNER_VARS  := vars/homelab.tfvars

TF_BACKEND_RG        := rg-platform-prd-uks-01
TF_BACKEND_SA        := stplatformprduks02
TF_BACKEND_CONTAINER := infra-homelab-config
TF_BACKEND_SUB       := cefc8742-e1dd-4b24-90a9-07e3d3c80d88

define tf_init
	terraform -chdir=$(1) init -input=false \
	  -backend-config="resource_group_name=$(TF_BACKEND_RG)" \
	  -backend-config="storage_account_name=$(TF_BACKEND_SA)" \
	  -backend-config="container_name=$(TF_BACKEND_CONTAINER)" \
	  -backend-config="key=$(2)" \
	  -backend-config="subscription_id=$(TF_BACKEND_SUB)"
endef

.PHONY: infra-init infra-plan infra-apply configure bookbuddy-configure tailscale-apply bootstrap seal \
        runner-init runner-plan runner-apply runner-configure

infra-init:
	$(call tf_init,$(TF_CLUSTER),cluster.tfstate)

infra-plan: infra-init
	terraform -chdir=$(TF_CLUSTER) plan -var-file="$(TF_CLUSTER_VARS)"

infra-apply: infra-init
	terraform -chdir=$(TF_CLUSTER) apply -var-file="$(TF_CLUSTER_VARS)"

configure:
	cd $(ANSIBLE_DIR) && ansible-galaxy install -r requirements.yml && \
	ansible-playbook -i inventory/hosts.yml site.yml

bookbuddy-configure:
	cd $(ANSIBLE_DIR) && ansible-galaxy install -r requirements.yml && \
	ansible-playbook -i inventory/hosts.yml site.yml --tags bookbuddy_worker


runner-init:
	$(call tf_init,$(TF_RUNNER),runner.tfstate)

runner-plan: runner-init
	terraform -chdir=$(TF_RUNNER) plan -var-file="$(TF_RUNNER_VARS)"

runner-apply: runner-init
	terraform -chdir=$(TF_RUNNER) apply -var-file="$(TF_RUNNER_VARS)"

runner-configure:
	cd $(ANSIBLE_DIR) && ansible-galaxy install -r requirements.yml && \
	ansible-playbook -i inventory/runner.yml site.yml --tags gha_runner

tailscale-apply:
	$(call tf_init,$(TF_TAILSCALE),tailscale.tfstate)
	terraform -chdir=$(TF_TAILSCALE) apply

bootstrap:
	cd $(ANSIBLE_DIR) && ansible-playbook -i inventory/hosts.yml site.yml --tags argocd

seal:
	kubeseal --controller-namespace sealed-secrets --format yaml < $(FILE) > $(OUT)
