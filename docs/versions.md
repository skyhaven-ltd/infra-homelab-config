# Versions & Environment Facts

Per §1.16 of the migration plan: every pinned artifact and every discovered
environment fact is recorded here. Never deploy `:latest`.

## Environment facts (discovered Phase 0, re-verified 2026-07-05)

### Proxmox host `lnproxlab01`

| Fact | Value |
|---|---|
| PVE version | pve-manager/8.3.0 (kernel 6.8.12-4-pve) |
| Node name | `lnproxlab01` |
| CPU | 12 cores (Intel Alder Lake-S, Dell OEM) |
| RAM | 23 GiB total (`free -g`) — confirms `<34 GiB` branch → shrink old VM to 6 GiB before apply |
| LAN IP | 192.168.1.2 |
| Tailscale IP | 100.82.112.92 |
| Gateway | 192.168.1.1 (via `vmbr0`) |
| Bridge | `vmbr0` |

### VMs

| VMID | Name | Notes |
|---|---|---|
| 100 | `lnsvrlab01` | `OLD_VMID`. 8 cores, 20000 MB RAM. `scsi0` local-lvm 60G (thin, ~30G used). `scsi1` = `data:100/vm-100-disk-0.raw` 930G = `MEDIA_DISK_SLOT`. `hostpci0: 0000:00:02` (Intel UHD 770 iGPU → Blocker 2). |
| 200 | `lnsvrk8s01` | New k3s VM. Provisioned (Phase 3). k3s `v1.36.2+k3s1` Ready (Phase 4). LAN `192.168.1.4`, Tailscale `100.90.207.55`. |

### Storage (physical disks)

| Disk | Size | Role | Free |
|---|---|---|---|
| `nvme0n1` | 238.5 GB | Proxmox system disk (VG `pve`) | VG `VFree` = 16 GB |
| `sda` | 931.5 GB | Media library, ext4 at `/data`, moves to VM 200 in Phase 9 | 0 GB — 100 % full (912G/916G) |

### Proxmox storages (`pvesm status`)

| Storage | Type | Total | Avail | Notes |
|---|---|---|---|---|
| `local` | dir | 32.7 GB | 18.3 GB | iso/templates. `iso_storage`. Too small for weekly vzdump (Open Q7 open). |
| `local-lvm` | lvmthin | 186.5 GB (pool 177.84 GB) | 154 GB thin-logical (17.16 % used) | VM disk storage = `vm_storage`. Physical pool ceiling 177.84 GB. |
| `data` | dir | 959.5 GB | 0 GB (99.58 % full) | the 930G media disk mounted `/data`. Moves to VM 200. |

### VG `pve` / LVM detail

```
PV /dev/nvme0n1p3   VG pve   237.47G, VFree 16.00G
LV pve/root   32G ext4  /
LV pve/swap    8G swap
LV pve/data   177.84G thinpool (backs local-lvm), 17.16% used
LV pve/vm-100-disk-0  60G thin, 50.85% used (~30G actual)
```

## Resolved sizing decisions

- **New VM disks (Blocker 1 resolved 2026-07-05):** `scsi0` 40 GB + `scsi1` 60 GB
  on `local-lvm` = 100 GB nominal < 154 GB thin avail, no overcommit.
  (§1.2's 150 GB appdata is superseded.)
- **Old VM RAM:** ✅ DONE 2026-07-05 — `qm set 100 --memory 6144` + stop/start.
  Verified: VM 100 back at `.3`, Pi-hole DNS resolving, all app ports open
  (53/8989/7878/9696/8080/13378/8384/32400/8090/8081). Host now 15 GiB available
  (was 1 GiB) — new VM's 12 GiB co-existence RAM fits (6+12+~3 ≈ 21/23 GiB).

## Phase 0 — COMPLETE (2026-07-05)

Discovery + access + RAM shrink all done. Blockers 1 & 2 resolved (see plan §0.2).
Remaining before `terraform apply`: none hard — Open Q7 (vzdump target) affects
backup layer 2 only, decide before Phase 1's off-box/backup steps rely on it.
Workstation DNS temporarily pointed at 192.168.1.1 to survive Pi-hole outages
(revert to DHCP/.3 post-migration).

## Open items blocking `terraform apply`

- **Blocker 2 — iGPU passthrough:** decide Option A (leave on old VM until cutover)
  vs Option B (move now). Adds a `hostpci` block to `vm-k8s.tf`.
- **Open Q7 — vzdump target:** `local` 18 GB free is too small; `data` is full.
  No PBS. Decide target (likely tied to any future added disk).

## Phase 1 — COMPLETE (2026-07-05)

Backups on `lnsvrlab01` at `/mnt/media/backups/pre-k8s-2026-07-05` (842 MB; media disk
has 96 GB free inside the VM — the host-side 100% is just the thick 930G raw image):

- `media-compose.yaml`, `stockalert/{docker-compose.yml,.env,config.yaml,products.txt}`,
  `learning-review/docker-compose.yml`
- `appdata.tar.gz` (881 MB, 9 apps), `learning-data.tar.gz`, `stockalert-data.tar.gz` — all verified
- `ip-addr.txt`, `ip-route.txt`, `netplan/`, `tailscale-status.txt`

**⚠ learning-review `.env` was deleted from disk** but `env_file: - .env` still references it.
All values survive only in the running container's env. Reconstructed to
`learning-review/.env` (19 app keys incl. secrets `APP_SECRET_KEY`, `WORKER_TOKEN`,
`APP_PASSWORD`) by filtering image-baked vars out of `docker inspect`. **This file is the
authoritative source for the Phase 7 learning-review Secret/ConfigMap.** Confirmed vault
genuinely unmounted (only `learning_data`→/data mount) — migrate without vault per Q8.

**Rollback point (VM-level):** full `qm snapshot`/`vzdump` NOT possible — media disk
(930G `.raw` on `data` dir-storage) isn't snapshot-capable and is too big for the 18 GB
`local` free. Instead took a thin LVM snapshot of the OS disk only:
`vm-100-disk-0-prek8s` (origin `pve/vm-100-disk-0`). Media excluded by necessity + design
(re-acquirable, moves to new VM anyway). Restore: `qm stop 100` →
`lvconvert --merge pve/vm-100-disk-0-prek8s` → `qm start 100`. Discard when migration done:
`lvremove pve/vm-100-disk-0-prek8s`.

### SSH access to old VM (set up 2026-07-05)

Key `id_ed25519_proxmox.pub` installed on `lnsvrlab01` for user `lgoodchild-a`
(passwordless sudo confirmed). WSL `~/.ssh/config` alias `old` / `lnsvrlab01` →
`192.168.1.3`. Bootstrap needed `PubkeyAuthentication=no` to avoid MaxAuthTries before
password.

## Phase 3 — COMPLETE (2026-07-05)

VM 200 `lnsvrk8s01` provisioned by Terraform (`bpg/proxmox = 0.111.1`). `terraform@pve`
user + token created (token in WSL `~/.tf_proxmox_token`, 0600, never in Git). VM live:
Ubuntu 24.04.4, sda 40G / sdb 60G, IP 192.168.1.4, `ops` SSH OK, state clean. VM 100
untouched. **Gotcha:** bpg blocks ~3-4 min per plan/apply waiting on the (not-yet-installed)
QEMU guest agent — not a hang; run applies in background. Next: Phase 4 — Ansible.

## Phase 2 — COMPLETE (2026-07-05)

Monorepo scaffold on branch `major/kubernetes`: full §2 directory tree (`.gitkeep`
placeholders in empty dirs), `compose.yaml` → `compose/compose.yaml` (`git mv`;
systemd units use host paths so running stack is untouched), `.gitignore` +
`Makefile` written, README updated. Tooling install was a no-op (WSL toolchain
already verified below). Next: Phase 3 — Proxmox API token + Terraform VM provision.

## Pinned artifact versions

Resolved at execution time per §1.16. Remaining rows filled as later phases land.

| Artifact | Pin | Resolved | Notes |
|---|---|---|---|
| `bpg/proxmox` Terraform provider | `= 0.111.1` | 2026-07-05 | latest stable (GitHub releases). `versions.tf`. |
| `hashicorp/local` provider | `~> 2.5` | 2026-07-05 | inventory rendering only |
| `tailscale/tailscale` provider | `= 0.29.2` | 2026-07-05 | latest stable. `terraform/tailscale/` (separate root/state) — disables node key expiry. OAuth client creds via env. |
| Ubuntu cloud image | `noble/current` (24.04.4 LTS) | 2026-07-05 | `image.tf`; downloaded to `local` storage |
| k3s | `v1.36.2+k3s1` | 2026-07-05 | latest stable (update.k3s.io stable channel). `group_vars/k8s.yml`. Plan §1.16 rule supersedes the plan's v1.32.x guess. |
| Argo CD | _TBD Phase 5_ | | |
| ingress-nginx / cert-manager / sealed-secrets charts | _TBD Phase 5_ | | |
| App/container image tags | _TBD Phase 6+_ | | |

## Workstation toolchain (WSL2 Ubuntu-24.04, verified 2026-07-05)

| Tool | Version |
|---|---|
| Terraform | v1.15.7 |
| kubectl | v1.36.x (bumped 2026-07-05 from v1.32.13 to match k3s v1.36.2 server; ±1 skew window) |
| Helm | v3.21.2 |
| kubeseal | 0.38.4 |
| Ansible | core 2.16.3 |
| gh | 2.96.0 |
