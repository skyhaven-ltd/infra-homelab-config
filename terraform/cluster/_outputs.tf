output "k8s_vm_id" {
  description = "Proxmox VM ID of the k3s node"
  value       = proxmox_virtual_environment_vm.k8s.vm_id
}

output "k8s_vm_ip" {
  description = "LAN address of the k3s node, without the CIDR suffix"
  value       = split("/", var.k8s_vm_ip)[0]
}
