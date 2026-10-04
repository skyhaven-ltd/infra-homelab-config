# Orca remote server

Plan for running an always-on Orca runtime on `lnsvrk8s01`, so that agents,
worktrees and scheduled automations live on the homelab instead of the gaming
desktop. The desktop and the Orca iOS app become clients of the same runtime and
the desktop can sleep or power off. Nothing in this document is implemented yet.

Assessed on 2026-10-04.

## Decision

Run Orca as an Ansible-managed **systemd service on the k3s host**, not as a
Kubernetes workload. It follows the opt-in host-worker pattern already used by
`bookbuddy_worker` and `backlog_portal_worker`.

| | |
| --- | --- |
| Host | `lnsvrk8s01` (`192.168.1.3`, tailnet `100.91.71.76`) |
| Form | systemd unit `orca-serve.service`, Ansible role `orca_server` |
| Service account | `orca`, system user, no `sudo`, no kubeconfig |
| Home / state | `/srv/appdata/orca` (appdata disk, not root) |
| Listener | `ws://0.0.0.0:6768`, reached over Tailscale only |
| Memory cap | `MemoryHigh=3G`, `MemoryMax=4G` |

## Why not Kubernetes

Orca does document a container route: extract the AppImage, because there is no
FUSE device; run under an init process, so finished PTY children are reaped;
no privileged mode needed. It would work here, but it is the wrong fit:

- **Restarts kill running agents.** In a container Orca has no systemd
  daemon-scope isolation, so every pod restart tears down every agent session.
  Argo CD self-heal, image bumps, evictions and k3s upgrades would all interrupt
  long-running agents and automations. On the host with lingering enabled, agent
  PTYs run in `orca-daemon-*.scope` and survive restarts of the service.
- **The image becomes a dev box.** Agents need whatever the repositories need
  (git, node, python, az, terraform, kubectl, gh, and the claude and codex
  CLIs). Baking that into an image means a rebuild for every new tool, and it
  conflicts with the cluster's `readOnlyRootFilesystem` / drop-`ALL` hardening.
- **Upgrades fight GitOps.** An Orca upgrade forward-migrates `orca-data.json`.
  A rollback needs the binary *and* a pre-upgrade profile archive, which is
  operator work, not something self-heal should reconcile.
- **Remote servers are beta** and upstream's supported headless path is systemd.

A dedicated Proxmox VM would give the strongest isolation from the control
plane. It was not chosen because the k3s node has the headroom (below) and the
host-worker pattern already exists. Revisit if agents need Docker, or if the
node's memory headroom shrinks.

## Memory assessment

Taken from Prometheus (kube-prometheus-stack, 15-day retention) for
2026-09-19 to 2026-10-04:

| Metric | Value |
| --- | --- |
| `MemTotal` | 15.6 GiB |
| `MemAvailable` average / 5th percentile / minimum | 8.17 / 7.89 / **7.24 GiB** |
| Daily minimum `MemAvailable` | 7.2 to 8.0 GiB, flat, no trend |
| Pod working set, peak | 7.05 GiB |
| Non-pod usage (k3s, containerd, kernel, host workers), peak | 2.3 GiB |
| Swap | none |
| OOM kills | 0 |
| Memory PSI (`some` / `full`) | about 0 |

Largest namespaces by peak working set: `monitoring` 1.42 GiB, `plex` 1.17,
`terraria` 1.15, `argocd` 0.80; everything else is under 0.6 GiB. Pod memory
*limits* add up to about 125% of capacity, but actual use has never come close.

These are estimates, not measured on this node:

| Component | Estimated memory |
| --- | --- |
| Orca server and Xvfb | 0.3 to 0.6 GiB |
| Each claude or codex agent CLI | 0.2 to 0.5 GiB |
| Builds and tests run by agents (npm, terraform, pytest) | 0.5 to 2 GiB while running |

Two or three agents working at once land around 1.5 to 3 GiB, well inside the
roughly 7 GiB that was always free.

### Why the cap is mandatory

The node has no swap, so running out of memory means OOM kills with no slow
degradation first. Kubernetes gives Burstable and BestEffort pods an
`oom_score_adj` close to 1000, while a systemd service runs at 0. The kubelet
also evicts pods when the node is under memory pressure, even when a host
process caused it. **An uncapped runaway agent build would get Plex or Home
Assistant killed, not Orca.** `MemoryHigh` throttles and reclaims Orca's own
cgroup first. `MemoryMax` confines any OOM kill to Orca's processes. Even at
the worst case seen in the 15 days, the pods keep about 3 GiB of headroom.

### Re-check before implementing

The data above will be stale. Re-run against Prometheus:

```bash
kubectl -n monitoring port-forward svc/monitoring-kube-prometheus-prometheus 19090:9090
```

```promql
min_over_time(node_memory_MemAvailable_bytes[15d]) / 2^30
quantile_over_time(0.05, node_memory_MemAvailable_bytes[15d]) / 2^30
increase(node_vmstat_oom_kill[15d])
max_over_time(rate(node_pressure_memory_waiting_seconds_total[5m])[15d:5m])
sort_desc(max_over_time(sum by (namespace) (container_memory_working_set_bytes{container!="",container!="POD"})[15d:5m]) / 2^30)
```

Go ahead if the 15-day minimum `MemAvailable` is still at least 5 GiB.
Otherwise lower `MemoryMax`, or reconsider the dedicated VM.

## Disk

The root disk (`/dev/sda1`, 38G) was 70% used with 12G free; repositories,
worktrees and `node_modules` would fill it quickly. `/srv/appdata` (`/dev/sdb`,
59G) had 49G free, so the `orca` home lives there.

`backup-appdata.sh` only archives `/srv/appdata/local-path`, so
`/srv/appdata/orca` is **not** backed up. Repositories are recoverable from Git.
The Orca profile (`~/.config/orca`, `~/.config/Orca`) only holds pairings and
settings, so losing it means re-pairing clients. Add it to the backup only if
that becomes painful.

## Implementation

### Role layout

```
ansible/roles/orca_server/
  defaults/main.yml
  handlers/main.yml
  tasks/main.yml
  templates/orca-serve.service.j2
```

Wire it into the `k8s` play in `site.yml`, opt-in like the other workers so a
plain `make configure` never touches it:

```yaml
    - role: orca_server
      tags: [orca_server]
      when: "'orca_server' in ansible_run_tags"
```

Add a Makefile target next to `bookbuddy-configure`:

```make
orca-configure:
	cd $(ANSIBLE_DIR) && ansible-playbook -i inventory/hosts.yml site.yml --tags orca_server
```

### Defaults

```yaml
orca_server_user: orca
orca_server_group: orca
orca_server_home: "{{ appdata_mount }}/orca"
orca_server_install_root: /opt/orca
orca_server_version: ""            # pin to a release tag, e.g. v1.x.y
orca_server_port: 6768
orca_server_pairing_address: "{{ tailscale_hostname }}.{{ tailscale_magicdns_suffix }}"
orca_server_memory_high: 3G
orca_server_memory_max: 4G
orca_server_cpu_quota: 400%        # 4 of 8 cores
orca_server_claude_code_version: ""
orca_server_codex_version: "{{ backlog_portal_worker_codex_version }}"
```

### Tasks

1. **Packages.** `xvfb`, `git`, `curl`, `file`, `jq`, `nodejs`, `npm`, plus
   the Electron runtime libraries upstream lists. Ubuntu 24.04 uses the `t64`
   names, so check each with `apt-cache policy` on the node:
   `libgtk-3-0t64 libnss3 libatk1.0-0t64 libatk-bridge2.0-0t64 libgbm1
   libasound2t64 libxtst6 libcups2t64 libdrm2 libxkbcommon0 libpango-1.0-0
   libcairo2 libatspi2.0-0t64 libxcomposite1 libxdamage1 libxfixes3
   libxrandr2 libxrender1 libx11-xcb1 libxcb-dri3-0 libxss1`.
2. **User.** A system user and group `orca` with home `orca_server_home`,
   shell `/usr/sbin/nologin`, not in `sudo`. Run `loginctl enable-linger orca`
   so agent daemon scopes outlive the service process.
3. **Binary.** Download the pinned `orca-linux.AppImage` release to a
   temporary file and check it with `file`. Run `--appimage-extract` into
   `/opt/orca/<version>/`, then point the symlink `/opt/orca/current` at it.
   Keep everything root-owned and read-only to `orca`. Extracting means no FUSE
   mount: the setuid `fusermount` would be blocked by `NoNewPrivileges`, and an
   in-place AppImage overwrite can corrupt a running mount. The previous
   version directory doubles as a binary rollback.
4. **Agent CLIs.** Install `@anthropic-ai/claude-code` and `@openai/codex`
   globally with npm at pinned versions, the same way
   `backlog_portal_worker` pins codex.
5. **Unit.** Template `orca-serve.service`, enable it, and restart it from a
   handler.

### Unit template

Upstream's minimal unit, plus the memory caps and the hardening the existing
workers use. Agents need to write to their home directory only.

```ini
[Unit]
Description=Orca runtime server
After=network-online.target tailscaled.service
Wants=network-online.target
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
User={{ orca_server_user }}
Group={{ orca_server_group }}
WorkingDirectory={{ orca_server_home }}
Environment=HOME={{ orca_server_home }}
Environment=LIBGL_ALWAYS_SOFTWARE=1
ExecStart={{ orca_server_install_root }}/current/AppRun serve --port {{ orca_server_port }} --pairing-address {{ orca_server_pairing_address }}
StandardOutput=journal
StandardError=journal
KillMode=mixed
Restart=on-failure
RestartPreventExitStatus=3
RestartSec=5
MemoryHigh={{ orca_server_memory_high }}
MemoryMax={{ orca_server_memory_max }}
MemorySwapMax=0
CPUQuota={{ orca_server_cpu_quota }}
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths={{ orca_server_home }}

[Install]
WantedBy=multi-user.target
```

`ProtectHome=true` hides `/home`, `/root` and `/run/user`, but does not touch
`/srv/appdata`. Lingering daemon scopes may need `/run/user/<uid>`. If agents
fail to start under the scope, relax this to `ProtectHome=read-only` first.

### First run

The pairing URL holds device credentials and E2EE material. Treat it as a
password and never paste it into an issue, PR or log.

```bash
make orca-configure
ssh ops@192.168.1.3 'sudo journalctl -u orca-serve -n 50 --no-pager'
```

The journal prints `Orca server ready`, the bound and advertised endpoints, and
an `orca://pair?code=...` URL. Pair the desktop app and the iOS app over the
tailnet. Then open an Orca terminal on the server and run `claude` and
`codex login` once each, so the subscription credentials persist in
`/srv/appdata/orca`.

Install shared agent skills headlessly:

```bash
orca skills install --all
```

### Networking

Clients reach `100.91.71.76:6768` (or the MagicDNS name) directly over
Tailscale. Do **not** put Orca behind `ingress-nginx`, and do not forward the
port to the internet. If it ever has to go through a proxy, the proxy must
support WebSocket upgrades, use `wss://`, and keep pairing URLs out of access
logs.

### Upgrades and rollback

1. Stop `orca-serve` and archive `~/.config/orca` and `~/.config/Orca` to
   `profile-<timestamp>.tgz`.
2. Extract the new version beside the old one, then move the `current`
   symlink.
3. Start the service and check the journal.

To roll back, move the symlink back **and** restore the profile archive. The
binary alone is not enough, because `orca-data.json` migrates forward. Paired
clients reconnect after an upgrade without re-pairing.

## Verification

- `systemctl status orca-serve` is active, and the journal shows
  `Orca server ready`.
- `systemctl show orca-serve -p MemoryHigh -p MemoryMax` shows the caps.
- The iOS app connects with the desktop powered off.
- A scheduled automation (`orca automations create ...`) fires with the
  desktop off.
- `sudo -l -U orca` reports no sudo rights, and the `orca` user cannot read
  `/etc/rancher/k3s/k3s.yaml`.
- A week later, re-run the PromQL above: no new OOM kills and no pod restarts
  caused by memory.

## Known limitations

- **No push notifications.** Upstream runs agent-finish detection in the
  desktop renderer, so a headless server can't send background pushes to the
  iOS app.
- **Remote servers are beta.**
- **No Docker for agents.** The node runs containerd for k3s only, so agent
  tasks that need Docker belong on a dedicated VM.
- **Memory figures are a snapshot.** They cover only 15 days, so rare peaks
  such as heavy Terraria sessions or several Plex transcodes at once may be
  missing.

## References

- [Headless Linux server reference](https://github.com/stablyai/orca/blob/main/docs/reference/headless-linux-server.md)
- [Remote Orca Servers](https://www.onorca.dev/docs/remote-servers)
- [Ways to run Orca](https://www.onorca.dev/docs/ways-to-run)
- [Scheduled automations](https://www.onorca.dev/docs/cli/automations)
