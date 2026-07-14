# infra-homelab-config

Monorepo for the Sky Haven homelab and its personal services. Terraform and Ansible provision the single-node k3s environment, Argo CD syncs the `kubernetes/` workloads, and `services/` contains the application and MCP source deployed around the homelab.
