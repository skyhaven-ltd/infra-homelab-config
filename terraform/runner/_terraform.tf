terraform {
  required_version = ">= 1.9.0"

  # Partial configuration — see terraform/cluster/_terraform.tf. State key:
  # runner.tfstate.
  #
  # BOOTSTRAP ROOT. Applied by the operator from a workstation inside the
  # network boundary, never by CI: this root provisions the runner that CI
  # executes on, so a pipeline apply would be destroying the machine running it.
  backend "azurerm" {}

  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = "= 0.111.1" # §1.16 pin — matches terraform/cluster
    }
    local = {
      source  = "hashicorp/local"
      version = "~> 2.5"
    }
  }
}
