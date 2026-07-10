resource "proxmox_virtual_environment_vm" "k8s" {
  name        = "lnsvrk8s01"
  description = "k3s single-node cluster (managed by Terraform)"
  node_name   = var.proxmox_node
  vm_id       = 200
  on_boot     = true

  cpu {
    cores = 8
    type  = "host"
  }

  memory {
    dedicated = var.k8s_memory_mb
  }

  agent {
    enabled = true
  }

  disk {
    datastore_id = var.vm_storage
    interface    = "scsi0"
    size         = 40
    file_id      = proxmox_download_file.ubuntu_noble.id
    discard      = "on"
  }

  disk {
    datastore_id = var.vm_storage
    interface    = "scsi1"
    size         = 60
    discard      = "on"
    file_format  = "raw"
  }

  network_device {
    bridge = var.bridge
  }

  operating_system {
    type = "l26"
  }

  serial_device {}

  initialization {
    datastore_id = var.vm_storage

    ip_config {
      ipv4 {
        address = var.k8s_vm_ip
        gateway = var.lan_gateway
      }
    }

    dns {
      servers = ["1.1.1.1", "8.8.8.8"]
    }

    user_account {
      username = "ops"
      keys     = [var.ssh_public_key]
    }
  }

  lifecycle {
    ignore_changes = [disk[2]]
  }
}
