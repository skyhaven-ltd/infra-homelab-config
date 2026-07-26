resource "tailscale_device_subnet_routes" "k8s" {
  device_id = data.tailscale_device.k8s.id
  routes    = ["192.168.1.0/24"]
}
