output "k8s_vm_id" {
  value = proxmox_virtual_environment_vm.k8s.vm_id
}

output "k8s_vm_ip" {
  value = split("/", var.k8s_vm_ip)[0]
}
