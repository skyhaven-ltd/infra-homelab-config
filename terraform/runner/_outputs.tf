output "runner_vm_id" {
  description = "Proxmox guest ID of the runner container"
  value       = proxmox_virtual_environment_container.runner.vm_id
}

output "runner_ip" {
  description = "LAN address of the runner container, without the CIDR suffix"
  value       = split("/", var.runner_ip)[0]
}

output "runner_hostname" {
  description = "Hostname of the runner container"
  value       = var.runner_hostname
}
