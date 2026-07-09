# Non-secret Phase 0 facts (docs/versions.md). Token is env-only (TF_VAR_proxmox_api_token).

#########################################
# PROXMOX
#########################################
proxmox_host = "100.82.112.92" # lnproxlab01 tailscale IP (proven SSH/API path from WSL)
proxmox_node = "lnproxlab01"
vm_storage   = "local-lvm"
iso_storage  = "local"

#########################################
# NETWORK
#########################################
k8s_vm_ip   = "192.168.1.3/24"
lan_gateway = "192.168.1.1"
bridge      = "vmbr0"

#########################################
# KUBERNETES NODE
#########################################
k8s_memory_mb = 16384

#########################################
# ACCESS
#########################################
ssh_public_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIH/2sxw8l1OAhwW3Yald3xYgnJ9SG+wfgKoHJRSmMALh ops-desktop@lnproxlab01"
