# Non-secret facts (docs/versions.md). Token is env-only (TF_VAR_proxmox_api_token).

#########################################
# PROXMOX
#########################################
proxmox_host      = "100.82.112.92" # lnproxlab01 tailscale IP
proxmox_node      = "lnproxlab01"
container_storage = "local-lvm"
template_storage  = "local"

#########################################
# NETWORK
#########################################
runner_ip   = "192.168.1.5/24"
lan_gateway = "192.168.1.1"
bridge      = "vmbr0"

#########################################
# RUNNER CONTAINER
#########################################
runner_hostname  = "lnsvrgha01"
runner_vm_id     = 300
runner_cores     = 2
runner_memory_mb = 2048
runner_swap_mb   = 512
runner_disk_gb   = 16

#########################################
# ACCESS
#########################################
ssh_public_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIH/2sxw8l1OAhwW3Yald3xYgnJ9SG+wfgKoHJRSmMALh ops-desktop@lnproxlab01"
