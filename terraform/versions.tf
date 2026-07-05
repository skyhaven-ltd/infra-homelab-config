terraform {
  required_version = ">= 1.9.0"

  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = "= 0.111.1" # §1.16 pin — latest stable resolved 2026-07-05
    }
    local = {
      source  = "hashicorp/local"
      version = "~> 2.5"
    }
  }
}
