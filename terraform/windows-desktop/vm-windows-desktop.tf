resource "proxmox_virtual_environment_vm" "windows_desktop" {
  name        = var.windows_hostname
  description = "Windows 11 Codex desktop managed by Terraform"
  node_name   = var.proxmox_node
  vm_id       = var.windows_vm_id
  on_boot     = true
  started     = true
  bios        = "ovmf"
  machine     = "pc-q35-9.0"

  cpu {
    cores = var.windows_cores
    type  = "host"
  }

  memory {
    dedicated = var.windows_memory_mb
    floating  = var.windows_balloon_mb
  }

  efi_disk {
    datastore_id      = var.vm_storage
    file_format       = "raw"
    type              = "4m"
    pre_enrolled_keys = true
  }

  tpm_state {
    datastore_id = var.vm_storage
    version      = "v2.0"
  }

  disk {
    datastore_id = var.vm_storage
    interface    = "sata0"
    size         = var.windows_disk_gb
    discard      = "on"
    file_format  = "raw"
    ssd          = true
  }

  cdrom {
    file_id   = var.windows_iso_file_id
    interface = "ide0"
  }

  network_device {
    bridge = var.bridge
    model  = "e1000e"
  }

  operating_system {
    type = "win11"
  }

  vga {
    type   = "std"
    memory = 64
  }
}
