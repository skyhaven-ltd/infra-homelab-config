variable "proxmox_host" {
  type        = string
  description = "Proxmox API/SSH host (tailscale IP from Phase 0)"
}

variable "proxmox_api_token" {
  type        = string
  sensitive   = true
  description = "terraform@pve!tf=<uuid> — supplied via TF_VAR_proxmox_api_token"
}

variable "proxmox_node" {
  type        = string
  description = "Proxmox node name"
}

variable "vm_storage" {
  type        = string
  description = "VM disk storage ID (local-lvm thin pool)"
}

variable "iso_storage" {
  type    = string
  default = "local"
}

variable "k8s_vm_ip" {
  type        = string
  default     = "192.168.1.4/24" # becomes .3 at cutover (Phase 11)
  description = "CIDR address for the k3s VM"
}

variable "lan_gateway" {
  type    = string
  default = "192.168.1.1"
}

variable "bridge" {
  type    = string
  default = "vmbr0"
}

variable "k8s_memory_mb" {
  type    = number
  default = 12288 # → 16384 in Phase 12 after old VM decommission
}

variable "ssh_public_key" {
  type        = string
  description = "Public key installed for the VM ops user"
}
