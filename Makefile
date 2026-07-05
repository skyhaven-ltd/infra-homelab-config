TF_DIR      := terraform
ANSIBLE_DIR := ansible

.PHONY: infra-init infra-plan infra-apply configure bootstrap seal

infra-init:
	cd $(TF_DIR) && terraform init

infra-plan:
	cd $(TF_DIR) && terraform plan

infra-apply:
	cd $(TF_DIR) && terraform apply

configure:
	cd $(ANSIBLE_DIR) && ansible-galaxy install -r requirements.yml && \
	ansible-playbook -i inventory/hosts.yml site.yml

bootstrap:
	cd $(ANSIBLE_DIR) && ansible-playbook -i inventory/hosts.yml site.yml --tags argocd

# usage: make seal FILE=secret.yaml OUT=kubernetes/apps/foo/sealedsecret.yaml
seal:
	kubeseal --controller-namespace sealed-secrets --format yaml < $(FILE) > $(OUT)
