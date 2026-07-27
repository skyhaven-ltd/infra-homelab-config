# Pi-hole answers for lab.skyhaven.ltd and runs on the k3s node, so it is
# reachable on the node's tailnet address as well as its LAN one. Registering it
# as a split-DNS nameserver does two things: tailnet clients resolve the lab
# domain from anywhere, and enabling MagicDNS on a client no longer costs them
# the lab domain (which is what happens when Tailscale takes over DNS and has
# nowhere to send lab.skyhaven.ltd queries).
resource "tailscale_dns_split_nameservers" "lab" {
  domain      = "lab.skyhaven.ltd"
  nameservers = [local.node_tailnet_ipv4]
}
