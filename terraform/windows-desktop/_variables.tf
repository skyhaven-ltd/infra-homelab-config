variable "proxmox_host" {
  type        = string
  description = "Proxmox API and SSH host"
}

variable "proxmox_api_token" {
  type        = string
  sensitive   = true
  description = "Proxmox API token supplied through TF_VAR_proxmox_api_token"
}

variable "proxmox_node" {
  type        = string
  description = "Proxmox node name"
}

variable "vm_storage" {
  type        = string
  description = "Datastore for VM disks"
}

variable "bridge" {
  type        = string
  description = "Proxmox network bridge"
}

variable "windows_iso_file_id" {
  type        = string
  description = "Proxmox file ID for the Windows 11 installation ISO"
}

variable "windows_hostname" {
  type        = string
  description = "Windows desktop hostname"
}

variable "windows_vm_id" {
  type        = number
  description = "Proxmox VM ID for the Windows desktop"
}

variable "windows_ip" {
  type        = string
  description = "Reserved LAN address for the Windows desktop"
}

variable "windows_cores" {
  type        = number
  description = "vCPU cores for the Windows desktop"
}

variable "windows_memory_mb" {
  type        = number
  description = "Maximum memory for the Windows desktop in MiB"
}

variable "windows_balloon_mb" {
  type        = number
  description = "Minimum balloon memory for the Windows desktop in MiB"
}

variable "windows_disk_gb" {
  type        = number
  description = "System disk size for the Windows desktop in GiB"
}
