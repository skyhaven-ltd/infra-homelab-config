resource "proxmox_virtual_environment_container" "runner" {
  node_name     = var.proxmox_node
  vm_id         = var.runner_vm_id
  description   = "GitHub Actions self-hosted runner (managed by Terraform)"
  started       = true
  start_on_boot = true

  unprivileged = true

  cpu {
    cores = var.runner_cores
  }

  memory {
    dedicated = var.runner_memory_mb
    swap      = var.runner_swap_mb
  }

  disk {
    datastore_id = var.container_storage
    size         = var.runner_disk_gb
  }

  features {
    nesting = false
  }

  initialization {
    hostname = var.runner_hostname

    ip_config {
      ipv4 {
        address = var.runner_ip
        gateway = var.lan_gateway
      }
    }

    dns {
      servers = ["1.1.1.1", "8.8.8.8"]
    }

    user_account {
      keys = [var.ssh_public_key]
    }
  }

  network_interface {
    name   = "eth0"
    bridge = var.bridge
  }

  operating_system {
    template_file_id = proxmox_download_file.ubuntu_lxc.id
    type             = "ubuntu"
  }
}
