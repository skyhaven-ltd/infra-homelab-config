terraform {
  required_version = ">= 1.9.0"

  # Partial configuration — resource group, storage account, container and the
  # per-root state key are supplied at init time (Makefile locally, the shared
  # terraform-backend-init action in CI). State lives in Azure rather than on
  # the homelab so it survives a cluster or runner rebuild.
  backend "azurerm" {}

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
