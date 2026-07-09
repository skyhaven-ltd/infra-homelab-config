resource "local_file" "ansible_inventory" {
  filename        = "${path.module}/../../ansible/inventory/hosts.yml"
  file_permission = "0640"

  content = yamlencode({
    k8s = {
      hosts = {
        lnsvrk8s01 = {
          ansible_host = split("/", var.k8s_vm_ip)[0]
          ansible_user = "ops"
        }
      }
    }
  })
}
