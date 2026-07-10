terraform {
  required_version = ">= 1.9"

  backend "azurerm" {}

  required_providers {
    tailscale = {
      source  = "tailscale/tailscale"
      version = "= 0.29.2"
    }
  }
}
