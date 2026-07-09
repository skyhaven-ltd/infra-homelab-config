provider "proxmox" {
  endpoint  = "https://${var.proxmox_host}:8006/"
  api_token = var.proxmox_api_token # via TF_VAR_proxmox_api_token env var — never in Git
  insecure  = true                  # self-signed PVE cert on a LAN/tailnet host

  ssh {
    agent    = true # id_ed25519_proxmox must be loaded in ssh-agent at apply time
    username = "root"
  }
}
