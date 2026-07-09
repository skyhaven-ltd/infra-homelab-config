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
    enabled = true # qemu-guest-agent installed by Ansible
  }

  # OS disk — booted from the downloaded Ubuntu cloud image
  disk {
    datastore_id = var.vm_storage
    interface    = "scsi0"
    size         = 40
    file_id      = proxmox_download_file.ubuntu_noble.id
    discard      = "on"
  }

  # appdata disk — all Kubernetes PV data (local-path). 60 GB per Blocker 1 (§0.3).
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

  serial_device {} # cloud images want a serial console

  initialization {
    datastore_id = var.vm_storage

    ip_config {
      ipv4 {
        address = var.k8s_vm_ip
        gateway = var.lan_gateway
      }
    }

    dns {
      servers = ["1.1.1.1", "8.8.8.8"] # static; NEVER the cluster's own pi-hole (§1.12)
    }

    user_account {
      username = "ops"
      keys     = [var.ssh_public_key]
    }
  }

  lifecycle {
    ignore_changes = [disk[2]] # media disk attached out-of-band in Phase 9 as scsi2
  }
}
