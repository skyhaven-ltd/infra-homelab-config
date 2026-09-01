# Terraria

Vanilla Terraria 1.4.5.8 server for the existing `Aura_Anonymous` world. The
server is exposed on TCP port 7777 and is intended to be reached through the
k3s node's Tailscale address. Do not configure a router port forward.

## First deployment

Close Terraria on the desktop before copying the world. This prevents the
desktop and server from writing different versions of the same world.

After Argo CD creates the pod, it remains in its `world-bootstrap` init
container until the world has been copied into the PVC. From WSL, copy the
world and its two recovery files into that container:

```bash
pod="$(kubectl -n terraria get pod -l app=terraria -o jsonpath='{.items[0].metadata.name}')"
worlds='/mnt/c/Users/LiamG/Documents/My Games/Terraria/Worlds'

kubectl -n terraria exec "$pod" -c world-bootstrap -- mkdir -p /config/Worlds
kubectl -n terraria cp "$worlds/Aura_Anonymous.wld" "$pod:/config/Worlds/Aura_Anonymous.wld" -c world-bootstrap
kubectl -n terraria cp "$worlds/Aura_Anonymous.wld.bak" "$pod:/config/Worlds/Aura_Anonymous.wld.bak" -c world-bootstrap
kubectl -n terraria cp "$worlds/Aura_Anonymous.wld.bak2" "$pod:/config/Worlds/Aura_Anonymous.wld.bak2" -c world-bootstrap
```

Within ten seconds the init container detects the world, fixes ownership, and
starts the server. Check it with:

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
