# Disable Tailscale key expiry for the k3s node so this infra host never drops
# off the tailnet. Runs as its own root/state AFTER `make configure` (the node
# must be joined before its device key can be managed) — see Makefile `tailscale-apply`.

resource "tailscale_device_key" "k8s" {
  device_id           = data.tailscale_device.k8s.id
  key_expiry_disabled = true
}
