output "device_id" {
  description = "Tailscale device ID of the k3s node"
  value       = data.tailscale_device.k8s.id
}

output "key_expiry_disabled" {
  description = "Whether Tailscale key expiry is disabled for the k3s node"
  value       = tailscale_device_key.k8s.key_expiry_disabled
}

output "subnet_routes" {
  description = "Subnet routes enabled for the k3s node"
  value       = tailscale_device_subnet_routes.k8s.routes
}

output "node_tailnet_ipv4" {
  description = "Tailnet IPv4 address of the k3s node"
  value       = local.node_tailnet_ipv4
}

output "lab_split_dns_nameservers" {
  description = "Nameservers resolving lab.skyhaven.ltd for tailnet clients"
  value       = tailscale_dns_split_nameservers.lab.nameservers
}
