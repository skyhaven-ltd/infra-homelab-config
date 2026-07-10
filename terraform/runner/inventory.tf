resource "local_file" "runner_inventory" {
  filename        = "${path.module}/../../ansible/inventory/runner.yml"
  file_permission = "0640"

  content = yamlencode({
    gha_runner = {
      hosts = {
        (var.runner_hostname) = {
          ansible_host = split("/", var.runner_ip)[0]
          ansible_user = "root"
        }
      }
    }
  })
}
