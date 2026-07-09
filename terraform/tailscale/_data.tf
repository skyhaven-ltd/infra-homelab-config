data "tailscale_device" "k8s" {
  hostname = var.node_hostname
}
