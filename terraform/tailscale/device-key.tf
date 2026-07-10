
resource "tailscale_device_key" "k8s" {
  device_id           = data.tailscale_device.k8s.id
  key_expiry_disabled = true
}
