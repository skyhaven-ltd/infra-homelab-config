# infra-homelab-config

Monorepo for the Sky Haven homelab, provisioning and configuring a single-node k3s cluster (`lnsvrk8s01`) end to end. Terraform creates the Proxmox VM, Ansible configures the OS and installs k3s plus Argo CD, and Argo CD then syncs the `kubernetes/` manifests (self-hosted media, DNS, and utility apps) via GitOps. `make` is the entrypoint for the plan/apply, configure/bootstrap, and secret-sealing steps.
