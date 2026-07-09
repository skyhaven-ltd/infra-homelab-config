# Written to its own inventory file rather than hosts.yml, which terraform/cluster
# owns — two roots writing one file would race and clobber. site.yml selects on the
# `gha_runner` group, so plays skip cleanly when the other inventory is used.
resource "local_file" "runner_inventory" {
  filename        = "${path.module}/../../ansible/inventory/runner.yml"
  file_permission = "0640"

  content = yamlencode({
    gha_runner = {
      hosts = {
        # LXC templates ship no unprivileged ops user; the key above lands on root.
        (var.runner_hostname) = {
          ansible_host = split("/", var.runner_ip)[0]
          ansible_user = "root"
        }
      }
    }
  })
}
