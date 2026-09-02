# Terraria

Vanilla Terraria 1.4.5.8 server for the `Aura_Anonymous_Master` world. The
server is exposed on TCP port 7777 and is intended to be reached through the
k3s node's Tailscale address. Do not configure a router port forward.

## First deployment

The server automatically creates a medium-sized Master Mode world on its first
start. `AUTOCREATE=2` selects the medium world size and `DIFFICULTY=2` selects
Master Mode. Check it with:

```bash
kubectl -n terraria rollout status deployment/terraria
kubectl -n terraria logs deployment/terraria
```

Players choose **Multiplayer**, **Join via IP**, then enter the k3s node's
Tailscale name or `100.x.y.z` address and port `7777`.

The PVC is stored with the other local-path volumes and is included in the
nightly appdata backup. Save before intentionally stopping or restarting it:

```bash
kubectl -n terraria exec deployment/terraria -- inject save
```
