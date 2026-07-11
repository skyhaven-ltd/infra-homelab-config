output "windows_vm_id" {
  description = "Proxmox VM ID of the Windows desktop"
  value       = proxmox_virtual_environment_vm.windows_desktop.vm_id
}

output "windows_ip" {
  description = "Reserved LAN address of the Windows desktop"
  value       = split("/", var.windows_ip)[0]
}

output "windows_hostname" {
  description = "Hostname of the Windows desktop"
  value       = var.windows_hostname
}
