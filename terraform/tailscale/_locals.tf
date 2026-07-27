locals {
  # Tailnet addresses cover both IPv4 and IPv6; the split-DNS nameserver and
  # the kubeconfig endpoint both want the v4 one.
  node_tailnet_ipv4 = one([
    for address in data.tailscale_device.k8s.addresses : address
    if !strcontains(address, ":")
  ])
}
