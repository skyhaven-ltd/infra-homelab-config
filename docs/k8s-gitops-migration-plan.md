# Homelab Kubernetes + GitOps Migration Plan

**Status:** ✅ **Phases 0–12 COMPLETE (2026-07-05). Phase 10 (Home Assistant) SKIPPED — operator doesn't use HA. Cutover DONE — `192.168.1.3` = the cluster; old VM 100 destroyed (14-day soak SKIPPED by operator directive); cluster grown to 16 GiB; Phase 13.4 reboot drill ✅ PASSED (appdata by-id disk fix validated, 15/15 Argo apps Healthy after cold reboot). See §0.3 Phase 11/12 — DONE. Remaining = rest of Phase 13 ops-hardening: restic first-run+verify, vzdump schedule (blocked on Open Q7 target), off-box crown jewels (Q6 age-encrypted repo), disaster-recovery doc. Plex claimed (`aa63d10e…`, server `lnsvrk8s01`). Watch for the disk-letter-swap landmine (§0.3 Phase 11) and the Argo-branch = `major/kubernetes` (not `main`).** Every app the operator uses is live on the cluster at `192.168.1.4`; all 15 Argo apps Synced/Healthy. Media disk (930G) moved VM100→VM200, all 7 media apps migrated byte-identical with data verified intact (§0.3 **Phase 9 — DONE**). Read the **▶ Resuming at Phase 11** block in §0.3 first — it has the pre-cutover gates, the IaC IP-swap sequence, and the repo-specific gotchas. Custom-app + media images pinned by digest in `docs/versions.md`. VM 200 `lnsvrk8s01` Terraform-managed; k3s `v1.36.2+k3s1`; Tailscale `100.90.207.55`; kubeconfig `ansible/lnsvrk8s01-kubeconfig`; SSH `ops@192.168.1.4` (pass `-i ~/.ssh/id_ed25519_proxmox`, no alias). **Open Q7 (vzdump target) still open** — backup *layer 2* only, non-blocking. Everything a fresh agent needs — access, aliases, discovered facts — is in §0.2 + §0.3 Progress Log.
**Audience:** An LLM coding agent with shell/file access to the operator's Windows desktop (workstation for this migration — see §0.2, not `lnsvrlab01` as originally assumed), SSH reachability to the Proxmox host (`lnproxlab01`), and push access to the `skyhaven-ltd` GitHub org. Read this document top-to-bottom once, then §0.2 Handoff Notes, then execute phases in order. Every architectural decision has already been made; where a value must be *discovered* (not decided), Phase 0 tells you how to discover it — most of Phase 0 is already done, see §0.2.

---

## 0. Environment Inventory (verified 2026-07-03)

These facts were gathered directly from the live environment. Re-verify anything marked *(discover)* in Phase 0 before relying on it.

### Hosts

| Host | Role | Details |
|---|---|---|
| `lnproxlab01` | Proxmox VE host | Tailscale IP `100.82.112.92`, LAN IP `192.168.1.2`. Node name `lnproxlab01`, PVE 8.3.0. 12 cores (Intel Alder Lake-S, Dell). RAM 23 GiB total. Storage: see §0.2 — **capacity blocker found** |
| `lnsvrlab01` | Current Docker workload VM (KVM guest on the Proxmox host) | Ubuntu 24.04.3 LTS, 8 vCPU, 20 GiB RAM, LAN `192.168.1.3/24` on `ens18`, Tailscale `100.98.14.63`. Disks: `sda` 60 GB (LVM; root LV only 29 GB, **77 % full**), `sdb` 930 GB ext4 mounted `/mnt/media` |
| `lnsvrk8s01` | **New** Kubernetes VM (created by this plan) | See VM sizing decision, §1.2 |

- LAN: `192.168.1.0/24`, gateway assumed `192.168.1.1` *(discover in Phase 0)*.
- Tailscale tailnet with MagicDNS active. `lnsvrlab01` advertises subnet route `192.168.1.0/24` (used for remote Plex without Plex Pass). **Known landmine:** MagicDNS (`100.100.100.100`) SERVFAILs public lookups when container runtimes forward to it — this previously broke containers on `lnsvrlab01` and is why the stockalert compose pins `dns: 1.1.1.1`. The new node avoids this by design (§1.13).
- Pi-hole at `192.168.1.3` is the LAN DNS server (host-network container).

### Current workloads (13 containers)

**Stack A — media/infra stack.** Compose file: `/srv/containers/media/compose.yaml` (tracked in repo `infra-homelab-config` as `compose.yaml`). App data under `/srv/containers/media/appdata/<app>`:

| App | Image | Network/Ports | State (size) | Notes |
|---|---|---|---|---|
| pihole | `pihole/pihole:latest` | host network, `NET_ADMIN` | 320 MB | LAN DNS — special cutover handling |
| plex | `lscr.io/linuxserver/plex:latest` | host network | 829 MB config + `/mnt/media/library` (71 GB) | PUID/PGID 1000 |
| sonarr | `lscr.io/linuxserver/sonarr:latest` | 8989 | 159 MB + `/mnt/media→/data` | |
| radarr | `lscr.io/linuxserver/radarr:latest` | 7878 | 76 MB + `/mnt/media→/data` | |
| prowlarr | `lscr.io/linuxserver/prowlarr:latest` | 9696 | 88 MB | |
| qbittorrent | `lscr.io/linuxserver/qbittorrent:latest` | 8080 web, 6881 tcp/udp | 16 MB + `/mnt/media→/data` | |
| audiobookshelf | `advplyr/audiobookshelf:latest` | 13378→80 | 1.1 MB + `/mnt/media→/data` | |
| syncthing | `lscr.io/linuxserver/syncthing:latest` | 8384 web, 22000 tcp/udp, 21027 udp | 112 KB + `/mnt/media→/data` | |
| homeassistant | `ghcr.io/home-assistant/home-assistant:stable` | host network, **privileged** | 26 MB | |

**Stack B — StockAlert monitor.** Compose: `~/repos/app-stockalert-monitor/docker-compose.yml` (repo `skyhaven-ltd/app-stockalert-monitor`, image built locally):

| App | Image | Ports | State | Notes |
|---|---|---|---|---|
| stock-checker | local build | none | `./data` (SQLite), `config.yaml` + `products.txt` ro binds, `.env` (2 secrets) | dns pinned 1.1.1.1/8.8.8.8 |
| flaresolverr | `ghcr.io/flaresolverr/flaresolverr:latest` | internal only | none | solves bot challenges |
| ntfy | `binwiederhier/ntfy:latest` | 8090→80 | `./ntfy/cache`, `./ntfy/etc` | **`NTFY_BASE_URL=http://192.168.1.3:8090`** — phones subscribe to this exact URL; IP must survive migration (§1.14) |

**Stack C — Learning Review app.** Compose: `~/repos/app-learning-review/docker-compose.yml` (repo `skyhaven-ltd/app-learning-review`, image built locally):

| App | Ports | State | Notes |
|---|---|---|---|
| app | 8081→8080 | named volume `app-learning-review_learning_data` at `/var/lib/docker/volumes/app-learning-review_learning_data/_data` | health endpoint `GET /health`. Compose declares an optional read-only Obsidian-vault bind, but the *running* container has no vault mount — migrate without it (see Open Question 8) |

**`/mnt/media` layout:** `library/` 71 GB, `downloads/` 690 GB, `backups/` 12 GB (existing backup target — reuse it).

**Existing repos (GitHub org `skyhaven-ltd`):** `infra-homelab-config` (becomes the monorepo), `app-learning-review`, `app-stockalert-monitor`, plus unrelated app repos.

---

## 0.2 Handoff Notes — executed 2026-07-05 (read this before doing anything else)

The operator ran Phase 0 discovery and initial access setup interactively before handing this off. Below is everything that changed vs. the original plan, everything discovered, and — critically — **two new blockers that need a decision before Phase 3 (Terraform apply)**.

### Workstation change (affects every `[old]` step in §3)

The plan originally assumed `lnsvrlab01` was the ops workstation. **It is not.** The operator's Windows 11 desktop is the workstation for this entire migration. Ansible has no native Windows control-node support, so the actual toolchain lives in **WSL2, distro `Ubuntu-24.04`**, installed and running on that desktop. Everywhere the phased plan says `[old]`, read it as "the WSL2 Ubuntu-24.04 environment on the operator's desktop" unless the step is explicitly about the Docker host's filesystem/containers themselves (e.g. Phase 1 backup steps, which still run on `lnsvrlab01` because that's where the data is).

Installed and verified working inside WSL2 `Ubuntu-24.04`:

| Tool | Version |
|---|---|
| Terraform | v1.15.7 |
| kubectl | v1.32.13 |
| Helm | v3.21.2 |
| kubeseal | 0.38.4 |
| Ansible | core 2.16.3 |
| gh | 2.96.0 |
| sshpass | 1.09 (used once to bootstrap the key below, not needed again) |

WSL user: `lgoodchild-a`, passwordless sudo configured (`/etc/sudoers.d/lgoodchild-a`) so future automation doesn't need password prompts.

### Proxmox SSH access — resolved (Open Question 1)

Generated `~/.ssh/id_ed25519_proxmox` (ed25519) in WSL, installed the public key into `lnproxlab01`'s `root/.ssh/authorized_keys` (it already had two other pre-existing keys — untouched, not overwritten). Verified key-only, non-interactive SSH works over **both** paths:

```
ssh -o BatchMode=yes -i ~/.ssh/id_ed25519_proxmox root@192.168.1.2      # LAN
ssh -o BatchMode=yes -i ~/.ssh/id_ed25519_proxmox root@100.82.112.92    # Tailscale
```

An SSH config alias exists in WSL (`~/.ssh/config`): `Host lnproxlab01 pve` → resolves via the Tailscale IP with the right identity file, so `ssh pve` works directly.

**Lesson learned, worth knowing:** the Proxmox web GUI's `>_ Shell` console (xterm.js/noVNC) mangles pastes of long single lines — it injects a real newline at the visual wrap point, silently corrupting multi-line commands. Don't paste long strings (like SSH public keys) into that console. Use `ssh-copy-id` / `scp` / piped `ssh` from a real terminal instead, which transfers content programmatically rather than relying on clipboard+paste.

### Phase 0 discovery — executed, full results

```
Node: lnproxlab01, PVE 8.3.0, kernel 6.8.12-4-pve
CPU: 12 cores (nproc), Intel Alder Lake-S (Dell OEM)
RAM: 23 GiB total (free -g) — confirms the <34 GiB branch in §1.2/Open Q2
Gateway: 192.168.1.1 via vmbr0 (confirmed, matches assumption)
Bridge: vmbr0 (confirmed)

VMs: only VMID 100 = lnsvrlab01 (OLD_VMID = 100)
  qm config 100:
    cores: 8, memory: 20000 (MB), cpu: x86-64-v2-AES
    scsi0: local-lvm:vm-100-disk-0, 60G (thin; actually ~30GB used, 50.85%)
    scsi1: data:100/vm-100-disk-0.raw, 930G   <- MEDIA_DISK_SLOT = scsi1
    net0: virtio, bridge=vmbr0
    hostpci0: 0000:00:02   <- UNDOCUMENTED, see Blocker 2 below

Storage (pvesm status):
  local        dir      32.7 GB total,  18.3 GB avail  (iso/templates only)
  local-lvm    lvmthin  186.5 GB total, 154.5 GB "avail" per pvesm — MISLEADING, see Blocker 1
  data         dir      959.5 GB total, 0 GB avail (99.58% full) — this is the 930G media disk, backed by
               a dedicated physical disk (/dev/sda, 931.5G), mounted at /data on the host

Underlying LVM (nvme0n1, 238.5 GB physical disk):
  VG pve: 237.47G total, VFree 16.00G   <- the REAL free space, not what pvesm reports
  LV pve/data (thinpool, backs "local-lvm" storage): 177.84G size, 17.16% used
  LV pve/root: 32G, LV pve/swap: 8G
```

### BLOCKER 1 — RESOLVED 2026-07-05 (VM disks resized to 40 GB + 60 GB)

**Resolution.** Re-verified live storage over SSH (`lsblk`, `pvs`, `vgs`, `lvs`, `pvesm status`, `df -h`). Confirmed two physical disks:

| Disk | Size | Role | Free |
|---|---|---|---|
| `nvme0n1` | 238.5 GB | Proxmox system disk — holds VG `pve` | 16 GB unallocated in VG (`VFree`) |
| `sda` | 931.5 GB | Media library, ext4 at `/data` (moves to new VM in Phase 9) | **0 GB — 100 % full (912G/916G)** |

The 1 TB `sda` cannot host the OS disk (already full, and it *moves* wholesale to the new VM). The 240 GB `nvme0n1` is fully carved: 32G root + 8G swap + 177.84G `local-lvm` thin pool + 16G VG free.

The original blocker conflated **VG physical free (16 GB)** with **thin-pool logical avail (154 GB)** — bpg/proxmox creates VM disks *on the `local-lvm` thin pool*, not from VG free space, so the OS disk was never the problem. The oversized **150 GB appdata disk** was: 40+150 = 190 GB nominal > 154 GB thin avail, forcing overcommit of a 177.84 GB physical pool (old VM already writes ~30 GB of it), which risks filling the pool and corrupting every volume in it.

**Decision (operator, 2026-07-05):** shrink `scsi1` (appdata) from 150 GB → **60 GB**. New layout `scsi0` 40 GB + `scsi1` 60 GB = **100 GB nominal < 154 GB thin avail — no overcommit**. App state is single-digit GB today; grow the thin appdata disk later (trivial) after Phase 12 decommission frees the old VM's ~30 GB. **No new hardware.** `terraform/vm-k8s.tf` and `variables.tf` use 60 GB for scsi1; §1.2's table is superseded on this one value.

Note: this does *not* resolve Open Q7 (vzdump target) — `local` has only 18 GB free, still too small for weekly whole-VM backups. Decide the backup target separately before relying on backup layer 2.

<details><summary>Original blocker text (kept for history)</summary>

**BLOCKER 1 — NVMe storage will not fit the planned VM disks (needs a decision)**

§1.2 sizes the new VM at `scsi0` 40 GB + `scsi1` 150 GB = **190 GB combined**, intended for `local-lvm`. Reality: the `local-lvm` thin pool is only 177.84 GB total, and the **actual unallocated space in the backing volume group is 16 GB** (`vgs` → VFree). `pvesm status`'s "Available: 154 GB" for a thinly-provisioned pool is *logical* headroom assuming average block efficiency, not physical disk space — it is not trustworthy for a sizing decision here. Decommissioning the old VM's 60 GB thin disk (Phase 12) only reclaims its ~30 GB actually-written blocks, bringing real free space to roughly 46 GB — still far short of 190 GB.

The other physical disk (`data`, 930 GB SATA, backing the existing media disk) has **0 GB available** — it's already 99.58% full with the current media library, and that disk is slated to *move* (not be shared) to the new VM in Phase 9 anyway.

**This means, as currently scoped, the new VM's disk layout in §1.2/`terraform/vm-k8s.tf` cannot be provisioned on this host's existing storage.** Options, none yet chosen — flag to the operator for a decision before writing `terraform/vm-k8s.tf`:
1. Operator adds a new physical disk (SSD/NVMe) to the Proxmox host and a new Proxmox storage is created on it for the new VM's disks.
2. Shrink the new VM's disk plan to fit within realistic free space (~16 GB now / ~46 GB post-decommission) — but the whole reason §1.2 sized 40 GB for the OS disk was that the *old* VM's 29 GB root disk was already 77% full, so a small disk here risks repeating that problem quickly.
3. Free space by shrinking the old VM's OS disk before provisioning the new one (limited headroom — old OS disk only uses ~30 GB of its 60 GB already).

Do not proceed to Phase 3 (`terraform apply`) until this is resolved with the operator.

</details>

### BLOCKER 2 — RESOLVED 2026-07-05 (Option A: iGPU stays on old VM until cutover)

**Decision (operator, 2026-07-05): Option A.** The iGPU (`hostpci0: 0000:00:02`, Intel UHD 770) stays on `lnsvrlab01` for the whole soak period — production Plex keeps HW transcode. New-cluster Plex runs software transcode until cutover. At Phase 11/12, the old VM is shut down and the `hostpci` moves to VM 200. Consequences: `terraform/vm-k8s.tf` gets **no `hostpci` block now** (added at cutover); the Plex manifest's GPU device-plugin/resource wiring is deferred to Phase 12. Lower risk — production stack keeps HW transcode until it's retired.

<details><summary>Original blocker text (kept for history)</summary>

**BLOCKER 2 — undocumented iGPU PCI passthrough on the old VM (needs a decision)**

`qm config 100` shows `hostpci0: 0000:00:02`, confirmed via `lspci -s 00:02.0 -k` to be the host's integrated GPU (`Intel UHD Graphics 770`, currently bound to `vfio-pci`). This is almost certainly powering Plex hardware transcoding and is **not mentioned anywhere in the original plan** (§1.2 sizing, Phase 9/10 media-disk-move steps, or the Plex app migration checklist in §4).

A PCI device can only be passed through to one *running* VM at a time, which matters for the plan's whole co-existence strategy (old + new VM running simultaneously across Phases 3–11). Needs a decision, not yet made:
- **Option A (lower risk):** leave the iGPU passthrough on `lnsvrlab01` for the entire soak period; the new cluster's Plex runs without hardware transcode (software transcode, or transcoding simply not exercised) until final cutover (Phase 11/12), at which point the old VM is shut down and the iGPU passthrough moves to `lnsvrk8s01`'s VM config.
- **Option B:** move the iGPU to the new VM immediately — old VM's Plex loses HW transcode for the whole migration, which is riskier given it's the production stack until cutover.

Whichever is chosen, `terraform/vm-k8s.tf` needs a `hostpci` block added (currently absent from the plan's example in §3 Phase 3), and the Ansible/Plex app manifest (kubernetes/apps/plex) needs the device plugin / resource request wired up for GPU access in-cluster (not otherwise covered by the plan's k3s role).

</details>

### Open Questions (§6) — operator's answers, 2026-07-05

1. **SSH access:** resolved above — workstation is the desktop (WSL2), not `lnsvrlab01`. Proxmox LAN IP is `192.168.1.2`.
2. **Proxmox host capacity:** discovered above. RAM confirms the <34 GiB branch — **approve shrinking `lnsvrlab01` to 6 GiB (`qm set 100 --memory 6144`) plus a reboot before Phase 3**, per §1.2's own mitigation. Not yet executed — do this first in Phase 0 continuation. Storage capacity is Blocker 1 above, more severe than the plan anticipated.
3. **Public domain:** none. Proceed with the internal self-signed CA per §1.9's default path.
4. **GHCR visibility:** make `app-learning-review` / `app-stockalert-monitor` packages **public**. This removes the need for a `read:packages` PAT / `imagePullSecret` in Phase 7 — simplify those steps accordingly (drop the `ghcr-pull` secret and its reference in the Deployment specs).
5. **Private keys in Git:** operator asked whether generated keys (SSH key above, Tailscale auth key) can be stored in the GitHub repo. **No** — private keys never go in Git, even a private repo. They stay local only: the Proxmox SSH key lives in WSL's `~/.ssh` (outside the repo); the Tailscale auth key is passed via the `TS_AUTHKEY` env var at `make configure` time (already how §3 Phase 4 documents it) and otherwise not persisted to disk in the repo tree.
6. **Off-box backup destination (crown jewels — sealed-secrets key, k3s token, tfstate, restic password):** operator asked whether GitHub (Actions) Secrets could serve this purpose, org- or repo-level. **They can't, for this use case** — GitHub Actions Secrets are write-only: injectable into a workflow run, never retrievable afterward via API or UI. Since §1.8 deliberately runs no CI for infra, there's no workflow to consume them, and they can't be pulled back down for a manual disaster-recovery restore. Recommended instead (already one of the plan's own listed options): a **private repo in the `skyhaven-ltd` org**, holding age-encrypted backup files of the crown jewels — `git clone` + `age -d` is the restore path. Repo-level is sufficient for a single operator; no need for org-level secrets machinery.
7. **Proxmox Backup Server:** none exists. Single host, no dedicated backup server — vzdump targets local Proxmox storage. **Unresolved which storage**, given Blocker 1: `local` only has 18 GB free (too small for weekly VM backups) and `data` has 0 GB free. This needs to be settled alongside Blocker 1 — likely the same new-disk decision would also provide the vzdump target.
8. **learning-review Obsidian vault:** confirmed genuinely unused. Migrate without it, as the plan already defaults to.
9. **Home Assistant hardware:** no USB/Zigbee/Bluetooth passthrough currently in use — confirmed no HA-related hardware integrations to carry over. (Note: this is unrelated to Blocker 2's iGPU passthrough, which is for Plex, not Home Assistant.)
10. **Plex claim:** acknowledged — proceed assuming the existing claimed server identity carries over via the config PV migration, per the plan's expectation.

### Additional operator directives (not part of the numbered Open Questions)

- Downtime during migration is acceptable — no requirement to keep every app up throughout.
- During the Pi-hole cutover window (Phase 11), the operator will temporarily point this desktop's own DNS at `192.168.1.1` (the router) so it keeps outbound internet while Pi-hole is being rebuilt in-cluster. This is a workstation-local, temporary change — not something to script into the Ansible/Terraform, just a heads-up for timing that phase.
- **Hard requirement, repeated for emphasis:** container configuration must be byte-identical post-migration. This is already §1.11's design goal (hostPath mirrors compose binds exactly, PV data is cold-copied not recreated) — treat any deviation from existing app config/behavior as a regression, not an acceptable simplification.

---

## 0.3 Progress Log — Phases 0 & 1 executed 2026-07-05 (READ THIS FIRST if resuming)

A fresh agent starting here has **already-completed Phases 0 and 1**. Begin work at **Phase 2**. Everything below is the actual end-state.

### Access & tooling (all from WSL2 `Ubuntu-24.04` on the operator's desktop)

- **Proxmox:** `ssh pve` (alias in WSL `~/.ssh/config` → `100.82.112.92`, user `root`, key `~/.ssh/id_ed25519_proxmox`). Works non-interactively.
- **Old VM `lnsvrlab01`:** `ssh old` (alias → `192.168.1.3`, user `lgoodchild-a`, **passwordless sudo**, same key). Set up 2026-07-05.
- **Nested-quoting landmine:** running commands as `wsl -d Ubuntu-24.04 bash -c "ssh pve '…'"` mangles `$VAR`, `$(...)`, and redirections across the three shell layers (they silently become empty / syntax-error). **Always** write a local `.sh` and pipe it: `ssh pve 'bash -s' < script.sh` (or `ssh old 'bash -s' < script.sh`). Vars then expand on the target only.
- `gh` authenticated for `skyhaven-ltd` (verify with `gh auth status`).

### Phase 0 — DONE

- Discovery re-verified live (see §0.2 + `docs/versions.md` "Environment facts"). Node `lnproxlab01`, PVE 8.3.0, 12 cores, **23 GiB RAM**, gateway `192.168.1.1`, bridge `vmbr0`, `OLD_VMID=100`, media disk = `scsi1` on `data` storage.
- **Storage truth (Blocker 1 resolved):** NVMe `nvme0n1` 238.5 GB = Proxmox system disk (VG `pve`: 32G root + 8G swap + 177.84G `local-lvm` thinpool + 16G VFree). SATA `sda` 931.5 GB = media, ext4 `/data`, 100% full at host level (thick 930G raw), **96 GB free inside the VM**. `local-lvm` thinpool has 154 GB thin-logical avail (old VM writes ~30 GB). **New VM disks = 40 GB + 60 GB = 100 GB nominal, no overcommit.** No new hardware.
- **iGPU (Blocker 2 resolved, Option A):** `hostpci0: 0000:00:02` (Intel UHD 770) **stays on VM 100** until cutover. `terraform/vm-k8s.tf` gets **no `hostpci` block** now; Plex runs software transcode on the new cluster until Phase 12.
- **Old VM RAM shrunk 20 GiB → 6 GiB** (`qm set 100 --memory 6144` + stop/start). Verified: all 13 containers back up, Pi-hole DNS resolving, ports 53/8989/7878/9696/8080/13378/8384/32400/8090/8081 open. Host now **15 GiB available** — new VM's 12 GiB co-existence RAM fits.
- **Workstation DNS:** desktop was resolving via Pi-hole (`192.168.1.3`); temporarily repointed to router `192.168.1.1` (interfaces `Ethernet 2`, `WiFi 2`) so it survives Pi-hole outages during migration. **Revert to DHCP/.3 post-migration.** (Proxmox uses Tailscale MagicDNS, not Pi-hole — untouched.)

### Phase 1 — DONE

- Backups at `/mnt/media/backups/pre-k8s-2026-07-05` (842 MB), all archives verified: `media-compose.yaml`, `stockalert/*`, `learning-review/*`, `appdata.tar.gz` (881 MB, 9 apps), `learning-data.tar.gz`, `stockalert-data.tar.gz`, network identity files.
- **⚠ learning-review `.env` was deleted from disk** (compose still has `env_file: - .env`). Values survive only in the running container. **Reconstructed** to `…/learning-review/.env` (19 app keys incl. secrets `APP_SECRET_KEY`, `WORKER_TOKEN`, `APP_PASSWORD`) via `docker inspect` minus image-baked vars. **This is the authoritative source for the Phase 7 learning-review Secret/ConfigMap.** Vault confirmed unmounted (only `learning_data`→/data) — migrate without it (Q8).
- **Rollback point:** full `qm snapshot`/`vzdump` impossible (media disk `.raw` on dir-storage isn't snapshot-capable; too big for 18 GB `local`). Took a **thin LVM snapshot of the OS disk only**: `vm-100-disk-0-prek8s` (origin `pve/vm-100-disk-0`). Restore: `qm stop 100` → `lvconvert --merge pve/vm-100-disk-0-prek8s` → `qm start 100`. Remove when migration done: `lvremove pve/vm-100-disk-0-prek8s`.

### Phase 2 — DONE (2026-07-05)

Monorepo scaffold created on branch `major/kubernetes` (the migration branch — the plan's
literal `k8s-migration` name was superseded; work continues on `major/kubernetes`):

- Full §2 directory tree created (`terraform/`, `ansible/{group_vars,inventory,roles/{base,tailscale,k3s,argocd_bootstrap}}`,
  `kubernetes/{bootstrap/argocd,argocd-apps,infrastructure/{ingress-nginx,cert-manager,cert-issuers,sealed-secrets},apps/{pihole,plex,sonarr,radarr,prowlarr,qbittorrent,audiobookshelf,syncthing,homeassistant,learning-review,stockalert}}`,
  `compose/`). Empty dirs hold `.gitkeep` placeholders (removed as real files land in later phases).
- `compose.yaml` → `compose/compose.yaml` via `git mv`. **Running stack unaffected** — the `systemd/`
  units reference host absolute paths (`/srv/containers/media/…`), not the repo compose path, so no
  systemd edit or host re-link was needed. README pointer updated to the new path + a layout table.
- `.gitignore` extended (tfstate, `.terraform/`, `ansible/inventory/hosts.yml`, `*.key`, `*-kubeconfig`;
  kept legacy `appdata/`). `Makefile` written with `infra-init/plan/apply`, `configure`, `bootstrap`, `seal`
  targets (tab-indented, verified).
- Tooling install (Phase 2 step 4) is a **no-op** — WSL2 toolchain already installed & verified (§0.3, versions.md).

### Phase 3 — DONE (2026-07-05)

VM 200 `lnsvrk8s01` provisioned via Terraform (`bpg/proxmox = 0.111.1`, pin in versions.md):

- **Proxmox identity:** `terraform@pve` user + `Administrator` ACL on `/` + API token `terraform@pve!tf`
  created (`pveum`). **Token stored only in WSL `~/.tf_proxmox_token` (0600) — never in Git.** Consumed
  via `TF_VAR_proxmox_api_token`. Provider SSH uses `ssh-agent` + `id_ed25519_proxmox`.
- **Terraform config** written under `terraform/`: `versions.tf` (pins), `providers.tf`, `variables.tf`,
  `terraform.tfvars` (non-secret Phase 0 facts; `proxmox_host = 100.82.112.92` tailscale), `image.tf`
  (Ubuntu noble, uses `proxmox_download_file` — the non-deprecated resource), `vm-k8s.tf` (scsi0 40G +
  scsi1 60G, no `hostpci` per Blocker 2 Option A, `ignore_changes = [disk[2]]` for the Phase 9 media
  disk), `inventory.tf` (renders `ansible/inventory/hosts.yml`), `outputs.tf`. `iothread` removed from
  both disks (bpg warns it needs a virtio-scsi-single controller; dropped rather than churn the disk).
- **VM live:** Ubuntu 24.04.4, `sda` 40G (root, cloud-init `done`), `sdb` 60G (appdata, unmounted —
  Ansible mounts it Phase 4), IP `192.168.1.4/24`, static DNS `1.1.1.1`/`8.8.8.8`, `ops` user SSH via
  `id_ed25519_proxmox`. `on_boot = true`. VM 100 (production) untouched.
- **⚠ Landmine hit + recorded — bpg guest-agent wait:** with `agent { enabled = true }` but
  qemu-guest-agent not yet installed (that's Phase 4), every `terraform plan`/`apply` **blocks ~3–4 min**
  on "waiting for the QEMU agent to publish network interfaces" then continues with a warning. **This is
  not a hang** — let it finish; run applies in the background. This also explains a mid-Phase-3 incident:
  the first `apply` was interrupted during that wait *after* Proxmox had already created+started the VM,
  leaving VM 200 running but absent from tfstate. `terraform import` also stalls on the same agent wait.
  Resolution: `qm destroy 200 --purge` then a clean background `apply` (state == reality). Stale host key
  for `.4` was cleared with `ssh-keygen -R 192.168.1.4`.
- **`make infra-init/plan/apply` all run from WSL** via ssh-agent; `terraform` operates on the repo over
  `/mnt/c` (slow but fine). Helper `tf-run.sh` (loads token + agent) lives in the session scratchpad, not the repo.

### Phase 4 — DONE (2026-07-05)

Ansible configured VM 200 → base OS, Tailscale, single-node k3s. Playbook `failed=0`. All §4 verifications pass.

- **k3s pinned `v1.36.2+k3s1`** (§1.16 latest stable via `update.k3s.io` stable channel — plan's v1.32.x guess superseded; recorded `docs/versions.md`). Node `lnsvrk8s01` **Ready**, INTERNAL-IP `192.168.1.4`, containerd 2.3.2-k3s2. Bundled **Traefik disabled**; coredns + local-path-provisioner + metrics-server all Running.
- **DNS test passed** (`kubectl run dns-test … nslookup github.com` → resolved via CoreDNS 10.43.0.10) — proves the §1.13 `--accept-dns=false` fix; no MagicDNS SERVFAIL.
- **Tailscale joined**: node = **`100.90.207.55`** (`--accept-dns=false`, `--hostname=lnsvrk8s01`), tailnet alongside `pve` (`.92`) + `old` (`.63`).
- **Tailscale key expiry disabled via IaC** (operator directive): new **separate** Terraform root `terraform/tailscale/` (`tailscale/tailscale = 0.29.2`) with a `tailscale_device_key { key_expiry_disabled = true }` on the node (looked up by hostname). Separate state because the device must be *joined* (Phase 4) before its key can be managed — running it in the main `terraform/` root would break a clean rebuild (VM apply precedes join). Make target **`tailscale-apply`**, run after `configure`. Creds = a tailnet **OAuth client** (`TAILSCALE_OAUTH_CLIENT_ID`/`_SECRET`, `devices:core` write scope), env-only, never in Git.
- **appdata**: `/dev/sdb` ext4 mounted `/srv/appdata` (59G, `defaults,noatime`); `default-local-storage-path=/srv/appdata/local-path` (dir created on first PVC).
- **kubeconfig** fetched to `ansible/lnsvrk8s01-kubeconfig` (gitignored `*-kubeconfig`), server rewritten `127.0.0.1`→`192.168.1.4`. **k3s token** `/var/lib/rancher/k3s/server/token` is the layer-3 backup artifact (kubeconfig itself is regenerable).
- **kubectl bumped `v1.32.13 → v1.36.2`** in WSL (operator-approved) to sit inside the server's ±1 skew window.

**Three role bugs found + fixed during execution (roles are now idempotent — re-runnable):**
1. **Tailscale `creates:` guard false-skipped `tailscale up`** — installing the pkg starts `tailscaled` and writes `tailscaled.state` *before* login, so the guard saw the file and skipped join (node sat `Logged out`). **Fix:** gate on real backend state (`tailscale status` rc, run `up` only when `rc != 0`).
2. **kubeconfig fetch dest was `{{ playbook_dir }}/../`** (repo root) but §4's sed targeted `ansible/`. **Fix:** dest → `{{ playbook_dir }}/lnsvrk8s01-kubeconfig`.
3. **`ansible.cfg` ignored** because `/mnt/c` is world-writable (ansible security check). **Fix (execution-time, not a repo change):** export `ANSIBLE_CONFIG=<abs path>` + `--private-key ~/.ssh/id_ed25519_proxmox` (no ssh-config block exists for `ops@192.168.1.4`). The Makefile `configure` target still works *inside* WSL only if `ANSIBLE_CONFIG` is set — see mechanics note below.

Also: `make configure` runs `site.yml` with **no** `--skip-tags` — Phase 4 was run with `--tags` / `--skip-tags argocd` manually. Before Phase 5, either add the `argocd` role or keep skipping it.

### ▶ Resuming at Phase 4 — execution mechanics for a fresh agent (READ THIS)

The workstation is a **Windows 11 desktop running Claude Code**; the real toolchain
(terraform/ansible/kubectl/ssh + the `pve`/`old` aliases + the Proxmox token) lives in
**WSL2 `Ubuntu-24.04`**. Every live command runs through WSL:

```
wsl.exe -d Ubuntu-24.04 -- bash -lc '<command>'
```

Repo path inside WSL: `/mnt/c/Local Files/Repositories/Sky Haven/infra-homelab-config`
(quote it — spaces). Terraform operates over `/mnt/c` (slow but fine).

**Quoting landmine (hit twice — do not relearn):** never inline non-trivial bash
(`$VAR`, `$(...)`, redirects, escaped quotes) inside `bash -lc '...'` — the
cmd→wsl→bash layers silently mangle it. **Write the script to a file and run it:**
`wsl.exe -d Ubuntu-24.04 -- bash -lc 'bash "/mnt/c/.../script.sh"'`. For remote
commands, pipe: `ssh pve 'bash -s' < script.sh`. Note `wsl.exe -- bash /mnt/c/x.sh`
(script path as a bare arg) gets path-rewritten by Git Bash — always wrap it in the
`bash -lc 'bash "…"'` form so the `/mnt/c` path stays literal.

**SSH targets (all key `~/.ssh/id_ed25519_proxmox`, non-interactive):** `ssh pve`
(Proxmox 100.82.112.92), `ssh old` (VM 100, `192.168.1.3`, passwordless sudo), and the
new node `ssh ops@192.168.1.4`. If the new VM is ever recreated, clear its stale key:
`ssh-keygen -R 192.168.1.4`.

**Re-running Terraform (only if needed — Phase 4 uses Ansible, not TF):** the provider
needs both the token env var and a loaded ssh-agent, in one shell:
```bash
export TF_VAR_proxmox_api_token="$(cat ~/.tf_proxmox_token)"   # 0600, WSL-only, never in Git
eval "$(ssh-agent -s)"; ssh-add ~/.ssh/id_ed25519_proxmox
cd "/mnt/c/Local Files/Repositories/Sky Haven/infra-homelab-config/terraform" && terraform plan
```
Expect the **~3–4 min bpg guest-agent wait** on every plan/apply until Phase 4 installs
qemu-guest-agent — run applies in the background, don't kill them.

**Phase 4 prerequisites (get these before `make configure`):**
1. **`TS_AUTHKEY`** — a reusable Tailscale auth key from the admin console. Passed inline
   only: `TS_AUTHKEY=tskey-... make configure`. **Never** written to disk/Git.
2. **k3s version pin** (§1.16) — resolve current stable `vX.Y.Z+k3s1`, write to
   `ansible/group_vars/k8s.yml` **and** `docs/versions.md`.

**Phase 4 facts already confirmed:** appdata disk = `/dev/sdb` (60G, present, unmounted) →
`appdata_mount: /srv/appdata`; `node_ip: 192.168.1.4`; `ansible_user: ops`. The
`ansible/` roles are empty `.gitkeep` placeholders — author `ansible.cfg`, `site.yml`,
`requirements.yml` (`community.general`, `ansible.posix`), `group_vars/k8s.yml`, and the
`base`/`tailscale`/`k3s` role tasks per the **Phase 4** section below (full task YAML is
there). The generated `ansible/inventory/hosts.yml` already exists (Terraform, gitignored).

**Run Phase 4 with `--skip-tags argocd`** (the `argocd_bootstrap` role is Phase 5 and will
fail if run now): `TS_AUTHKEY=... ansible-playbook -i inventory/hosts.yml site.yml --skip-tags argocd`
(or add the skip to the Makefile target while Phase 5 is pending).

### ▶ Resuming at Phase 5 — Argo CD bootstrap: handoff for a fresh agent (READ THIS)

Phases 0–4 are done. k3s node is **Ready**. Phase 5 = install Argo CD, wire the app-of-apps root, and land the four platform Applications (ingress-nginx, cert-manager, sealed-secrets, cert-issuers). Full spec is **§ Phase 5** below — this block is the execution wrapper.

**Execution mechanics are unchanged from Phase 4** — reuse the "▶ Resuming at Phase 4" block above verbatim for: the `wsl.exe -d Ubuntu-24.04 -- bash -lc '…'` pattern, the **write-a-script-and-run-it** quoting rule (never inline `$VAR`/`$(...)`/redirects), and the SSH targets (`ssh pve` / `ssh old` / `ssh ops@192.168.1.4`). Repo path in WSL: `/mnt/c/Local Files/Repositories/Sky Haven/infra-homelab-config`.

**kubectl access (already working, persists on disk across a context clear):**
- `KUBECONFIG=<repo>/ansible/lnsvrk8s01-kubeconfig` (gitignored; server already rewritten to `192.168.1.4`). Regenerable any time via the k3s role's fetch task.
- WSL `kubectl` is **v1.36.2** (matches server). `/mnt/c` is world-writable so remember `export ANSIBLE_CONFIG=<repo>/ansible/ansible.cfg` for any `ansible-playbook` run.
- `gh` in WSL is authenticated for `skyhaven-ltd` (needed for Step 2 `gh repo deploy-key add`).

**⚠ BRANCH LANDMINE — resolve before Argo starts syncing.** Every Phase 5 `Application` (and the root-app) sets **`targetRevision: main`**, but all manifests live on branch **`major/kubernetes`** and are **not yet merged to `main`**. If you `kubectl apply` the root-app while `main` lacks the manifests, Argo syncs an empty/old tree. Pick one before Step 3:
  1. **Merge `major/kubernetes` → `main` first** (the plan's phase-boundary rule), then apply root-app as written. Cleanest.
  2. **Temporarily set `targetRevision: major/kubernetes`** on the root-app + all child Applications during migration; flip to `main` at merge. More churn.
  Recommend #1 — commit Phase 4/5 work, merge, then bootstrap Argo against `main`.

**Pins to resolve at execution time (§1.16) and record in `docs/versions.md`:** Argo CD (`install.yaml` tag, expect `v2.14.x`/`v3.x` — check argoproj/argo-cd releases), `ingress-nginx` chart, `cert-manager` chart, `sealed-secrets` chart. Never `:latest`.

**The `argocd_bootstrap` role is still an empty `.gitkeep`.** `site.yml` already lists it (Phase 4 ran with `--skip-tags argocd`). Author it to wrap Steps 1–3 with `kubectl get`-guards so `make configure` / `make bootstrap` (`--tags argocd`) is idempotent for a clean rebuild.

**Order of play:** Step 1 (namespace + kustomization) → Step 2 (repo deploy key, the ONE manual secret — `shred` it after) → Step 3 (root-app, mind the branch landmine) → Step 4 (four platform Apps, sync-waves -2/-1) → Step 5 (custody: back up sealed-secrets key + k3s token + root CA to `/srv/appdata/key-backups/`; export CA public cert to `docs/`). Verify per §Phase 5 (Argo UI, all Synced/Healthy, `curl -k https://192.168.1.4` → nginx 404, `clusterissuer homelab-ca` Ready, GitOps loop test).

### Phase 5 — DONE (2026-07-05)

Argo CD bootstrapped; app-of-apps live; four platform Apps **Synced/Healthy**. Playbook `failed=0`.

- **Argo CD `v3.4.4`** installed via `argocd_bootstrap` role (kustomize → pinned `install.yaml`). **Server-side apply required** — bundled `applicationsets.argoproj.io` CRD exceeds the 256 KB client-side last-applied annotation limit; role uses `kubectl apply --server-side --force-conflicts` (also makes it idempotent, no "already installed" guard).
- **Public-repo GitOps (design change):** `infra-homelab-config` is **public**, so Argo pulls anonymously over **HTTPS** — the deploy-key "one manual secret" was **dropped entirely** (also the org disables deploy keys: `HTTP 422 Deploy keys are disabled`). All `repoURL`s are `https://github.com/...`; SealedSecrets ciphertext is safe to publish. **Phase 5 now has ZERO manual secrets.**
- **Branch:** all Applications `targetRevision: major/kubernetes` (operator directive — no merge to `main`). Argo reads **origin**, so every manifest change must be **committed AND pushed** to `origin/major/kubernetes` before Argo sees it. Flip to `main` if/when merged.
- **Pins (docs/versions.md):** Argo CD `v3.4.4`, ingress-nginx chart `4.15.1`, cert-manager `v1.20.3`, sealed-secrets chart `2.19.1`. **⚠ sealed-secrets chart repo moved** `bitnami-labs.github.io` → `bitnami.github.io/sealed-secrets` (old URL 404s — first sync failed on it; fixed + pushed).
- **Verified:** `curl -k https://192.168.1.4` → **HTTP 404** (ingress-nginx LB `EXTERNAL-IP 192.168.1.4`, klipper binds 80/443); `clusterissuer homelab-ca` + `selfsigned` **Ready=True**; sealed-secrets-controller **Running**. GitOps loop proven live (sealed-secrets repo fix auto-synced on push).
- **Key custody** (`/srv/appdata/key-backups/`, 600 root on node): `sealed-secrets-key.yaml`, `k3s-token`, `root-ca.yaml`. Phase 9 adds a `/mnt/media/backups` copy; Phase 13 sends off-box.
- **CA public cert** exported → `docs/homelab-ca.crt` (self-signed root `CN=homelab-root-ca`, valid to 2036; install on devices to trust `*.lab.home.arpa`).
- **Argo admin UI:** `kubectl -n argocd port-forward svc/argocd-server 8443:443`; initial password `kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d`.

### Phase 6 — DONE (2026-07-05)

Pi-hole pilot **live on the cluster and verified**; old Pi-hole (`.3`) still serving the LAN untouched.

- **Manifests** `kubernetes/apps/pihole/` (pvc, deployment, service, ingress, kustomization) + `argocd-apps/app-pihole.yaml`. Argo **Synced/Healthy**.
- **Byte-identical (§1.11):** image pinned by **digest** (`pihole/pihole@sha256:91dc91d…`, = old Core v6.3). Env only `TZ` (as compose). **No sealed secret** — the web/API password rides along in the seeded `pihole.toml` (pwhash); old password still works. **Deviation from plan** (plan sealed a new password): dropped because the old container set no `WEBPASSWORD` env and byte-identical is the hard requirement. Sealed-secrets gets exercised in Phase 7/8 (stockalert/learning-review) where it's genuinely needed.
- **One required adaptation:** `FTLCONF_dns_listeningMode=all` (pod is behind a Service; old was host-network with `LOCAL`). v6 writes it into the toml; verified effective `= ALL`.
- **Data seed:** rsync old→WSL→new PV `/srv/appdata/local-path/<pvc>_pihole_pihole-etc`, autosync disabled during seed. **Excluded the 317M `pihole-FTL.db`** (query-log history = disposable telemetry, not config) — seed was ~5 MB. gravity.db, adlists, dnsmasq.conf, hosts, TLS all carried over.
- **Verified:** `dig @192.168.1.4 doubleclick.net` → **0.0.0.0** (blocked via LB); `github.com` → real IP; **83,809** gravity domains seeded; ingress + **homelab-ca** TLS serving the UI (HTTP 302 → /admin/login, issuer `homelab-root-ca`).
- **⚠ Landmine fixed (DNS) — now IaC.** The node's `systemd-resolved` **stub (127.0.0.53) was dead** ("connection refused"), which broke containerd image pulls → local-path PVC provisioning hung ("helper pod image can't be pulled"). Fix hardened into `roles/base`: pin `DNS=1.1.1.1 8.8.8.8`, `DNSStubListener=no`, symlink `/etc/resolv.conf` → `/run/systemd/resolve/resolv.conf` (uplink, bypass stub). Applied + converged; stub off, resolves clean. **Any stateful app is blocked until this is in place** — it's in the base role now, so a rebuild is covered.
- **Seed procedure (reused by every stateful app):** patch Argo app `syncPolicy.automated=null` → `scale deploy --replicas=0` → resolve PV via `kubectl get pv <name> -o jsonpath='{.spec.local.path}'` → rsync (`--rsync-path="sudo rsync"`, stage through WSL — no direct old↔new SSH) → scale to 1 → restore `automated`.
- **Not done (operator soak step):** point ONE test client at `192.168.1.4` for a day. **Do NOT** change router DHCP. `pihole.lab.home.arpa` has no DNS record yet (add in OLD Pi-hole UI → `192.168.1.4` to browse the new UI before cutover).

### Phase 7 — DONE (2026-07-05, one operator UI action outstanding)

CI images for the two custom apps build + push to GHCR on every push to `main`.

- **Workflow** `.github/workflows/publish.yml` (identical) added to `skyhaven-ltd/app-learning-review` and `app-stockalert-monitor`. Both repos have a `main` **ruleset requiring PRs** — direct push `GH013` rejected; landed via `gh pr create` + `gh pr merge --squash --admin --delete-branch` (PRs #7 / #2). Both `publish` runs **success** (33s / 1m41s).
- **Image refs recorded** (`docs/versions.md`) — tag = commit SHA:
  - `ghcr.io/skyhaven-ltd/app-learning-review:9424c0b64d9f85d9107e8d3226c35311d0cc9d8a`
  - `ghcr.io/skyhaven-ltd/app-stockalert-monitor:f54ba2e7f2bd7a5ad13c914067b802975677e97f`
- **Simplified per Open Q4:** packages **public** → the plan's Step 2 `ghcr-pull` imagePullSecret + `read:packages` PAT is **dropped**. Phase 8 has **no** GHCR sealed secret.
- **✅ Both GHCR packages PUBLIC** (operator, 2026-07-05 — required lifting the org package policy to allow public containers first, then the per-package flip; the toggle was initially "disabled by organization administrators"). Anonymous pull verified `http=200`. No imagePullSecret anywhere — Phase 8 GHCR-secretless. **Pins upgraded to digest** (§1.11): learning-review `@sha256:ce2944ad…812bb1`, stockalert `@sha256:0c78c241…881d1d` (full digests in `docs/versions.md`).
- **Rollback:** delete the two `publish.yml` files (no runtime impact).

### Phase 8 — DONE (2026-07-05)

Both custom apps live on the cluster, verified, old stacks down (old ntfy kept up).

- **Manifests** `kubernetes/apps/{learning-review,stockalert}/` + Argo Applications `argocd-apps/app-{learning-review,stockalert}.yaml`. Both **Synced/Healthy**. Root-app auto-discovered them on push.
- **learning-review:** Deployment (GHCR digest `@sha256:ce2944ad…`), PVC `learning-data` 2Gi at `/data`, Service 8080, Ingress `learning.lab.home.arpa` (homelab-ca TLS). Env from **SealedSecret `learning-review-env`** (19 keys, sealed from the Phase-1-reconstructed `.env`). **App binds 8080 despite `APP_PORT=8081`** (confirmed in logs — `APP_PORT` only affected the compose host-publish port), so containerPort/probes on 8080 as planned; `.env` kept byte-identical. No vault mount (Q8). `/health` → **HTTP 200** via ingress with seeded data.
- **stockalert:** three Deployments in one dir.
  - **ntfy** (digest `@sha256:cfbbb1ba…`, `args:[serve]`): split into **ClusterIP `ntfy:80`** (in-cluster, keeps `NTFY_SERVER=http://ntfy:80` byte-identical) **+ LoadBalancer `ntfy-lb` 8090→80** for phones. *Two ports on one LB would make klipper bind node :80 and clash with ingress-nginx* — hence the split. `/etc/ntfy` was empty on the old host → pure-env config, no server.yml. PVC `ntfy-cache` 1Gi.
  - **flaresolverr** (digest `@sha256:139dfee1…`): ClusterIP `flaresolverr:8191`, mem limit 2Gi.
  - **stock-checker** (GHCR digest `@sha256:0c78c241…`): `config.yaml`+`products.txt` via **configMapGenerator** (subPath ro mounts at `/app/`), env from **SealedSecret `stockalert-env`** (5 keys), PVC `stockalert-data` 1Gi at `/app/data`. **No value edits** — compose service names `ntfy`/`flaresolverr` map 1:1 to same-namespace Services, so in-cluster DNS resolves them byte-identically. No `dns:` pin (CoreDNS proven Phase 4).
- **Byte-identical images (§1.11):** ntfy + flaresolverr pinned to the **exact running `:latest` digests** on the old host (recorded `docs/versions.md`). GHCR apps pinned to Phase-7 digests. **No imagePullSecret** (packages public, Q4).
- **Data seed (Phase 6 recipe):** pause Argo autosync → scale 0 → `docker compose stop` old source (consistent SQLite) → clear PV → tar old→WSL→node (`ops` passwordless sudo, no direct old↔new SSH) → scale 1 → restore autosync. Seeded `learning.db` (1.44M) and stockalert `stock.db`+wal+shm+logs+html.
- **Verified end-to-end:** stock-checker ran a full 23-product cycle (currys/ao/argos/johnlewis/meaco), **FlareSolverr round-trips exercised** (ao.com 200 via flaresolverr; argos/meaco challenge pages = identical to prod), scheduler armed at 300s. A **real restock notification** ("Currys Restock! DELONGHI Pinguino EX100 £949.00", priority 5) was delivered by the in-cluster stock-checker through `ntfy:80` and polled back from `ntfy-lb`. Test publish via LB (`.4:8090`) and in-cluster (`ntfy:80`) both HTTP 200.
- **Old stacks down:** old `learning-review` + `stockalert` compose `down`; **old ntfy brought back up** (`.3:8090` → 200) so phones keep notifications until Phase 11 cutover. Media stack (Stack A, 9 containers + old pihole) untouched.
- **Rollback:** delete the Application(s); `docker compose up -d` old stacks. Old data unchanged + Phase-1 backups intact.

**Operator follow-ups (non-blocking):**
- Add `learning.lab.home.arpa` → `192.168.1.4` A record in the **old** Pi-hole (and it's already seeded in the new one) to browse the new UI before cutover.
- (Optional pre-cutover) subscribe a phone to `http://192.168.1.4:8090/uk-aircon-2a486b394641` to confirm phone push from the new ntfy; unsubscribe after.
- **Workflow change:** `products.txt` edits are now Git commits to the monorepo (configMapGenerator → rollout), not live file edits.

### Phase 9 — DONE (2026-07-05)

Media disk physically moved VM100→VM200 and all 7 media apps live on the cluster, data verified intact. Old media stack down (restart disabled); pihole/HA/ntfy on old VM still up until Phase 10/11.

- **Manifests** `kubernetes/apps/{plex,sonarr,radarr,prowlarr,qbittorrent,audiobookshelf,syncthing}/` + Argo Apps. All 7 **Synced/Healthy**; 15/15 Argo apps green. Byte-identical (§1.11): each image pinned to the **old container's exact running `:latest` digest** (recorded `docs/versions.md`); env/ports/container-paths mirror `compose/compose.yaml` 1:1.
- **Deviation from plan (correct, not a regression):** Step 2's literal `docker compose down` would kill pihole+HA (same compose file, not yet migrated). Followed §4 instead — stopped **only the 7 media services**, left pihole/HA/ntfy running. Also **media mounts kept `rw`** (compose is rw; byte-identical) not the plan table's `ro` for plex/abs.
- **Disk move:** `qm move-disk 100 scsi1 --target-vmid 200 --target-disk scsi2` — same-storage reassign (fast, no copy). Now `scsi2: data:200/vm-200-disk-0.raw,size=930G`. Mounted on node **by UUID `bc0c5059…`** (device letter unstable) `defaults,noatime,nofail` — folded into `roles/base` + `group_vars/k8s.yml` (`media_mount`/`media_fs_uuid`, **no mkfs**). `terraform/vm-k8s.tf` keeps `ignore_changes = [disk[2]]` — the media disk is a pet, deliberately outside TF's destroy/recreate lifecycle (can't data-preservingly adopt a populated foreign volume anyway).
- **⚠ Landmine — VM100 reboot re-armed the media containers** (`restart: unless-stopped` fired on boot) against an empty `/mnt/media`. Node seeds were already copied (pre-reboot) so unaffected; fixed with `docker update --restart=no` + stop on the 7 (the §4 step-8 action, early).
- **⚠ Landmine — Argo root-app fights a live `automated: null` patch.** Pausing a child app for seeding doesn't stick because root re-applies the child's Application spec (automated enabled in Git) then selfHeal rescales. **Must pause the ROOT app first**, then children, then scale 0 (confirm zero pods) before seeding — else you seed under a live pod (SQLite corruption risk). Re-seeded all 6 cleanly at zero pods after discovering this.
- **Data seed (Phase 6 recipe, corrected):** appdata (~1.2 GB, root disk) streamed old→WSL→node `/tmp/seed-<app>.tar` (no direct old↔new SSH); per app: pause root+child → scale 0 → confirm 0 pods → wipe PV → `tar -xp --strip-components` → chown 1000:1000 (linuxserver apps) → scale 1 → resume. abs split config/metadata into its 2 PVCs.
- **Verified data intact:** plex 3 movies/12 shows + `/media` browseable; **sonarr 31 series**, **radarr 117 movies** (both rootfolders `/data/library/*` `accessible:true` — proves hostPath + path maps byte-identical), **prowlarr 333 indexers**, **qbittorrent 115 torrents**, **abs** health 200 + DB, **syncthing** 3 devices/1 folder. Plex identity `aa63d10e…` carried; old server had no token either (signed-out) → operator signs in via web UI to claim (Open Q10).
- **Cross-app URLs repointed (the one config that must change):** all pointed at `192.168.1.3` (old VM). Updated via each app's API to **in-cluster DNS** — sonarr/radarr download-client host → `qbittorrent.qbittorrent.svc.cluster.local`; prowlarr Sonarr/Radarr apps → `*.svc.cluster.local` (Readarr skipped, not migrated). Reachability confirmed (200 / ping OK). These live on the PVs and use cluster DNS, so they **survive the Phase 11 IP cutover** unchanged.
- **LoadBalancers** (klipper) all bound to `192.168.1.4`, no clashes: qbt 6881 tcp/udp, syncthing 22000 tcp/udp (+ plex hostNetwork 32400). Alongside 80/443, 53, 8090.
- **Rollback:** `qm shutdown 200` → `qm move-disk 200 scsi2 --target-vmid 100 --target-disk scsi1` → uncomment old fstab → `docker update --restart=unless-stopped` + `docker compose up -d` the 7. Old appdata never deleted (Phase 12); Phase-1 backups + cold tar (`/mnt/media/backups/pre-k8s-final-2026-07-05/`, rides the moved disk) intact.

**Operator follow-ups (non-blocking):**
- Add `{sonarr,radarr,prowlarr,qbittorrent,abs,syncthing}.lab.home.arpa` → `192.168.1.4` A records in the **old** Pi-hole to browse the new ingresses before cutover (already resolvable in the new Pi-hole).
- **Plex claim:** sign in via `http://192.168.1.4:32400/web` to re-associate the server to the account (config/identity migrated; libraries populate after sign-in).
- Node `/tmp/seed-*.tar` (~1.2 GB) are transient seed sources — cleared on reboot, safe to `rm` anytime.

### ▶ Resuming at Phase 11 — Cutover (the IP swap): handoff for a fresh agent (READ THIS)

Phases 0–9 are **DONE**; **Phase 10 (Home Assistant) is SKIPPED** (operator doesn't use HA — it dies with the old VM, never migrated). Every app the operator uses is live on the cluster at **`192.168.1.4`**, all 15 Argo apps Synced/Healthy. Phase 11 = make **`192.168.1.3`** mean "the cluster": swap the cluster VM to `.3`, move the old VM to `.13`, move the Tailscale subnet route. Full spec is **§ Phase 11** below — this block is the execution wrapper.

**Execution mechanics unchanged from Phase 4/5** — reuse the "▶ Resuming at Phase 4" block verbatim: `wsl.exe -d Ubuntu-24.04 -- bash -lc '…'`, the **write-a-script-and-run-it** quoting rule (never inline `$VAR`/`$(...)`/redirects), SSH targets `ssh pve` / `ssh old` / **`ssh -i ~/.ssh/id_ed25519_proxmox ops@192.168.1.4`** (the node has **no ssh-config alias** — always pass `-i`). Repo in WSL: `/mnt/c/Local Files/Repositories/Sky Haven/infra-homelab-config`. `KUBECONFIG=<repo>/ansible/lnsvrk8s01-kubeconfig` (regenerable; **server URL will need rewriting `.4`→`.3` after cutover**, or re-fetch via the k3s role).

**Before you start (pre-cutover gates):**
1. **DNS records:** confirm every `*.lab.home.arpa` the operator uses (`pihole,plex?,learning,sonarr,radarr,prowlarr,qbittorrent,abs,syncthing`) resolves in the **new** (cluster) Pi-hole. Plex uses host-net :32400, no ingress record needed.
2. **Plex claim** still outstanding — sign in at `http://192.168.1.4:32400/web` first if you want claimed-server continuity verified before the IP moves.
3. **Workstation DNS** is already pointed at the router `192.168.1.1` (§0.3) so it survives the Pi-hole blip — leave it there through the window, revert to DHCP/`.3` after.
4. **`make configure` needs `TS_AUTHKEY`** in the env (the tailscale role runs; join is idempotent-guarded so it won't re-login, but the var must be set). Same reusable key mechanism as Phase 4 — never persist it.

**Cutover gotchas specific to this repo:**
- **Argo reads `origin/major/kubernetes`** (not `main`). Any manifest change (none strictly required for Phase 11) must be committed **and pushed** before Argo sees it.
- **IaC drives the cluster IP:** `terraform/terraform.tfvars` `k8s_vm_ip = "192.168.1.3/24"` → `make infra-apply` (cloud-init change only; expect the **~3–4 min bpg guest-agent wait** — not a hang) → `[pve] qm reboot 200` (cloud-init network applies on boot). Then `ansible/group_vars/k8s.yml` `node_ip: 192.168.1.3` → `make configure`. **tls-san already includes `.3`** since Phase 4, so kubeconfig/k3s cert stays valid.
- **`nofail` media mount + `on_boot=true`** already survive the reboot; after `qm reboot 200` re-verify `df -h /mnt/media` shows the 930G disk and all pods return.
- **Subnet route** moves old→new: `[old] sudo tailscale set --advertise-routes=` then `[new] sudo tailscale set --advertise-routes=192.168.1.0/24` → **approve in the Tailscale admin console**.
- **Old VM** goes to `.13` and `systemctl disable docker`; its `homeassistant`/`pihole`/`ntfy` containers stop for good at step 1 (`docker compose down` + stockalert compose down). The 7 media containers are already `restart=no` + stopped (Phase 9).
- **Rollback is symmetric (~5 min)** and documented in §Phase 11 — practice saying it before step 1.

### Phase 11 — DONE (2026-07-05)

**Cutover complete: `192.168.1.3` now means "the cluster".** All 15 Argo apps Synced/Healthy on the new identity; LAN DNS + ad-blocking, every ingress, and ntfy all serving on `.3`. Old VM re-addressed to `.13`, docker disabled, subnet route moved to the new node (operator approved in console).

- **Pre-cutover DNS blocker found + fixed:** the `*.lab.home.arpa` records were **never present in either Pi-hole** (the Phase 6/9 "add A records" follow-ups were never actually done — verified both `custom.list` empty, `dns.hosts=[]`). Post-cutover `.3` = cluster Pi-hole, so every ingress hostname would have broken. Fix (GitOps, byte-surviving): `FTLCONF_misc_dnsmasq_lines: "address=/lab.home.arpa/192.168.1.3"` on the pihole Deployment — one dnsmasq **wildcard** → the ingress-nginx LB (`.3`), covers all current + future ingresses. Committed before the flip.
- **IP swap via IaC (worked clean):** `tfvars k8s_vm_ip .4→.3` → `terraform apply` (in-place `ip_config` update, no VM/disk recreate; media disk untouched via `ignore_changes=[disk[2]]`) → `qm reboot 200`. cloud-init **did** re-apply network on reboot (renamed the iface `ens18→eth0` via `set-name`; nothing in the repo pins `ens18`, k3s auto-detects, so harmless). `group_vars node_ip .3` → `make configure` reset k3s `--node-ip` and restarted it. tls-san already had `.3` (Phase 4) so certs stayed valid.
- **⚠⚠ Landmine (severe) — reboot swapped disk device letters → whole stack down.** After the reboot the 930G media disk came up as `/dev/sdb` and the 60G appdata disk as `/dev/sdc`. The base role mounted appdata by the **unstable device name `/dev/sdb`**, so `/srv/appdata` mounted the *media* disk and every local-path PV path vanished → all stateful pods stuck `FailedMount`/not-Ready → Argo apps stuck `Progressing` (pods Running but never Ready → empty Service endpoints → ingress 503, DNS `connection refused`). Media survived only because it mounts by-UUID. **Fix:** appdata now mounts by the stable **by-id slot path** `/dev/disk/by-id/scsi-0QEMU_QEMU_HARDDISK_drive-scsi1` + `nofail` (deterministic per Proxmox slot across reboots AND clean rebuilds — works on a blank disk pre-UUID; also removes the risk of the `mkfs` task ever targeting the media disk). Applied to live fstab + `group_vars`/`roles/base`. Recovery: fix fstab → `umount`/`mount` → delete stuck pods → all 15 green. **The Phase 13.4 reboot drill now genuinely validates this — do it.**
- **Role gap fixed:** `roles/k3s` now rewrites the fetched kubeconfig server `127.0.0.1 → node_ip` (was a manual Phase 4 step) so `make configure` yields a directly-usable kubeconfig (Phase 13 DR relies on this).
- **Commits:** `major/kubernetes` — pihole wildcard DNS (`6619a94`) + cutover IP & reboot-safe mounts (`f3ad857`), pushed. Argo reads `origin/major/kubernetes`.

**Operator manual steps still outstanding (non-blocking):**
- **Phone ntfy test:** confirm your existing subscription on `http://192.168.1.3:8090/<topic>` still receives a push (server is up + LB-reachable on the historic URL).
- **Router DHCP:** confirm no reservation pins the *old* VM's MAC to `.3` (VMs have different MACs — a stale reservation would fight the static assignment).
- **Plex claim:** still `claimed=0` — sign in at `http://192.168.1.3:32400/web` for claimed-server continuity (identity `aa63d10e…` carried over).
- **Workstation DNS:** revert this desktop from router `192.168.1.1` back to DHCP/`.3` now the cluster Pi-hole is live (was repointed in Phase 0 to survive the outage).

### Phase 12 — DONE (2026-07-05) — soak SKIPPED by operator directive

**Old VM 100 permanently destroyed.** Operator chose full destroy immediately (not the plan's 14-day soak) — informed consent after the irreversibility was spelled out. Safety mitigations that made this acceptable: appdata is live + Phase-8/9-verified on cluster PVs; media disk + `/mnt/media/backups` (Phase 1 backups + cold tar) already rode to VM 200 in Phase 9; crown-jewel key-backups live on VM 200. So the destroy lost only the quick Docker-rollback + the Phase 1 LVM snapshot, not data/backups.

- **Pre-destroy checks:** all `~/repos/*` on old VM had **0 unpushed commits**. Two uncommitted working-tree diffs captured before destroy: `app-stockalert-monitor/products.txt` (+13 AC product URLs) and `infra-developer-config/claude/settings.json` (editor prefs). **products.txt was a false alarm** — Phase 8 migrated the *working-tree* file, so the cluster configMap `stockalert-config-*` already has all **23** URLs (verified live). settings.json = trivial dev prefs, discarded. Patch saved to session scratchpad only.
- **Destroy:** `qm shutdown 100` → `qm destroy 100 --purge` (removed `vm-100-disk-0`). Lingering Phase 1 snapshot `pve/vm-100-disk-0-prek8s` removed with `lvremove`. `qm list` = only VM 200. VG `pve` VFree 16G (thin-pool logical space reclaimed).
- **Cluster grown 12→16 GiB:** `tfvars k8s_memory_mb=16384` → `terraform apply` (in-place) → `qm reboot 200` (memory not hot-plugged). `free -g` ~15 GiB usable (= 16384 MiB minus reserved).
- **✅ Phase 13.4 reboot drill PASSED (done early, on this reboot):** node auto-recovered at `.3`, **appdata correctly on `/dev/sdc` (60G) and media on `/dev/sdb` (930G) via the by-id/UUID mounts** — proves the Phase 11 disk-letter-swap fix holds across a cold reboot — **15/15 Argo apps Healthy** on poll 1, zero stuck pods. Power-loss recovery validated.
- **Old node removed from Tailscale** (operator, admin console). **`compose/` deleted** (operator; was already untracked on this branch). README updated to the post-migration world; `scripts/`+`systemd/` (legacy compose-era backup helpers, superseded by the Phase 13 restic timer) flagged pending-removal, left in place for now.

**Phase 13 remaining (not done):** restic timer exists in `roles/base` but **first run + `restic snapshots` verify** not done; **vzdump schedule** blocked on Open Q7 target; **off-box crown jewels** (age-encrypted private repo, Q6) not sent; **disaster-recovery doc** not written. The reboot drill (13.4) is already ✅.

### Still open

- **Open Q7 — vzdump target** for backup layer 2. `local` 18 GB free (too small), `data` full, no PBS. Not blocking; settle before weekly VM backups matter (likely needs a new disk).
- **Commit/push/merge:** Phases 0–3 are committed (see git log). **Phase 4 + `terraform/tailscale/` (key-expiry IaC) are DONE but UNCOMMITTED in the working tree** — commit as a Phase 4 checkpoint; merge `major/kubernetes` → `main` per the phase-boundary rule (also unblocks the Phase 5 branch landmine above).
- **Secrets in transcript (revoke):** the Phase 4 Tailscale **auth key** and the key-expiry **API token** were pasted into an earlier chat. Both should be revoked in the Tailscale console (Settings → Keys) — node is joined and expiry is set, neither is needed again.
- Stray files in repo root from tooling (WSL checkout only): `kubeseal`, `kubeseal-0.38.4-linux-amd64.tar.gz` — delete, don't commit. (Not present in the Windows-desktop checkout.)

---

## 1. Decision Record

Each entry: **Decision**, then reasoning. Items marked *(judgment call)* are opinionated recommendations; everything else is close to forced by the constraints.

### 1.1 Proxmox Terraform provider: `bpg/proxmox`

**Decision:** `bpg/proxmox`, pinned to an exact version (resolve latest 0.x at execution time per the pin rule in §1.16, expected ≥ 0.66).

Reasoning: `telmate/proxmox` is effectively unmaintained, has long-standing bugs around cloud-init and disk resizing, and lags Proxmox VE releases. `bpg/proxmox` is actively maintained, supports API-token auth, has a first-class `proxmox_virtual_environment_download_file` resource (so the Ubuntu cloud image itself is Terraform-managed — no manual template clicking), and models cloud-init natively. This is the community-consensus choice as of 2026.

### 1.2 VM sizing *(judgment call)*

**Decision:** `lnsvrk8s01` — 8 vCPU (`type=host`), **12 GiB RAM during co-existence, raised to 16 GiB after the old VM is decommissioned**, disk layout:

| Disk | Size | Purpose |
|---|---|---|
| `scsi0` | 40 GB | OS + k3s binaries/images. The old VM's 29 GB root at 77 % proves 29 GB is too small; 40 GB with no LVM shrinkage gives headroom for container images |
| `scsi1` | ~~150 GB~~ **60 GB** (Blocker 1, §0.3) | `/srv/appdata` — all Kubernetes PV data (local-path). Separate disk so the OS disk can be rebuilt without touching state, and so Proxmox backups can target it selectively. 60 not 150 to avoid thin-pool overcommit; grow later. |
| `scsi2` | (moved, not created) | The existing 930 GB media disk, moved from `lnsvrlab01` in Phase 9, mounted `/mnt/media` |

Reasoning: total current container RSS is ~2.5 GiB; k3s control plane + Argo CD + ingress adds ~1.5–2 GiB; Plex transcodes spike CPU not RAM. 12 GiB is comfortable. CPU overcommit on Proxmox is harmless for this workload, so both VMs can claim 8 vCPU simultaneously. RAM is the real co-existence constraint and the Proxmox host's total RAM is unknown — **Phase 0 discovers it; if host RAM < 34 GiB, shrink `lnsvrlab01` to 6 GiB first** (it uses 2.5 GiB; this is safe) via Proxmox UI or `qm set <vmid> --memory 6144` + reboot.

### 1.3 Terraform → Ansible handoff: separate pipeline stages via Makefile

**Decision:** Terraform and Ansible run as **separate, explicitly-ordered stages** (`make infra-apply` → `make configure`), glued by Terraform rendering the Ansible inventory file (`local_file` resource). **No `local-exec` provisioner.**

Reasoning: provisioners are Terraform's own documented "last resort" — they run only on resource creation, so a playbook fix after VM creation forces a taint/recreate or manual run anyway; they hide Ansible failures inside Terraform state weirdness; and they make `terraform plan` output lie about what a run will do. Separate stages are idempotent (re-run Ansible freely), have clean failure boundaries, and match how real pipelines stage IaC. The Makefile encodes the ordering so nothing is memorized.

### 1.4 Single-node vs multi-node: single node

**Decision:** One k3s server node (control plane + workloads on the same VM). No workers, no HA.

Reasoning: there is one physical machine. "Multi-node" here would mean multiple VMs on the same Proxmox host — that buys zero hardware fault tolerance while tripling RAM overhead and adding etcd quorum fragility, network storage requirements, and inter-VM traffic for no benefit. A single node with good backups (§1.15) is strictly better for one-host homelabs. The design keeps the door open: k3s supports adding agent nodes later with one command if a second physical machine appears.

### 1.5 Monorepo: yes — evolve `infra-homelab-config`

**Decision (updated 2026-07-14):** Use the existing `skyhaven-ltd/infra-homelab-config` repository for Proxmox Terraform, Ansible, Kubernetes manifests, and selected personal application source under `services/`. BookBuddy and StockAlert now follow this layout; `app-learning-review` remains separate unless it is migrated explicitly later.

At this scale, directory ownership and path-filtered CI provide a sufficient code-versus-config boundary without separate repositories. The monorepo keeps application and deployment changes together while service workflows publish immutable images and Argo CD continues to deploy only the explicitly pinned image digests in `kubernetes/`.

### 1.6 Kubernetes distribution: k3s

**Decision:** k3s, pinned version (resolve per §1.16 pin rule; expect a v1.32.x+k3s1 stable), installed by Ansible. Bundled Traefik **disabled**; bundled ServiceLB (klipper-lb), local-path-provisioner, CoreDNS, metrics-server **kept**.

Reasoning:
- **k3s vs full k8s (kubeadm):** kubeadm is a multi-component ops burden (etcd, certs, CNI selection, upgrade choreography) that teaches you Kubernetes *administration* at the cost of never getting to Kubernetes *usage*. k3s is a single binary + systemd unit, CNCF-certified conformant, with sane batteries included. Everything learned on k3s transfers.
- **vs k0s:** technically similar, materially smaller community/docs pool — for someone at zero Kubernetes knowledge, k3s's massive homelab community is worth more than k0s's slightly purer architecture.
- **vs microk8s:** snap-based (snap auto-refresh has broken clusters at 3 a.m.), Canonical-centric addon model that hides the standard manifest-driven way of doing things.
- **Why disable Traefik:** the bundled Traefik is installed by k3s itself, outside Git — invisible to GitOps. Installing ingress-nginx via Argo CD keeps 100 % of in-cluster software Git-managed and uses the ingress controller with the largest documentation base. ServiceLB stays because something must answer LoadBalancer-type Services on bare metal (Pi-hole's port 53, ntfy's 8090) and klipper-lb is exactly the right size for one node — MetalLB would add BGP/ARP configuration for zero gain here.

### 1.7 GitOps tool: Argo CD

**Decision:** Argo CD (pinned release), app-of-apps pattern, auto-sync + self-heal + prune enabled for all Applications.

Reasoning: Argo CD vs Flux is close at this scale; the decisive factor for a GitOps beginner is Argo's web UI, which visualizes the sync state, resource tree, and diffs of every application — an unmatched learning tool when Kubernetes is new. It's also the pattern most homelab references use (app-of-apps), and its `Application` CRD keeps "what's deployed" enumerable in one directory. Flux is excellent and slightly leaner, but its CLI/CRD-only feedback loop is a worse teacher. *(Judgment call — Flux would also work.)*

### 1.8 Infra changes vs app changes: infra stays manually triggered, by design

**Decision:** App/manifest changes deploy automatically via Argo CD on merge to `main` (that's the GitOps loop). Terraform/Ansible changes are applied **manually** via `make infra-plan && make infra-apply` (and `make configure`) from `lnsvrlab01` (later from any tailnet machine). No CI runner executes Terraform.

Reasoning: there is no external CI that can reach the Proxmox API on the LAN without either exposing Proxmox (unacceptable) or joining CI to the tailnet (possible — GitHub Actions + `tailscale/github-action` — but then a compromised Actions workflow holds keys to the hypervisor). For a single operator, auto-applying hypervisor changes on merge adds risk and subtracts nothing: infra changes are rare, and the human running `make infra-apply` reviewing a plan *is* the approval gate. This is a deliberate architecture, not a gap. Future option (documented, not built): a self-hosted GitHub Actions runner on the Proxmox host running plan-on-PR only.

### 1.9 Ingress, TLS, hostnames

**Decision:**
- **Ingress:** `ingress-nginx` (Helm chart via Argo CD), Service type LoadBalancer → klipper binds 80/443 on the node IP.
- **Hostnames:** `<app>.lab.home.arpa` (RFC 8375 home-network domain), resolved by Pi-hole local DNS records pointing at the cluster IP (`192.168.1.3` after cutover).
- **TLS:** cert-manager (Helm via Argo CD) with a **self-signed internal CA** (`ClusterIssuer` backed by a cert-manager-generated root CA). Every Ingress gets a real cert from that CA. The root CA cert is exported once and installed on the user's devices.

Reasoning: no public domain is confirmed for this homelab (Open Question 3). An internal CA works with zero external dependencies, no port-forwarding, no DNS-01 API tokens, and teaches the full cert-manager machinery. If Open Question 3 lands a real domain + Cloudflare, swap the ClusterIssuer for a Let's Encrypt DNS-01 issuer later — a one-file change; every Ingress annotation stays identical. Trade-off: browsers on devices without the root CA installed show warnings.

### 1.10 Secrets management: Sealed Secrets

**Decision:** Bitnami Sealed Secrets (controller via Argo CD, `kubeseal` CLI on the workstation). Encrypted `SealedSecret` manifests live in Git next to their app. Exactly **one** manual, never-in-Git bootstrap secret: the Argo CD repo deploy key (Phase 5). The sealed-secrets controller's private key is backed up to `/mnt/media/backups/sealed-secrets/` and one off-box copy (Open Question 6).

Reasoning vs SOPS: SOPS+age is a fine tool but integrates with Argo CD only via plugins/sidecars (KSOPS) — extra moving parts and a bootstrap age-key distribution problem. Sealed Secrets is a native controller + CRD: `kubeseal` encrypts with the cluster's public key, Git stores ciphertext, controller decrypts in-cluster, Argo needs zero special config. The known weakness — secrets are coupled to one cluster key — is neutralized by backing up the key (which you must do anyway for disaster recovery, §1.15).

### 1.11 Persistent storage: local-path-provisioner + hostPath for media

**Decision:**
- **App state** (Pi-hole config, *arr databases, Plex metadata, SQLite files, HA config): k3s's bundled **local-path-provisioner** as default StorageClass, with its data root moved to `/srv/appdata/local-path` (the dedicated 60 GB `scsi1` disk, §0.3).
- **Bulk media** (`/mnt/media`): the existing 930 GB disk moved to the new VM and mounted as **hostPath volumes** in pod specs, exactly mirroring today's bind mounts (`/mnt/media` → `/data` in-container, preserving *arr/qbittorrent path mappings and hardlink behavior).
- **Longhorn: rejected.**

Reasoning: Longhorn's value is *replication across nodes* — on one node it delivers zero durability gain while adding an engine, a UI, iSCSI daemons, and a per-volume overhead tax; a failed single node loses Longhorn volumes just as dead as local-path ones. local-path is dumb in the best way: PVs are plain directories under `/srv/appdata/local-path/`, trivially rsync-able for the data-seeding migration (§4 recipe) and trivially backed up by restic (§1.15). hostPath for media (rather than a PV) is deliberate: it's a shared, pre-existing, multi-app read-write directory tree where per-app PVC semantics would be a fiction. The `/data` in-container path is preserved **byte-identical** to compose so sonarr/radarr/qbittorrent internal path references and hardlinks keep working with zero re-configuration.

### 1.12 Pi-hole / DNS continuity

**Decision:** Pi-hole **migrates into the cluster** (it's the Phase 6 pilot app). DNS on port 53 TCP+UDP is exposed via a LoadBalancer Service on the node IP. During the whole migration the *old* Pi-hole on `192.168.1.3` keeps serving the LAN untouched. Cutover (Phase 11) is an **IP swap**: old VM moves to `192.168.1.13`, new VM takes `192.168.1.3`. LAN clients, the router's DHCP-advertised DNS, and every hardcoded reference to `.3` (including phone ntfy subscriptions) continue working without touching any client device.

Reasoning: the alternative — re-pointing router DHCP at a new IP — requires router access, waits on client lease renewal, and still breaks the hardcoded ntfy base URL. Swapping IPs at the infrastructure layer moves the *service identity* to the new machine in one atomic step with a trivially symmetric rollback. The cluster node must **never depend on cluster Pi-hole for its own resolution** (boot-order deadlock after power loss): the node's own DNS is statically `1.1.1.1`/`8.8.8.8` via cloud-init (§1.13).

### 1.13 Node DNS + Tailscale (avoiding the MagicDNS SERVFAIL repeat)

**Decision:** On `lnsvrk8s01`: static resolvers `1.1.1.1`, `8.8.8.8` in cloud-init netplan; Tailscale installed by Ansible with `--accept-dns=false`; subnet route `192.168.1.0/24` advertisement moves from old VM to new at cutover.

Reasoning: the documented failure on `lnsvrlab01` (containers SERVFAIL public names because the runtime forwards to MagicDNS `100.100.100.100`) would recur in-cluster: CoreDNS forwards upstream to the *node's* `/etc/resolv.conf`. `--accept-dns=false` keeps MagicDNS off the node resolv chain entirely, so CoreDNS forwards to 1.1.1.1 and every pod resolves public names. Tailnet-name resolution from the node isn't needed (use IPs/LAN names); LAN clients get ad-blocking DNS from Pi-hole, not from the node's resolvers. Preserves the no-Plex-Pass remote-access path (subnet route + direct connections) after cutover.

### 1.14 Custom app images: GHCR + GitHub Actions (new requirement)

**Decision:** `app-learning-review` and `app-stockalert-monitor` currently `build: .` locally — Kubernetes needs a registry. Each app repo gets a GitHub Actions workflow building and pushing `ghcr.io/skyhaven-ltd/<app>:<git-sha>` (and `:latest`) on push to `main`. The cluster pulls via an `imagePullSecret` (a GHCR read-only PAT, sealed). Deploying a new app version = CI pushes image, then a one-line image-tag bump commit in the monorepo (keeps Git as literal source of truth for *what runs*).

Reasoning: GHCR is free for these repos, already inside the org's auth perimeter, and GitHub Actions is the zero-infra CI available. Building on-node (k3s can't) or running a private registry in-cluster (chicken-and-egg on cluster rebuild) are both worse. sha-pinned tags in Git give exact rollback.

### 1.15 Backup strategy

**Decision (three layers):**
1. **App state:** nightly `restic` snapshot of `/srv/appdata` → `/mnt/media/backups/restic-appdata/` via systemd timer on the node (Ansible-managed). 14 daily + 8 weekly retention.
2. **VM level:** weekly Proxmox `vzdump` of `lnsvrk8s01` **scsi0 + scsi1 only** (media disk excluded via `backup=0` flag on scsi2) to Proxmox-local backup storage *(target storage: discover in Phase 0; PBS if present — Open Question 7)*.
3. **Crown jewels, off-box** (Open Question 6 for destination): sealed-secrets private key, k3s token, Terraform state, root CA secret, restic password.

Reasoning: single-node means the node *is* the blast radius; restic gives fast file-level restore of one app's state, vzdump gives whole-VM disaster recovery, and layer 3 makes a rebuilt-from-Git cluster able to decrypt its own secrets. `/mnt/media` bulk media is explicitly *not* backed up (existing posture, 761 GB of re-acquirable media; `backups/` dir itself is on that disk — acceptable, noted in §5 risks).

### 1.16 Version-pinning rule (applies everywhere)

GitOps requires pinned versions; this document cannot know July-2026 latest releases. **Rule (mechanical, no judgment):** at execution time, resolve the current latest *stable* release of each pinned artifact (Helm chart, image tag, k3s version, provider version) via its registry/GitHub releases, write that exact version into Git, and record it in `docs/versions.md`. Never deploy `:latest` as a running tag. For container images prefer the upstream's current stable semver tag; for `linuxserver.io` images use their `version-<x>` tags. Upgrades thereafter are Git commits bumping pins.

---

## 2. Target Repo Structure (`skyhaven-ltd/infra-homelab-config`)

```
infra-homelab-config/
├── README.md
├── Makefile                          # single entrypoint: infra-plan/apply, configure, bootstrap, seal
├── .gitignore                        # *.tfstate*, .terraform/, ansible/inventory/hosts.yml, *.key, kubeconfig
├── docs/
│   ├── k8s-gitops-migration-plan.md  # this file
│   └── versions.md                   # every resolved pin (per §1.16), maintained as pins change
├── terraform/                        # Layer 1: Proxmox VM (infra creation)
│   ├── versions.tf                   # terraform + bpg/proxmox pins
│   ├── providers.tf                  # provider config (endpoint; token via env var)
│   ├── variables.tf
│   ├── terraform.tfvars              # non-secret values (node name, storage IDs, IPs)
│   ├── image.tf                      # Ubuntu 24.04 cloud image download (TF-managed)
│   ├── vm-k8s.tf                     # lnsvrk8s01 definition incl. cloud-init
│   ├── inventory.tf                  # renders ansible/inventory/hosts.yml from VM facts
│   └── outputs.tf
├── ansible/                          # Layer 2: VM configuration (OS → k3s → Argo bootstrap)
│   ├── ansible.cfg
│   ├── site.yml                      # imports roles in order: base, tailscale, k3s, argocd_bootstrap
│   ├── group_vars/
│   │   └── k8s.yml                   # k3s version pin, disk device names, tailscale flags
│   ├── inventory/
│   │   └── hosts.yml                 # GENERATED by terraform — gitignored
│   └── roles/
│       ├── base/                     # packages, qemu-guest-agent, scsi1 fs+mount, sysctls, unattended-upgrades, restic timer
│       ├── tailscale/                # install, up --accept-dns=false (route advert added at cutover)
│       ├── k3s/                      # /etc/rancher/k3s/config.yaml + pinned installer
│       └── argocd_bootstrap/         # kubectl apply -k kubernetes/bootstrap/argocd + root app
├── kubernetes/
│   ├── bootstrap/
│   │   └── argocd/                   # kustomization pinning upstream Argo CD install manifest + ns
│   │       ├── kustomization.yaml
│   │       └── namespace.yaml
│   ├── argocd-apps/                  # app-of-apps: one Application manifest per deployable unit
│   │   ├── root-app.yaml             # applied once by ansible; watches this directory
│   │   ├── infra-ingress-nginx.yaml
│   │   ├── infra-cert-manager.yaml
│   │   ├── infra-cert-issuers.yaml
│   │   ├── infra-sealed-secrets.yaml
│   │   ├── app-pihole.yaml
│   │   ├── app-plex.yaml … (one per app)
│   │   └── app-stockalert.yaml
│   ├── infrastructure/               # platform components (Helm-chart Applications point here for values)
│   │   ├── ingress-nginx/values.yaml
│   │   ├── cert-manager/values.yaml
│   │   ├── cert-issuers/             # plain manifests: selfsigned issuer → root CA cert → CA ClusterIssuer
│   │   └── sealed-secrets/values.yaml
│   └── apps/                         # one directory per app: plain YAML + kustomization.yaml
│       ├── pihole/                   #   deployment, pvc(s), services, ingress, sealedsecret
│       ├── plex/
│       ├── sonarr/  radarr/  prowlarr/  qbittorrent/  audiobookshelf/  syncthing/
│       ├── homeassistant/
│       ├── learning-review/
│       └── stockalert/               # stock-checker + flaresolverr + ntfy (one namespace, three deployments)
├── compose/                          # LEGACY: current compose.yaml moves here; deleted in Phase 12
└── scripts/                          # existing helper scripts (unchanged until decommission review)
```

Placement logic: **terraform/** creates things Proxmox knows about; **ansible/** configures the OS up to and including "Argo CD is running and pointed at this repo"; **kubernetes/** is Argo CD's exclusive territory — after bootstrap, *nothing* under `kubernetes/` is ever `kubectl apply`'d by hand (the two documented exceptions: the one-time repo-key secret and root-app in Phase 5). Terraform state stays local on the machine running it, gitignored, copied into the layer-3 backup set.

---

## 3. Phased Execution Plan

General rules for every phase:
- Work on branch `k8s-migration` in the monorepo; merge to `main` at each phase boundary (Argo CD watches `main`).
- Never stop an old-stack container until its replacement is verified (each phase says when).
- If a verification step fails, follow that phase's rollback, fix, re-run. Phases are idempotent unless noted.
- Shell blocks are written for the stated host: `[old]` = lnsvrlab01, `[pve]` = Proxmox host root shell, `[new]` = lnsvrk8s01, `[any]` = wherever kubectl/kubeseal/git run (initially lnsvrlab01).

---

### Phase 0 — Preflight discovery & access ✅ DONE (2026-07-05, see §0.3)

**Prerequisites:** none.

**Steps:**

1. `[old]` Verify SSH to the Proxmox host over the tailnet (try `ssh root@100.82.112.92 pveversion`; if key auth fails this is a hard blocker → Open Question 1).
2. `[pve]` Discover and record facts:

```bash
pvesh get /nodes --output-format json        # → node NAME (expected single node)
pvesm status                                  # → storage IDs; note which are active
                                              #   - VM disk storage (type lvmthin "local-lvm" or zfs)
                                              #   - a storage with content "iso" (usually "local")
                                              #   - a storage with content "backup"
free -g; nproc                                # → host RAM/cores (drives §1.2 co-existence call)
qm list                                       # → VMID of lnsvrlab01 (call it OLD_VMID)
qm config <OLD_VMID>                          # → which scsiN is the 930G media disk (call it MEDIA_DISK_SLOT)
cat /etc/pve/qemu-server/<OLD_VMID>.conf | grep net0   # → bridge name (expected vmbr0)
```

3. `[old]` Confirm gateway: `ip route | grep default` (expected `192.168.1.1`).
4. `[old]` Confirm `gh` CLI is authenticated for org `skyhaven-ltd`: `gh auth status`.
5. Record all discovered values in `docs/versions.md` under a "Environment facts" heading, commit.
6. If host RAM < 34 GiB: `[pve]` `qm set <OLD_VMID> --memory 6144`, then reboot `lnsvrlab01` at a convenient moment (brief full outage of all current apps — do it now, not mid-migration). Verify after reboot: `free -g` on old shows ~6 GiB and all 13 containers running (`docker ps | wc -l` ≥ 13… wait for compose restart policies to bring them up).

**Verification:** `docs/versions.md` contains node name, storage IDs, OLD_VMID, MEDIA_DISK_SLOT, bridge, gateway, host RAM; SSH to pve works non-interactively; `gh auth status` OK.

**Rollback:** nothing to roll back (read-only except optional RAM shrink; revert with `qm set <OLD_VMID> --memory 20480`).

---

### Phase 1 — Backup current state ✅ DONE (2026-07-05, see §0.3)

**Prerequisites:** Phase 0.

**Steps** `[old]`:

```bash
BK=/mnt/media/backups/pre-k8s-$(date +%F); mkdir -p "$BK"

# 1. Compose definitions + env (env files contain secrets: keep perms tight)
cp /srv/containers/media/compose.yaml "$BK/media-compose.yaml"
cp -r ~/repos/app-stockalert-monitor/{docker-compose.yml,.env,config.yaml,products.txt} "$BK/stockalert/" 2>/dev/null || \
  { mkdir -p "$BK/stockalert"; cp ~/repos/app-stockalert-monitor/docker-compose.yml ~/repos/app-stockalert-monitor/.env ~/repos/app-stockalert-monitor/config.yaml ~/repos/app-stockalert-monitor/products.txt "$BK/stockalert/"; }
mkdir -p "$BK/learning-review"; cp ~/repos/app-learning-review/{docker-compose.yml,.env} "$BK/learning-review/"
chmod -R go-rwx "$BK"

# 2. App state (stop nothing; these apps tolerate hot copy for a safety snapshot —
#    the REAL migration copies happen cold, per-app, in later phases)
sudo tar -C /srv/containers/media -czf "$BK/appdata.tar.gz" appdata
sudo tar -C /var/lib/docker/volumes/app-learning-review_learning_data -czf "$BK/learning-data.tar.gz" _data
tar -C ~/repos/app-stockalert-monitor -czf "$BK/stockalert-data.tar.gz" data ntfy

# 3. Network/DNS identity of the host (needed for the IP swap later)
ip addr > "$BK/ip-addr.txt"; ip route > "$BK/ip-route.txt"
sudo cp -r /etc/netplan "$BK/netplan"
tailscale status > "$BK/tailscale-status.txt"

# 4. Verify archives are readable
for f in "$BK"/*.tar.gz; do tar -tzf "$f" >/dev/null && echo "OK $f"; done
```

`[pve]` Snapshot the old VM as a point-in-time fallback: `qm snapshot <OLD_VMID> pre-k8s-migration --description "before k8s migration $(date +%F)"` (works on lvmthin/zfs; if storage doesn't support snapshots, run `vzdump <OLD_VMID> --storage <backup-storage> --mode snapshot` instead).

**Verification:** all `OK` lines printed; `qm listsnapshot <OLD_VMID>` (or vzdump log) shows the snapshot; `du -sh $BK` is plausibly sized (≥ 1.5 GB given appdata sizes).

**Rollback:** n/a (backups only). **This phase is the master rollback for everything later.**

---

### Phase 2 — Monorepo scaffold

**Prerequisites:** Phase 1.

**Steps** `[old]` in `~/repos/infra-homelab-config`, branch `k8s-migration`:

1. Create the §2 directory tree. Move `compose.yaml` → `compose/compose.yaml` (update the README pointer; if a systemd unit references the old path — check `systemd/` dir — update it in the same commit and re-link on the host so the running stack is unaffected).
2. `.gitignore`:

```gitignore
*.tfstate
*.tfstate.*
.terraform/
.terraform.lock.hcl.backup
ansible/inventory/hosts.yml
*.key
*-kubeconfig
crash.log
```

3. `Makefile`:

```makefile
TF_DIR      := terraform
ANSIBLE_DIR := ansible

.PHONY: infra-init infra-plan infra-apply configure bootstrap seal

infra-init:
	cd $(TF_DIR) && terraform init

infra-plan:
	cd $(TF_DIR) && terraform plan

infra-apply:
	cd $(TF_DIR) && terraform apply

configure:
	cd $(ANSIBLE_DIR) && ansible-galaxy install -r requirements.yml && \
	ansible-playbook -i inventory/hosts.yml site.yml

bootstrap:
	cd $(ANSIBLE_DIR) && ansible-playbook -i inventory/hosts.yml site.yml --tags argocd

# usage: make seal FILE=secret.yaml OUT=kubernetes/apps/foo/sealedsecret.yaml
seal:
	kubeseal --controller-namespace sealed-secrets --format yaml < $(FILE) > $(OUT)
```

4. Install tooling on `[old]` (it's the ops workstation for now): `terraform` (HashiCorp apt repo, pin latest 1.x per §1.16), `ansible` (pipx or apt), `kubectl`, `kubeseal`, `helm` (for template debugging only — Argo does the real installs).
5. Commit, push, merge `k8s-migration` → `main` (repeat at each phase boundary; not restated below).

**Verification:** `make infra-init` fails only because `terraform/` has no config yet (expected); tree matches §2; running compose stack unaffected (`docker ps` count unchanged).

**Rollback:** `git revert`; restore compose.yaml path if moved.

---

### Phase 3 — Proxmox API token + Terraform VM provision

**Prerequisites:** Phases 0–2.

**Step 1** `[pve]` — create a Terraform identity:

```bash
pveum user add terraform@pve --comment "Terraform IaC"
pveum aclmod / -user terraform@pve -role Administrator
pveum user token add terraform@pve tf -privsep 0
# SAVE the printed token value NOW — it is shown once.
```

(Administrator on `/` is pragmatic for a single-operator homelab; a least-privilege custom role is a documented future hardening, not done now.)

**Step 2** `[old]` — Terraform config. `terraform/versions.tf`:

```hcl
terraform {
  required_version = ">= 1.9.0"
  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = "= <PIN per §1.16, e.g. 0.66.x latest>"
    }
  }
}
```

`terraform/providers.tf`:

```hcl
provider "proxmox" {
  endpoint  = "https://${var.proxmox_host}:8006/"
  api_token = var.proxmox_api_token   # supplied via TF_VAR_proxmox_api_token env var — never in Git
  insecure  = true                    # self-signed PVE cert on a LAN host; acceptable here
  ssh {                               # bpg uses SSH for a few operations (e.g. file uploads)
    agent    = true
    username = "root"
  }
}
```

`terraform/variables.tf`:

```hcl
variable "proxmox_host"      { type = string }               # pve LAN IP or tailscale IP from Phase 0
variable "proxmox_api_token" { type = string, sensitive = true } # "terraform@pve!tf=<uuid>"
variable "proxmox_node"      { type = string }               # node name from Phase 0
variable "vm_storage"        { type = string }               # VM disk storage ID from Phase 0
variable "iso_storage"       { type = string, default = "local" }
variable "k8s_vm_ip"         { type = string, default = "192.168.1.4/24" } # becomes .3 at cutover
variable "lan_gateway"       { type = string, default = "192.168.1.1" }
variable "bridge"            { type = string, default = "vmbr0" }
variable "k8s_memory_mb"     { type = number, default = 12288 }  # → 16384 in Phase 12
variable "ssh_public_key"    { type = string }               # content of ~/.ssh/id_ed25519.pub (generate if absent)
```

`terraform/terraform.tfvars`: fill every variable with Phase 0 facts (this file is non-secret and committed; the token is env-only).

`terraform/image.tf`:

```hcl
resource "proxmox_virtual_environment_download_file" "ubuntu_noble" {
  content_type = "iso"
  datastore_id = var.iso_storage
  node_name    = var.proxmox_node
  url          = "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img"
  file_name    = "ubuntu-noble-cloudimg-amd64.img"
}
```

`terraform/vm-k8s.tf`:

```hcl
resource "proxmox_virtual_environment_vm" "k8s" {
  name        = "lnsvrk8s01"
  description = "k3s single-node cluster (managed by Terraform)"
  node_name   = var.proxmox_node
  vm_id       = 200
  on_boot     = true

  cpu    { cores = 8, type = "host" }
  memory { dedicated = var.k8s_memory_mb }
  agent  { enabled = true }               # qemu-guest-agent installed by Ansible

  disk {
    datastore_id = var.vm_storage
    interface    = "scsi0"
    size         = 40
    file_id      = proxmox_virtual_environment_download_file.ubuntu_noble.id
    iothread     = true
    discard      = "on"
  }
  disk {
    datastore_id = var.vm_storage
    interface    = "scsi1"
    size         = 60          # Blocker 1 (§0.2/§0.3): 60 not 150 — 40+60=100 GB fits local-lvm thin (154 GB avail) with no overcommit. Grow later after Phase 12 frees old VM's ~30 GB.
    iothread     = true
    discard      = "on"
    file_format  = "raw"
  }

  network_device { bridge = var.bridge }
  operating_system { type = "l26" }
  serial_device {}                        # cloud images want a serial console

  initialization {
    datastore_id = var.vm_storage
    ip_config {
      ipv4 { address = var.k8s_vm_ip, gateway = var.lan_gateway }
    }
    dns { servers = ["1.1.1.1", "8.8.8.8"] }   # static; NEVER the cluster's own pi-hole (§1.12)
    user_account {
      username = "ops"
      keys     = [var.ssh_public_key]
    }
  }

  lifecycle {
    ignore_changes = [disk[2]]  # media disk gets attached out-of-band in Phase 9 as scsi2
  }
}
```

`terraform/inventory.tf`:

```hcl
resource "local_file" "ansible_inventory" {
  filename        = "${path.module}/../ansible/inventory/hosts.yml"
  file_permission = "0640"
  content = yamlencode({
    k8s = {
      hosts = {
        lnsvrk8s01 = {
          ansible_host = split("/", var.k8s_vm_ip)[0]
          ansible_user = "ops"
        }
      }
    }
  })
}
```

(add `hashicorp/local` to required_providers). `terraform/outputs.tf`: output the VM IP and VMID.

**Step 3** `[old]`:

```bash
export TF_VAR_proxmox_api_token='terraform@pve!tf=<uuid-from-step-1>'
make infra-init && make infra-plan   # review: 3 resources to add
make infra-apply
```

**Verification:** `qm list` on pve shows VMID 200 running; `ssh ops@192.168.1.4 'lsb_release -d && lsblk'` succeeds and shows sda 40G / sdb 60G; `ansible/inventory/hosts.yml` exists. Old stack untouched.

**Rollback:** `terraform destroy` (only touches VM 200 + downloaded image). Nothing on the old VM changed.

---

### Phase 4 — Ansible: base config, Tailscale, k3s ✅ DONE 2026-07-05 (see §0.3 for as-built + fixes)

**Prerequisites:** Phase 3.

`ansible/ansible.cfg`:

```ini
[defaults]
inventory = inventory/hosts.yml
host_key_checking = False
roles_path = roles
interpreter_python = auto_silent
```

`ansible/group_vars/k8s.yml`:

```yaml
k3s_version: "<PIN per §1.16, e.g. v1.32.x+k3s1>"
appdata_device: /dev/sdb          # the 60G scsi1 disk (§0.3)
appdata_mount: /srv/appdata
node_ip: 192.168.1.4              # updated to .3 at cutover (Phase 11)
tailscale_authkey: "{{ lookup('env', 'TS_AUTHKEY') }}"   # one-time reusable key from admin console
```

`ansible/site.yml`:

```yaml
- hosts: k8s
  become: true
  roles:
    - { role: base,             tags: [base] }
    - { role: tailscale,        tags: [tailscale] }
    - { role: k3s,              tags: [k3s] }
    - { role: argocd_bootstrap, tags: [argocd] }
```

`roles/base/tasks/main.yml` (complete):

```yaml
- name: Install base packages
  ansible.builtin.apt:
    name: [qemu-guest-agent, curl, jq, restic, nfs-common, open-iscsi, htop, unattended-upgrades]
    update_cache: true
- name: Enable qemu-guest-agent
  ansible.builtin.systemd: { name: qemu-guest-agent, state: started, enabled: true }
- name: Filesystem on appdata disk
  community.general.filesystem: { fstype: ext4, dev: "{{ appdata_device }}" }
- name: Mount appdata disk
  ansible.posix.mount:
    path: "{{ appdata_mount }}"
    src: "{{ appdata_device }}"
    fstype: ext4
    opts: defaults,noatime
    state: mounted
- name: Kernel params for k8s
  ansible.posix.sysctl: { name: "{{ item.k }}", value: "{{ item.v }}", state: present }
  loop:
    - { k: fs.inotify.max_user_instances, v: "1024" }
    - { k: fs.inotify.max_user_watches,   v: "1048576" }
- name: Enable unattended security upgrades
  ansible.builtin.copy:
    dest: /etc/apt/apt.conf.d/20auto-upgrades
    content: |
      APT::Periodic::Update-Package-Lists "1";
      APT::Periodic::Unattended-Upgrade "1";
```

(`requirements.yml`: `community.general`, `ansible.posix`.)

`roles/tailscale/tasks/main.yml`:

```yaml
- name: Add tailscale repo key/source
  ansible.builtin.shell: |
    curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/noble.noarmor.gpg -o /usr/share/keyrings/tailscale-archive-keyring.gpg
    curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/noble.tailscale-keyring.list -o /etc/apt/sources.list.d/tailscale.list
  args: { creates: /etc/apt/sources.list.d/tailscale.list }
- name: Install tailscale
  ansible.builtin.apt: { name: tailscale, update_cache: true }
- name: Bring up tailscale (MagicDNS OFF on this node — see decision 1.13)
  ansible.builtin.command: tailscale up --authkey={{ tailscale_authkey }} --accept-dns=false --hostname=lnsvrk8s01
  args: { creates: /var/lib/tailscale/tailscaled.state }
```

`roles/k3s/tasks/main.yml`:

```yaml
- name: k3s config directory
  ansible.builtin.file: { path: /etc/rancher/k3s, state: directory, mode: "0755" }
- name: k3s config
  ansible.builtin.copy:
    dest: /etc/rancher/k3s/config.yaml
    content: |
      disable:
        - traefik
      node-ip: {{ node_ip }}
      tls-san:
        - lnsvrk8s01
        - 192.168.1.3        # future identity after IP swap
        - {{ node_ip }}
      default-local-storage-path: {{ appdata_mount }}/local-path
      write-kubeconfig-mode: "0640"
  notify: restart k3s
- name: Install k3s (pinned)
  ansible.builtin.shell: |
    curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION={{ k3s_version }} sh -s - server
  args: { creates: /usr/local/bin/k3s }
- name: Fetch kubeconfig to controller
  ansible.builtin.fetch:
    src: /etc/rancher/k3s/k3s.yaml
    dest: "{{ playbook_dir }}/../lnsvrk8s01-kubeconfig"
    flat: true
```

(handler `restart k3s`: `systemd: name=k3s state=restarted`.) After fetch, `[old]`: `sed -i 's/127.0.0.1/192.168.1.4/' ansible/lnsvrk8s01-kubeconfig; export KUBECONFIG=$PWD/ansible/lnsvrk8s01-kubeconfig` (file is gitignored; add to layer-3 backups… actually it's regenerable, the *k3s token* `/var/lib/rancher/k3s/server/token` is what goes in backups).

Run: `TS_AUTHKEY=<from tailscale admin> make configure` (skip `argocd` tag failures for now — that role lands in Phase 5; alternatively run with `--skip-tags argocd`).

**Verification:**

```bash
kubectl get nodes -o wide        # lnsvrk8s01 Ready, correct version, INTERNAL-IP 192.168.1.4
kubectl get pods -A              # coredns, local-path-provisioner, metrics-server Running; NO traefik
kubectl run dns-test --rm -it --image=busybox:1.36 --restart=Never -- nslookup github.com
                                 # MUST resolve — this proves the §1.13 SERVFAIL fix
```

**Rollback:** `/usr/local/bin/k3s-uninstall.sh` on the node, or `terraform destroy` the VM and re-run Phases 3–4. Old stack untouched.

---

### Phase 5 — Argo CD bootstrap + platform apps

**Prerequisites:** Phase 4; kubeconfig working from `[old]`.

**Step 1 — Argo CD install manifests in Git.** `kubernetes/bootstrap/argocd/namespace.yaml`: plain `Namespace` named `argocd`. `kustomization.yaml`:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: argocd
resources:
  - namespace.yaml
  - https://raw.githubusercontent.com/argoproj/argo-cd/<PIN e.g. v2.14.x>/manifests/install.yaml
```

**Step 2 — repo deploy key (the ONE manual secret).** `[old]`:

```bash
ssh-keygen -t ed25519 -f /tmp/argocd-repo-key -N "" -C "argocd@lnsvrk8s01"
gh repo deploy-key add /tmp/argocd-repo-key.pub -R skyhaven-ltd/infra-homelab-config --title argocd-readonly
kubectl apply -k kubernetes/bootstrap/argocd
kubectl -n argocd create secret generic repo-infra-homelab-config \
  --from-literal=type=git \
  --from-literal=url=git@github.com:skyhaven-ltd/infra-homelab-config.git \
  --from-file=sshPrivateKey=/tmp/argocd-repo-key
kubectl -n argocd label secret repo-infra-homelab-config argocd.argoproj.io/secret-type=repository
shred -u /tmp/argocd-repo-key   # key now lives only in-cluster; regenerable at will
```

**Step 3 — root app (app-of-apps).** `kubernetes/argocd-apps/root-app.yaml`:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata: { name: root, namespace: argocd }
spec:
  project: default
  source:
    repoURL: git@github.com:skyhaven-ltd/infra-homelab-config.git
    targetRevision: main
    path: kubernetes/argocd-apps
  destination: { server: https://kubernetes.default.svc, namespace: argocd }
  syncPolicy:
    automated: { prune: true, selfHeal: true }
```

Apply once by hand (`kubectl apply -f kubernetes/argocd-apps/root-app.yaml`) — from here on, adding a file to `kubernetes/argocd-apps/` deploys it. Wrap Steps 1–3 into `roles/argocd_bootstrap` (each task with a `creates`/`kubectl get`-guard so re-runs are no-ops) so a cluster rebuild is `make configure` end-to-end.

**Step 4 — platform Applications.** Add to `kubernetes/argocd-apps/` (all follow this template — shown once, deltas noted):

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: ingress-nginx
  namespace: argocd
  annotations: { argocd.argoproj.io/sync-wave: "-2" }   # platform before apps
spec:
  project: default
  sources:
    - repoURL: https://kubernetes.github.io/ingress-nginx
      chart: ingress-nginx
      targetRevision: "<PIN chart ver>"
      helm: { valueFiles: ["$values/kubernetes/infrastructure/ingress-nginx/values.yaml"] }
    - repoURL: git@github.com:skyhaven-ltd/infra-homelab-config.git
      targetRevision: main
      ref: values
  destination: { server: https://kubernetes.default.svc, namespace: ingress-nginx }
  syncPolicy:
    automated: { prune: true, selfHeal: true }
    syncOptions: [CreateNamespace=true, ServerSideApply=true]
```

- **ingress-nginx** (wave -2): `values.yaml`: `controller.service.type: LoadBalancer` (klipper binds node 80/443). 
- **cert-manager** (wave -2): chart `cert-manager` from `https://charts.jetstack.io`, values `crds.enabled: true`.
- **sealed-secrets** (wave -2): chart from `https://bitnami-labs.github.io/sealed-secrets`, namespace `sealed-secrets`, values `fullnameOverride: sealed-secrets-controller`.
- **cert-issuers** (wave -1, plain-manifest Application pointing at `kubernetes/infrastructure/cert-issuers/`): a `ClusterIssuer` `selfsigned`, a `Certificate` `homelab-root-ca` (isCA: true, 10-year duration, secret `homelab-root-ca` in `cert-manager` ns, issuerRef selfsigned), and `ClusterIssuer` `homelab-ca` (`ca.secretName: homelab-root-ca`). Every app Ingress uses `cert-manager.io/cluster-issuer: homelab-ca`.

**Step 5 — key custody.** `[new]`:

```bash
kubectl -n sealed-secrets get secret -l sealedsecrets.bitnami.com/sealed-secrets-key -o yaml \
  > /mnt/media/backups/…  # NO — /mnt/media not attached yet. Write to /srv/appdata/key-backups/ now;
                          # Phase 9 adds a copy to /mnt/media/backups; Phase 13 sends off-box copy.
sudo sh -c 'mkdir -p /srv/appdata/key-backups && chmod 700 /srv/appdata/key-backups'
kubectl -n sealed-secrets get secret -l sealedsecrets.bitnami.com/sealed-secrets-key -o yaml \
  | sudo tee /srv/appdata/key-backups/sealed-secrets-key.yaml >/dev/null
sudo cp /var/lib/rancher/k3s/server/token /srv/appdata/key-backups/k3s-token
kubectl -n cert-manager get secret homelab-root-ca -o yaml | sudo tee /srv/appdata/key-backups/root-ca.yaml >/dev/null
sudo chmod 600 /srv/appdata/key-backups/*
```

Export the CA *public* cert for device install: `kubectl -n cert-manager get secret homelab-root-ca -o jsonpath='{.data.tls\.crt}' | base64 -d > homelab-ca.crt` — install on user's devices (macOS/iOS/Windows/Android per-platform; leave the file in `docs/` — it's public material).

**Verification:** Argo UI reachable (`kubectl -n argocd port-forward svc/argocd-server 8443:443`, admin password from `kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d`); all platform apps **Synced/Healthy**; `curl -k https://192.168.1.4` returns ingress-nginx 404 (controller alive); `kubectl get clusterissuer homelab-ca` shows Ready. Test the GitOps loop end-to-end: commit a trivial values change, watch Argo auto-sync it.

**Rollback:** delete Applications from `argocd-apps/` (Argo prunes), or nuke namespace `argocd` and re-run Step 1–3. Old stack untouched.

---

### Phase 6 — Pilot app: Pi-hole (template for everything after)

**Prerequisites:** Phase 5 all-green.

Pi-hole is the pilot because it exercises every mechanism (PVC seed, sealed secret, LoadBalancer, Ingress) while the old Pi-hole keeps serving the LAN — zero user impact if it flops.

**Manifests** — `kubernetes/apps/pihole/` (all bound by a `kustomization.yaml` listing them; namespace `pihole`):

`pvc.yaml`:

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata: { name: pihole-etc, namespace: pihole }
spec:
  accessModes: [ReadWriteOnce]
  resources: { requests: { storage: 1Gi } }
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata: { name: pihole-dnsmasq, namespace: pihole }
spec:
  accessModes: [ReadWriteOnce]
  resources: { requests: { storage: 256Mi } }
```

`sealedsecret.yaml` — seal the web password (`[old]`):

```bash
kubectl create secret generic pihole-admin -n pihole \
  --from-literal=WEBPASSWORD='<generate: openssl rand -base64 24; note it for the user>' \
  --dry-run=client -o yaml > /tmp/s.yaml
make seal FILE=/tmp/s.yaml OUT=kubernetes/apps/pihole/sealedsecret.yaml && rm /tmp/s.yaml
```

`deployment.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata: { name: pihole, namespace: pihole }
spec:
  replicas: 1
  strategy: { type: Recreate }          # RWO volume: never two pods at once
  selector: { matchLabels: { app: pihole } }
  template:
    metadata: { labels: { app: pihole } }
    spec:
      containers:
        - name: pihole
          image: pihole/pihole:<PIN per §1.16>
          env:
            - { name: TZ, value: "Etc/UTC" }
            - { name: FTLCONF_dns_listeningMode, value: "all" }
            - name: WEBPASSWORD
              valueFrom: { secretKeyRef: { name: pihole-admin, key: WEBPASSWORD } }
          ports:
            - { name: dns-tcp, containerPort: 53, protocol: TCP }
            - { name: dns-udp, containerPort: 53, protocol: UDP }
            - { name: http,    containerPort: 80 }
          volumeMounts:
            - { name: etc-pihole,  mountPath: /etc/pihole }
            - { name: etc-dnsmasq, mountPath: /etc/dnsmasq.d }
          resources:
            requests: { cpu: 100m, memory: 128Mi }
            limits:   { memory: 512Mi }
          securityContext:
            capabilities: { add: [NET_ADMIN] }   # mirrors compose cap_add
          livenessProbe:
            exec: { command: [dig, "@127.0.0.1", "pi.hole"] }
            initialDelaySeconds: 30
      volumes:
        - name: etc-pihole
          persistentVolumeClaim: { claimName: pihole-etc }
        - name: etc-dnsmasq
          persistentVolumeClaim: { claimName: pihole-dnsmasq }
```

`service.yaml` (two Services: LB for DNS on the node IP, ClusterIP for web):

```yaml
apiVersion: v1
kind: Service
metadata: { name: pihole-dns, namespace: pihole }
spec:
  type: LoadBalancer
  selector: { app: pihole }
  ports:
    - { name: dns-tcp, port: 53, targetPort: 53, protocol: TCP }
    - { name: dns-udp, port: 53, targetPort: 53, protocol: UDP }
---
apiVersion: v1
kind: Service
metadata: { name: pihole-web, namespace: pihole }
spec:
  selector: { app: pihole }
  ports: [{ name: http, port: 80, targetPort: 80 }]
```

`ingress.yaml`:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: pihole
  namespace: pihole
  annotations: { cert-manager.io/cluster-issuer: homelab-ca }
spec:
  ingressClassName: nginx
  tls: [{ hosts: [pihole.lab.home.arpa], secretName: pihole-tls }]
  rules:
    - host: pihole.lab.home.arpa
      http:
        paths:
          - path: /
            pathType: Prefix
            backend: { service: { name: pihole-web, port: { number: 80 } } }
```

Plus `kubernetes/argocd-apps/app-pihole.yaml` (the §5 Application template: path `kubernetes/apps/pihole`, namespace `pihole`, `CreateNamespace=true`).

**Data seed** (generic procedure — reused by every stateful app; see §4):

```bash
kubectl -n pihole scale deploy pihole --replicas=0
PV1=$(kubectl -n pihole get pvc pihole-etc -o jsonpath='{.spec.volumeName}')
DIR1=$(kubectl get pv "$PV1" -o jsonpath='{.spec.hostPath.path}')   # under /srv/appdata/local-path/
# from [old]:
sudo rsync -a --delete /srv/containers/media/appdata/pihole/etc-pihole/ ops@192.168.1.4:/tmp/seed-etc/
# on [new]: sudo rsync -a /tmp/seed-etc/ "$DIR1"/ && sudo rm -rf /tmp/seed-etc
# (repeat for etc-dnsmasq.d → pihole-dnsmasq claim)
kubectl -n pihole scale deploy pihole --replicas=1
```

(Note: Argo's selfHeal will re-scale to 1 within its sync interval — for longer seeds, disable auto-sync on the app in the Argo UI first, re-enable after. Doing the copy in the gap is fine for small dirs; the *arr apps in Phase 9 use the disable-autosync route. PVC hostPath dirs are also directly writable at `/srv/appdata/local-path/<pvc-id>/` — resolve via the two commands above.)

**Verification:**

```bash
dig @192.168.1.4 doubleclick.net        # answers 0.0.0.0 (blocklist seeded correctly)
dig @192.168.1.4 github.com             # answers real IP (upstream resolution works)
# add pihole.lab.home.arpa → 192.168.1.4 as a local DNS record in the OLD pi-hole UI (temporary; re-pointed at cutover)
curl -kI https://pihole.lab.home.arpa   # 200/302 via ingress; cert issued by homelab-ca (kubectl -n pihole get certificate)
```

Point ONE test client (e.g. the user's phone via manual DNS) at `192.168.1.4` for a day of soak. **Do not** change router DHCP.

**Rollback:** delete `app-pihole.yaml` from Git (Argo prunes everything). Old Pi-hole never stopped serving.

---

### Phase 7 — CI images for custom apps (GHCR)

**Prerequisites:** Phase 5 (cluster can hold the pull secret); independent of Phase 6.

**Step 1** — identical workflow in `app-learning-review` and `app-stockalert-monitor` repos at `.github/workflows/publish.yml`:

```yaml
name: publish
on:
  push: { branches: [main] }
permissions: { contents: read, packages: write }
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: docker/login-action@v3
        with: { registry: ghcr.io, username: "${{ github.actor }}", password: "${{ secrets.GITHUB_TOKEN }}" }
      - uses: docker/build-push-action@v6
        with:
          context: .
          push: true
          tags: |
            ghcr.io/skyhaven-ltd/${{ github.event.repository.name }}:${{ github.sha }}
            ghcr.io/skyhaven-ltd/${{ github.event.repository.name }}:latest
```

**Step 2** — pull secret (packages default private; Open Question 4 to make public instead). User creates a classic PAT with `read:packages` only. Then:

```bash
kubectl create secret docker-registry ghcr-pull -n default \
  --docker-server=ghcr.io --docker-username=<gh-user> --docker-password=<PAT> \
  --dry-run=client -o yaml > /tmp/s.yaml
# Seal one copy per consuming namespace (sealed-secrets is namespace-scoped):
#   learning-review, stockalert — edit metadata.namespace before each seal.
make seal FILE=/tmp/s.yaml OUT=kubernetes/apps/learning-review/ghcr-pull.yaml   # ns learning-review
make seal FILE=/tmp/s.yaml OUT=kubernetes/apps/stockalert/ghcr-pull.yaml        # ns stockalert
rm /tmp/s.yaml
```

**Verification:** push a trivial commit to each app repo's `main`; `gh run watch`; `ghcr.io/skyhaven-ltd/app-learning-review:<sha>` and `...app-stockalert-monitor:<sha>` exist (`gh api /orgs/skyhaven-ltd/packages?package_type=container`). Record the two shas — Phase 8 pins them.

**Rollback:** delete workflow files. No runtime impact.

---

### Phase 8 — Migrate custom apps (learning-review, stockalert stack)

**Prerequisites:** Phases 6–7. Apply the §4 recipe; specifics below.

**8a. learning-review** — namespace `learning-review`:
- Deployment: image `ghcr.io/skyhaven-ltd/app-learning-review:<sha>`, `imagePullSecrets: [{name: ghcr-pull}]`, port 8080, env from sealed copy of the repo `.env`, PVC `learning-data` (2Gi) at `/data`, liveness+readiness probes `httpGet /health :8080` (compose healthcheck translated), `strategy: Recreate`. **No vault mount** (running container has none — Open Question 8).
- Service 8080 + Ingress `learning.lab.home.arpa` (add local DNS record in old Pi-hole AND in the new pihole's config as you go; from here on add each app's record in **both** so cutover is a no-op).
- Data seed: `[old]` `sudo tar -C /var/lib/docker/volumes/app-learning-review_learning_data/_data -czf - . | ssh ops@192.168.1.4 'cat > /tmp/ld.tgz'`, then extract into the PVC dir (scale-0 → extract → scale-1 per §4).
- Verify: `curl -k https://learning.lab.home.arpa/health` → 200; app UI loads with existing data visible; then `docker compose -f ~/repos/app-learning-review/docker-compose.yml down` `[old]`.

**8b. stockalert** — namespace `stockalert`, three Deployments, one directory:
- **ntfy**: image pinned `binwiederhier/ntfy:<PIN>`, args `[serve]`, env `NTFY_BASE_URL=http://192.168.1.3:8090` (the post-cutover identity — phones keep working after the IP swap; between now and cutover the *old* ntfy at `.3` keeps serving phones), `NTFY_UPSTREAM_BASE_URL=https://ntfy.sh`, `NTFY_LISTEN_HTTP=:80`; PVC `ntfy-cache` 1Gi at `/var/cache/ntfy`; ConfigMap or PVC for `/etc/ntfy` (seed from `~/repos/app-stockalert-monitor/ntfy/etc`); **Service type LoadBalancer, port 8090 → 80** (must be a raw LAN port, not Ingress — phones use plain HTTP on 8090).
- **flaresolverr**: pinned image, env `LOG_LEVEL=info`, `TZ=Europe/London`, ClusterIP Service `flaresolverr:8191`, no storage. Memory limit 2Gi (headless Chrome).
- **stock-checker**: image `ghcr.io/skyhaven-ltd/app-stockalert-monitor:<sha>`; ConfigMap `stockalert-config` from `config.yaml` + `products.txt` mounted read-only at `/app/config.yaml`, `/app/products.txt` (subPath mounts); SealedSecret from `.env` via `envFrom`; PVC `stockalert-data` 1Gi at `/app/data` (seed the SQLite dir); point it at in-cluster peers via env/config: ntfy → `http://ntfy.stockalert.svc.cluster.local:80`, flaresolverr → `http://flaresolverr.stockalert.svc.cluster.local:8191` (check `config.yaml`/`.env` for which key holds each URL and set accordingly in the ConfigMap/Secret copies — the values differ from compose where DNS names were `ntfy`/`flaresolverr`). **No `dns:` pin needed** — CoreDNS resolves public names correctly (proved in Phase 4 verification).
  - **Workflow change (flag to user):** `products.txt` edits become Git commits to the monorepo ConfigMap, not live file edits.
- Verify: stock-checker logs show a full successful check cycle including a walled retailer (FlareSolverr round-trip) and a test notification received on the phone **via the old ntfy** — wait, phones point at old `.3:8090`; to verify new ntfy end-to-end pre-cutover, temporarily subscribe the phone to `http://192.168.1.4:8090/<topic>`, confirm delivery, unsubscribe. Then `[old]` `docker compose -f ~/repos/app-stockalert-monitor/docker-compose.yml down` (old ntfy dies here: phones lose notifications until cutover **unless** you leave *only* ntfy running: `docker compose ... up -d ntfy` after the down — do that; it's stopped in Phase 11).

**Rollback (either app):** delete its Application from `argocd-apps/`, `docker compose up -d` the old stack. Data unchanged on old host until the compose `down`, and backed up since Phase 1 regardless.

---

### Phase 9 — Media disk move + media stack (plex, arrs, qbittorrent, audiobookshelf, syncthing)

**Prerequisites:** Phase 8 (routine established). **This is the highest-impact phase — the media disk physically changes VMs. Schedule a maintenance window.**

**Step 1 — write manifests first** (all 7 apps, per §4 recipe), commit with each Application file **named but with sync disabled** (`syncPolicy: {}` — no automated block — so Argo shows them OutOfSync but doesn't start pods before the disk exists). Key per-app deltas:

| App | Image (pin) | Workload notes | Services/Ingress | Volumes |
|---|---|---|---|---|
| plex | `lscr.io/linuxserver/plex` | `hostNetwork: true`, `dnsPolicy: ClusterFirstWithHostNet`, env PUID/PGID=1000, TZ | none (host net exposes 32400) | PVC `plex-config` 5Gi → `/config`; hostPath `/mnt/media/library` → `/media` (ro) |
| sonarr | `lscr.io/linuxserver/sonarr` | PUID/PGID 1000 | 8989 + `sonarr.lab.home.arpa` | PVC 2Gi → `/config`; hostPath `/mnt/media` → `/data` |
| radarr | `lscr.io/linuxserver/radarr` | same | 7878 + `radarr.lab...` | same pattern |
| prowlarr | `lscr.io/linuxserver/prowlarr` | same | 9696 + ingress | PVC 1Gi → `/config` only |
| qbittorrent | `lscr.io/linuxserver/qbittorrent` | env WEBUI_PORT=8080 | ingress for web; **LoadBalancer Service port 6881 TCP + 6881 UDP** | PVC 1Gi → `/config`; hostPath `/mnt/media` → `/data` |
| audiobookshelf | `advplyr/audiobookshelf` | | 80 + `abs.lab...` | PVCs → `/config`, `/metadata`; hostPath `/mnt/media` → `/data` (ro) |
| syncthing | `lscr.io/linuxserver/syncthing` | PUID/PGID 1000; local discovery lost (no broadcast) — global discovery + static peer addresses cover it | ingress for 8384; **LoadBalancer 22000 TCP + 22000 UDP** | PVC 1Gi → `/config`; hostPath `/mnt/media` → `/data` |

hostPath volume snippet (identical in-container paths to compose — preserves *arr path mappings and hardlinks):

```yaml
      volumes:
        - name: media
          hostPath: { path: /mnt/media, type: Directory }
```

**Step 2 — cold-stop old stack & final state copy** `[old]`:

```bash
cd /srv/containers/media && docker compose down       # media stack fully stopped (user-visible outage starts)
BK=/mnt/media/backups/pre-k8s-final-$(date +%F)
sudo mkdir -p "$BK" && sudo tar -C /srv/containers/media -czf "$BK/appdata-cold.tar.gz" appdata   # cold copy = consistent DBs
sudo umount /mnt/media                                 # nothing may hold it; lsof /mnt/media to confirm first
sudo sed -i 's|^.*/mnt/media|#&|' /etc/fstab           # old VM must not try to mount it on next boot
```

Then seed each app's `/config` PVC **from the cold tar over the network before moving the disk** — no: simpler and safer ordering: rsync appdata dirs to the new VM *now* (disk still mounted ro is fine too, but it's already unmounted — so re-mount ro if needed): practical sequence:

```bash
sudo mount -o ro /dev/sdb /mnt/media                   # remount ro for the copy window
for app in plex sonarr radarr prowlarr qbittorrent audiobookshelf syncthing; do
  sudo rsync -a /srv/containers/media/appdata/$app/ ops@192.168.1.4:/tmp/seed-$app/
done
sudo umount /mnt/media
```

(appdata lives on the *root* disk, not the media disk — the ro remount is only belt-and-braces against anything touching /mnt/media mid-move. The rsync source is the root disk; ~1.2 GB total, minutes on LAN.)

**Step 3 — move the disk** `[pve]`:

```bash
qm shutdown <OLD_VMID> --timeout 120   # full shutdown required to release the disk cleanly
qm move-disk <OLD_VMID> <MEDIA_DISK_SLOT> --target-vmid 200 --target-disk scsi2
qm start <OLD_VMID>
```

`[new]`: `echo '/dev/sdc /mnt/media ext4 defaults,noatime,nofail 0 2' | sudo tee -a /etc/fstab && sudo mkdir -p /mnt/media && sudo mount -a` — **verify device name first** with `lsblk` (930G disk; likely `sdc`), and fold this mount into `roles/base` vars so Ansible owns it going forward. Check contents: `ls /mnt/media` shows `library downloads backups`.

**Step 4 — seed PVCs & go live.** For each app: enable its Application (add the `automated` syncPolicy back, commit), let PVC bind, scale-0/seed-from-`/tmp/seed-<app>`/scale-1 per §4. Order: plex first (longest soak), then arr/qbt, then abs/syncthing.

**Verification (before declaring the window closed):**
- Plex: `http://192.168.1.4:32400/web` shows libraries with correct item counts; play a file; from a remote device on tailscale, confirm playback still direct (old VM still advertises the subnet route until Phase 11 — remote goes via `.3`? No: subnet route covers the whole /24, so remote clients reach `.4` fine through the old VM's route. Confirm in Plex remote settings.)
- Sonarr/Radarr: UI loads, series/movie lists intact, root folder `/data/...` shows green (path preserved), trigger a manual import scan — no path errors. Prowlarr: indexers test OK, and update its Sonarr/Radarr app-sync URLs to the new in-cluster DNS names (`http://sonarr.sonarr.svc.cluster.local:8989` etc.) — cross-app URLs are the one config that *must* change.
- qBittorrent: torrents resume/recheck against `/data/downloads`; port 6881 reachable (`nc -zv 192.168.1.4 6881`).
- Audiobookshelf: library plays. Syncthing: peers reconnect (may need address hint `tcp://192.168.1.4:22000` on peer devices until cutover restores `.3`).

**Rollback:** the full-reverse is documented and real: `qm shutdown 200` → `qm move-disk 200 scsi2 --target-vmid <OLD_VMID> --target-disk <MEDIA_DISK_SLOT>` → un-comment fstab on old → `docker compose up -d`. Appdata on the old root disk was never deleted (that happens only in Phase 12). Practice saying this out loud before Step 2.

---

### Phase 10 — Home Assistant — SKIPPED (2026-07-05, operator directive)

**Operator does not use Home Assistant — Phase 10 is skipped entirely.** HA is **not migrated** to the cluster; it is decommissioned with the old VM. The old `homeassistant` container keeps running on VM100 until Phase 11 step 1 (`docker compose down`), then dies with the rest of the old stack — no cluster manifest, no data seed, no Ingress. The empty `kubernetes/apps/homeassistant/` placeholder and Open Question 9 (HA hardware passthrough) are moot.

<details><summary>Original Phase 10 plan (not executed — kept for history)</summary>

**Prerequisites:** Phase 9 (pattern maturity; HA last because it's the most host-coupled).

Manifests per recipe with: `hostNetwork: true`, `dnsPolicy: ClusterFirstWithHostNet`, `securityContext: {privileged: true}` (mirrors compose; required for its discovery/integrations), PVC `ha-config` 5Gi → `/config` seeded from `appdata/homeassistant`, no Service/Ingress needed for LAN use (host net :8123) but add Ingress `ha.lab.home.arpa` → a headless Service targeting the pod for TLS convenience. Env `TZ`.

Stop old container first (`docker stop homeassistant && docker update --restart=no homeassistant`) since both bind host ports; seed; sync app.

**Verification:** `http://192.168.1.4:8123` — dashboard loads, entity history intact, integrations connected.

**Rollback:** `docker update --restart=unless-stopped homeassistant && docker start homeassistant`, remove Application.

</details>

---

### Phase 11 — Cutover: the IP swap

**Prerequisites:** Phases 6–9 verified (**Phase 10 skipped** — HA not migrated); every `.lab.home.arpa` record present in the **new** Pi-hole. This phase makes `192.168.1.3` mean "the cluster". Total planned outage: ~2–5 minutes of LAN DNS (clients fall back to secondary if the router advertises one). Note: step 1's `docker compose down` also kills the old `homeassistant` container permanently — intended (not migrated).

**Steps, in exact order:**

1. `[old]` Stop the last running old services: `docker compose -f ~/repos/app-stockalert-monitor/docker-compose.yml down` (kills the kept-alive old ntfy), `cd /srv/containers/media && docker compose down` (idempotent; already down since Phase 9 except pihole — pihole dies here; **LAN DNS now only from the router/secondary**), and disable Docker restart surprises: `sudo systemctl disable docker`.
2. `[old]` Re-address to `.13`: edit `/etc/netplan/50-cloud-init.yaml` (or the file found in Phase 1 backup) `192.168.1.3/24` → `192.168.1.13/24`, `sudo netplan apply`. Remove subnet route advertisement: `sudo tailscale set --advertise-routes=`.
3. `[any]` Re-address the cluster VM via IaC: in `terraform/terraform.tfvars` set `k8s_vm_ip = "192.168.1.3/24"`; `make infra-plan` (expect: cloud-init change only) `make infra-apply`; then `[pve]` `qm reboot 200` (cloud-init network changes apply on boot). Update `ansible/group_vars/k8s.yml` `node_ip: 192.168.1.3` and re-run `make configure` (k3s config + inventory refresh; tls-san already included `.3` since Phase 4 — this is why).
4. `[new]` Advertise the subnet route: `sudo tailscale set --advertise-routes=192.168.1.0/24` → approve in the Tailscale admin console (route moves from old node to new). Verify IPv6 RA setting matches old host if Hyperoptic direct-v6 path is in use for Plex: `sysctl net.ipv6.conf.ens18.accept_ra=2` (add to Ansible base role sysctls).
5. **Verify the new identity (checklist):**

```bash
dig @192.168.1.3 doubleclick.net         # 0.0.0.0 — cluster pihole is the LAN DNS
dig @192.168.1.3 pihole.lab.home.arpa    # 192.168.1.3 — records survived
curl -kI https://sonarr.lab.home.arpa    # ingress answers on .3
curl -sI http://192.168.1.3:8090/v1/health   # ntfy on its historic URL — phones reconnect on their own
# Phone: existing ntfy subscription (http://192.168.1.3:8090/<topic>) receives a test publish:
curl -d "cutover test" http://192.168.1.3:8090/<topic>
# Plex remote over tailscale from off-LAN device: direct play works (subnet route via new node)
kubectl get nodes -o wide                 # INTERNAL-IP 192.168.1.3, Ready
```

6. Update the router: nothing to change if DHCP DNS pointed at `192.168.1.3` (it still does, and that's now the cluster). **Check** the router doesn't have a DHCP reservation pinning the old VM's MAC to `.3` — if it does, delete/repoint it (the VMs have different MACs; a reservation would fight the static assignment).

**Rollback (symmetric, ~5 min):** old VM netplan back to `.3` + `netplan apply` + `systemctl enable --now docker` + compose up pihole; tfvars back to `.4` + apply + reboot 200; re-advertise route from old. Everything returns to the pre-phase state.

---

### Phase 12 — Decommission old Compose setup

**Prerequisites:** Phase 11 + **a 14-day soak** with zero rollbacks. Do not rush this phase; it deletes the safety net.

1. `[old]` Confirm nothing runs: `docker ps -q | wc -l` → 0.
2. Move any remaining wanted files off (e.g. `~/repos` working copies — they're all pushed to GitHub; verify `git -C <repo> status` clean for each).
3. `[pve]` `qm shutdown <OLD_VMID>`, leave it **stopped but existing** for 14 more days (snapshot from Phase 1 still inside it), then: `qm destroy <OLD_VMID> --purge` — **Warning:** this permanently deletes the old VM and its disks, including the original copies of all appdata and the Phase 1 root-disk backups (the `/mnt/media/backups` copies live on the media disk, which already moved — those survive). Confirm the restic backups (Phase 13) have run successfully before destroying.
4. Remove the old node from Tailscale admin console (`lnsvrlab01`).
5. Grow the cluster: `terraform.tfvars` `k8s_memory_mb = 16384`, `make infra-apply`, `qm reboot 200` if memory hot-plug doesn't apply it.
6. Repo hygiene: delete `compose/` directory and stale `scripts/`/`systemd/` entries from the monorepo (Git history preserves them), update README to describe the k8s world.

**Verification:** all apps green in Argo; `free -g` on node shows 16 GiB; monorepo contains no live references to compose.

**Rollback:** before `qm destroy`, full rollback is still possible (start old VM, Phase 11 reverse). After `qm destroy`, rollback is restore-from-backup only.

---

### Phase 13 — Ops hardening + final validation

**Prerequisites:** Phase 12.

1. **restic backups** (add to `roles/base`): systemd service+timer `restic-appdata.timer` daily 03:00 — `restic -r /mnt/media/backups/restic-appdata backup /srv/appdata --exclude /srv/appdata/local-path/*/plex-config/*/Cache` with `RESTIC_PASSWORD_FILE=/root/.restic-pass` (generate once, add to layer-3 backup set); weekly `restic forget --keep-daily 14 --keep-weekly 8 --prune`. First run manual; verify `restic snapshots` lists one.
2. **vzdump schedule** `[pve]`: Datacenter → Backup (or `/etc/pve/jobs.cfg`): weekly, VM 200 only, mode snapshot, target = backup storage from Phase 0. Set `backup=0` on scsi2: `qm set 200 --scsi2 <current-volume-spec>,backup=0` (fetch current spec from `qm config 200`). Verify one manual run completes and its size ≈ scsi0+scsi1 used space, not 1 TB.
3. **Off-box crown jewels** (Open Question 6 destination): `/srv/appdata/key-backups/*`, `/root/.restic-pass`, `terraform/terraform.tfstate`, copy of this doc.
4. **Reboot drill (mandatory):** `[pve]` `qm reboot 200`. Within ~3 minutes, without any human action: node Ready, all Argo apps Healthy, `dig @192.168.1.3 github.com` works, Plex plays, phone ntfy test delivers. This proves power-loss recovery (on_boot=true → VM starts → k3s starts → pods start → pihole serves; node DNS independence per §1.12 means no deadlock).
5. **Disaster-recovery doc:** write `docs/disaster-recovery.md`: rebuild = `make infra-apply` → `make configure` → restore sealed-secrets key + k3s token → Argo re-syncs everything → restic restore `/srv/appdata` → reattach media disk. Every input it needs must exist in Git or the layer-3 backup set — audit that claim.

**Final validation checklist** (all must pass):

- [ ] `kubectl get applications -n argocd` — every app Synced + Healthy
- [ ] Git loop: image-tag bump commit on a custom app → live in-cluster within 5 min, no kubectl
- [ ] LAN DNS + ad-blocking via `192.168.1.3` from ≥ 2 client devices
- [ ] All `*.lab.home.arpa` ingresses serve with homelab-ca certs (no warnings on CA-trusting devices)
- [ ] Plex: local + remote (tailscale, direct) playback
- [ ] Sonarr/Radarr/Prowlarr/qBittorrent: end-to-end grab→download→import of one item
- [ ] StockAlert: scheduled check ran, notification on phone via `http://192.168.1.3:8090`
- [ ] learning-review `/health` 200 + data intact; audiobookshelf plays; syncthing peers in sync
- [ ] `restic snapshots` ≥ 1; vzdump job ≥ 1 success; key-backups present off-box
- [ ] Reboot drill passed
- [ ] Old VM destroyed; tailnet shows `lnsvrk8s01` with subnet route; no `lnsvrlab01`

---

## 4. Per-App Migration Recipe (generic)

Compose→Kubernetes translation table:

| Compose construct | Kubernetes equivalent |
|---|---|
| `services.<x>` | `Deployment` (replicas 1, `strategy: Recreate` when any RWO PVC is mounted) in namespace `<x>` (or shared ns for tightly-coupled stacks like stockalert) |
| `image:` | same image, **pinned tag** (§1.16); `build:` → GHCR image from CI (Phase 7 pattern) |
| `ports: "H:C"` | ClusterIP Service port C + Ingress `<app>.lab.home.arpa` for HTTP UIs; **LoadBalancer Service** for raw TCP/UDP protocol ports (DNS 53, torrent 6881, syncthing 22000, ntfy 8090) |
| `network_mode: host` | `hostNetwork: true` + `dnsPolicy: ClusterFirstWithHostNet` (only plex, homeassistant) |
| `environment:` | `env:` inline for non-secrets; secrets → SealedSecret + `envFrom`/`secretKeyRef` |
| `env_file: .env` | `kubectl create secret generic --from-env-file` → kubeseal |
| named volume / appdata bind | PVC (local-path); size = current use × 4 rounded up |
| ro config-file bind | ConfigMap with `subPath` mount |
| `/mnt/media` bind | `hostPath` volume, **identical container path** as compose |
| `depends_on` | drop it — probes + restarts converge; in-cluster DNS names replace compose service names (`<svc>.<ns>.svc.cluster.local`) — **grep app config for old hostnames** |
| `restart: unless-stopped` | free (Deployment) |
| `healthcheck` | livenessProbe + readinessProbe |
| `cap_add` / `privileged` | `securityContext.capabilities.add` / `privileged: true` |
| `dns:` overrides | drop — CoreDNS forwards to node's static 1.1.1.1 (§1.13) |

Checklist per app:

1. `mkdir kubernetes/apps/<app>` → `kustomization.yaml`, `deployment.yaml`, `pvc.yaml`, `service.yaml`, `ingress.yaml` (+ `configmap.yaml`/`sealedsecret.yaml` as needed). Set resource requests (start: cpu 100m / mem 128Mi req; mem limit ≈ observed × 3) — no CPU limits (throttling hurts more than it helps on one node).
2. Add DNS record `<app>.lab.home.arpa → <cluster IP>` in Pi-hole (both old and new until cutover).
3. Add `kubernetes/argocd-apps/app-<app>.yaml` — **with auto-sync disabled if data must be seeded**.
4. Commit → Argo creates namespace + PVCs. Find each PVC's hostPath: `kubectl get pv $(kubectl -n <ns> get pvc <claim> -o jsonpath='{.spec.volumeName}') -o jsonpath='{.spec.hostPath.path}'`.
5. Stop the old container (`docker stop <app>` — leave the rest of the old stack running). Cold-copy state: rsync/tar old data dir → PVC hostPath dir on the node. Preserve ownership: linuxserver images expect uid/gid 1000 inside `/config` (`chown -R 1000:1000` after copy); others match whatever the old data had.
6. Enable/scale the app (auto-sync on, replicas 1). Watch `kubectl -n <ns> logs deploy/<app> -f` for a clean start.
7. Verify app-specific function (UI, data present, one real operation), update any cross-app URLs to cluster DNS names.
8. Only then declare the old container permanently dead (`docker update --restart=no <app>`). It is *removed* in Phase 11/12, not before.
9. Add the app to the Phase 13 validation checklist.

---

## 5. Risks & Homelab-Specific Caveats

- **Single point of failure is total.** One Proxmox host, one VM, one node: any hardware death takes everything. Mitigation is recovery speed, not availability: Git holds the entire definition, restic + vzdump + key backups make rebuild ≈ 1 hour. Accept this; don't fake HA on one box.
- **The media disk is a second SPOF with no backup.** 761 GB of media is explicitly unbacked (existing posture). The `backups/` directory *rides on the media disk* — so app-state backups die with that disk. Layer-2 vzdump (on Proxmox storage) and layer-3 off-box copies exist precisely to cover that; don't skip Phase 13.3.
- **Power loss / reboot behavior** is engineered, then *drilled* (Phase 13.4): VM `on_boot=true`, k3s systemd auto-start, node DNS never depends on its own Pi-hole, `nofail` on the media mount so a dead media disk can't hang boot. The drill is mandatory because untested recovery paths don't exist.
- **Memory pressure during co-existence** (both VMs up, Phases 3–11): watched via Phase 0's host-RAM check + old-VM shrink. If the Proxmox host OOMs or heavily swaps (`free` on pve), pause and shrink further — a swapping hypervisor corrupts timing everywhere.
- **k3s upgrades are your job now.** Unattended-upgrades covers the OS only. Process: bump `k3s_version` in group_vars, `make configure`, watch node. Do it at least quarterly; Argo/chart pins likewise (`docs/versions.md` is the ledger).
- **Argo self-heal fights manual kubectl edits** — by design. The escape hatch during incidents: disable auto-sync on one app in the UI, fix, then reconcile Git. Never leave it disabled.
- **Compose fallback lives until Phase 12** — stopped, not deleted. The old VM at `.13` can resurrect any app in minutes throughout the soak period. After `qm destroy`, Git + backups are the only fallback.
- **Sealed-secrets key loss = every secret in Git is garbage.** The key backup (Phases 5/13) is not optional; test-decrypt one secret from a restored key during the reboot-drill week.
- **Browser trust warnings** on devices without the homelab root CA installed (§1.9); fixed per-device once, or made moot by a future real-domain Let's Encrypt swap.
- **hostNetwork pods (plex, HA) bypass NetworkPolicy/Service abstractions** — accepted mirror of today's compose posture; revisit if the cluster ever grows.
- **Behavioral change:** config edits (e.g. `products.txt`, adding an app) are now Git commits, not SSH file edits. That's the point — but note the muscle-memory shift.

---

## 6. Open Questions (answer before the agent starts)

**All answered 2026-07-05 — full detail in §0.2. Quick index:**

1. **SSH access to Proxmox host:** confirm key-based root SSH to `lnproxlab01` (`100.82.112.92`) from `lnsvrlab01` works, or provide credentials/console access to set it up (Phase 0 hard-blocks without it). Also confirm its LAN IP. → **Answered.** Workstation is the desktop (WSL2 Ubuntu-24.04), not `lnsvrlab01`. LAN IP `192.168.1.2`. Key generated and installed, verified over LAN + Tailscale. See §0.2.
2. **Proxmox host capacity:** unknown RAM/CPU/storage totals — Phase 0 discovers; **but** if you already know the host has < 34 GiB RAM, approve the old-VM shrink to 6 GiB up front (brief full outage at Phase 0). → **Answered/discovered.** 23 GiB RAM, 12 cores — shrink approved but **not yet executed**. Storage discovery surfaced **Blocker 1** (§0.2) — worse than anticipated, needs a decision before Phase 3.
3. **Public domain:** do you own a domain (and is it on Cloudflare) you'd like used for `*.lab.<domain>` with Let's Encrypt DNS-01 instead of the internal CA? (Plan proceeds with internal CA either way; this swaps one issuer file later.) → **Answered: no domain, use internal CA** (plan's default path, unchanged).
4. **GHCR visibility:** keep `app-learning-review`/`app-stockalert-monitor` images private (requires you to mint a `read:packages` PAT for the pull secret, Phase 7) or make the packages public (no PAT needed)? Default if unanswered: private + PAT. → **Answered: make public.** Drop the `ghcr-pull` imagePullSecret/PAT steps in Phase 7.
5. **Tailscale auth key:** generate a reusable auth key in the admin console for Phase 4 (Settings → Keys), or pre-approve interactive `tailscale up` on the new VM. → **Not yet answered** — still needed before Phase 4. (Not to be confused with the operator's separate question about *whether* generated keys can live in Git — see §0.2 item 5: no, they can't, keep this one as an env var too.)
6. **Off-box backup destination** for crown jewels (sealed-secrets key, tfstate, restic password): options — private GitHub repo (encrypted with age), a cloud drive, a USB stick. Name one; Phase 13.3 blocks without it. → **Answered: private GitHub repo (age-encrypted), repo-level, in `skyhaven-ltd`.** GitHub Actions Secrets ruled out — write-only, can't be retrieved for restore. See §0.2.
7. **Proxmox Backup Server:** does one exist on your network? If yes, vzdump targets it (better dedup/retention); if no, which Proxmox storage should hold weekly VM backups (Phase 0 lists candidates)? → **Answered: no PBS, single host.** Target storage still **unresolved** — tangled up with Blocker 1 (§0.2), both existing storages are nearly full.
8. **learning-review Obsidian vault mount:** compose declares an optional read-only vault bind but the running container doesn't have it. Confirm it's genuinely unused (migrate without, as planned) — if it *is* wanted, state the vault's path and how it reaches the new VM (likely via syncthing to a `/mnt/media` path). → **Answered: confirmed unused,** migrate without it.
9. **Home Assistant hardware:** any USB/Zigbee/Bluetooth devices attached to integrations? (None visible from container config; if yes, Proxmox USB passthrough to VM 200 must be added in Phase 10 — say so now.) → **Answered: no HA hardware integrations in use.** (Separately, Phase 0 discovery found an *undocumented* iGPU passthrough for Plex — Blocker 2 in §0.2, unrelated to this question.)
10. **Plex claim:** confirm the Plex server is claimed to your account (config PV migration preserves identity, so no re-claim expected — this is just the "if it asks, sign in and claim" heads-up). → **Acknowledged.**
