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

variable "container_storage" {
  type        = string
  description = "Datastore ID for the container root disk (local-lvm thin pool)"
}

variable "template_storage" {
  type        = string
  description = "Datastore ID holding the downloaded LXC template"
  default     = "local"
}

variable "lan_gateway" {
  type        = string
  description = "Default gateway for the runner container"
  default     = "192.168.1.1"
}

variable "bridge" {
  type        = string
  description = "Proxmox network bridge the runner attaches to"
  default     = "vmbr0"
}

variable "runner_ip" {
  type        = string
  description = "CIDR address for the runner container (.1 gateway, .2 host, .3 k3s node)"
  default     = "192.168.1.5/24"
}

variable "runner_hostname" {
  type        = string
  description = "Hostname of the runner container, also its Ansible inventory key"
  default     = "lnsvrgha01"
}

variable "runner_vm_id" {
  type        = number
  description = "Proxmox guest ID for the runner container (VM 200 is the k3s node)"
  default     = 300
}

variable "runner_cores" {
  type        = number
  description = "vCPU cores for the runner container"
  default     = 2
}

variable "runner_memory_mb" {
  type        = number
  description = "Dedicated memory for the runner container, in MiB"
  default     = 2048
}

variable "runner_swap_mb" {
  type        = number
  description = "Swap for the runner container, in MiB"
  default     = 512
}

variable "runner_disk_gb" {
  type        = number
  description = "Root disk size for the runner container, in GiB"
  default     = 16
}

variable "ssh_public_key" {
  type        = string
  description = "Public key installed for the container root user (Ansible connects as root)"
}
