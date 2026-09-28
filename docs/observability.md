# Observability

Alerts route through Alertmanager to ntfy (`monitoring` topic). Dashboards live
in Grafana under the **Homelab** folder; **Homelab Mission Control** is the one
to open first.

Everything here exists because the July 2026 cluster rebuild broke three things
that stayed broken for a day without anyone noticing: remote `kubectl`, the
BookBuddy generation queue, and Sonarr's size guardrails.

## Where the metrics come from

| Signal | Source |
| ------ | ------ |
| Host, pod, and cluster health | kube-prometheus-stack (node-exporter, kube-state-metrics) |
| Tailnet, API certificate, generation worker, Sonarr guardrails | `homelab-metrics.timer` on the k3s node |
| BookBuddy generation queue depth and job age | BookBuddy `/metrics`, scraped via ServiceMonitor |
| Physical disk SMART and NVMe health | `disk_health` role on the Proxmox host, scraped as `proxmox-disk-health` |

The `homelab_metrics` Ansible role installs a script that writes
`/var/lib/node_exporter/textfile_collector/homelab.prom` every minute.
node-exporter already bind-mounts the host root, so it reads that path through
`--collector.textfile.directory` with no extra volume.

Check it by hand:

```sh
ssh ops@192.168.1.3 'sudo systemctl start homelab-metrics.service \
  && cat /var/lib/node_exporter/textfile_collector/homelab.prom'
```

If `homelab_metrics_last_run_timestamp_seconds` stops advancing, every
`homelab_*` alert is blind — `HomelabMetricsStale` covers exactly that.

## Disk health

The k3s VM only sees QEMU virtual disks, so SMART data is not available inside
it. The physical drives are on the Proxmox host `lnproxlab01`:

| Host device | Drive | Used by the k3s VM as |
| ----------- | ----- | --------------------- |
| `/dev/sda` | Seagate ST1000LM014 1TB HDD | `/dev/sdc`, mounted at `/mnt/media` |
| `/dev/nvme0` | WD SN740 256GB NVMe | Storage for `/` and `/srv/appdata` |

The `disk_health` Ansible role installs Debian's `prometheus-node-exporter`
with only the textfile collector enabled, plus the `smartmon` and `nvme`
collector timers from `prometheus-node-exporter-collectors`. Both timers run
every 15 minutes. The exporter listens on `192.168.1.2:9100` and a systemd
`IPAddressAllow` drop-in only accepts the k3s node. The platform deploy
workflow applies the role with `inventory/proxmox.yml` and `--tags disk_health`.

Grafana's **Disk Health** dashboard in the **Homelab** folder shows the drives,
their temperatures, error counters, NVMe wear and the VM's filesystem usage.

Check it by hand:

```sh
ssh root@192.168.1.2 'systemctl start prometheus-node-exporter-smartmon.service \
  prometheus-node-exporter-nvme.service \
  && cat /var/lib/prometheus/node-exporter/{smartmon,nvme}.prom'
```

The media HDD reported 1179 lifetime uncorrectable errors when monitoring was
added, so `DiskUncorrectableErrorsIncreasing` alerts on growth, not on the
absolute value.

## Reaching the cluster over Tailscale

The node advertises `192.168.1.0/24`, but using that route needs
`--accept-routes` on every client. The API server certificate therefore also
covers the node's tailnet address and its MagicDNS name
(`lnsvrk8s01.<tailnet>.ts.net`), so `kubectl` works over the tailnet directly:

```sh
kubectl config set-cluster default --server=https://<tailnet-ipv4>:6443
```

A rebuild re-registers the node and changes that address. The `tailscale` role
reads the current one and the `k3s` role puts it in `tls-san`, discarding the
old certificate so k3s reissues it. `ApiServerCertMissingTailnetName` fires if
the two ever drift apart.

MagicDNS names only resolve on clients with `--accept-dns=true`. Enabling that
used to cost you `lab.skyhaven.ltd`, because Tailscale took over DNS and had
nowhere to send those queries. The `tailscale_dns_split_nameservers` resource in
`terraform/tailscale` points that domain at Pi-hole on the node's tailnet
address, so MagicDNS and the lab domain now coexist.

## Alerts

| Alert | Meaning |
| ----- | ------- |
| `TailscaleBackendDown` | Node is off the tailnet; nothing is reachable remotely |
| `TailscaleSubnetRouteNotApproved` | Route advertised but unapproved; re-run the tailscale Terraform stack |
| `ApiServerCertMissingTailnetName` | Remote `kubectl` will fail TLS; re-run the `k3s` role |
| `HomelabMetricsStale` | The exporter stopped; other homelab alerts are blind |
| `BookBuddyWorkerTimerMissing` | Worker not installed; queued jobs are never claimed |
| `BookBuddyWorkerRunFailing` | Worker runs, but every run errors |
| `BookBuddyGenerationJobStalled` | A job sat pending over 30 minutes |
| `BookBuddyGenerationJobStuckRunning` | A worker died mid-job; nothing resets the claim |
| `BookBuddyGenerationJobsFailing` | Jobs are completing as failed |
| `SonarrQualityDefinitionsUncapped` | HD qualities have no maximum size |
| `SonarrSeriesOffManagedProfile` | Series are on Sonarr's unscored default profile |
| `DiskHealthExporterDown` | Proxmox disk exporter unreachable; disk alerts are blind |
| `DiskHealthDataStale` | A SMART or NVMe collector has not written for over an hour |
| `DiskSmartUnhealthy` | A drive failed its SMART overall health check |
| `DiskPendingOrUncorrectableSectors` | The HDD has unreadable sectors |
| `DiskReallocatedSectorsIncreasing` | The HDD remapped sectors in the last day |
| `DiskUncorrectableErrorsIncreasing` | The HDD reported new uncorrectable errors in the last day |
| `DiskTemperatureHigh` | The HDD is above 58C for 30 minutes |
| `NvmeCriticalWarning` | The NVMe raised a critical warning |
| `NvmeMediaErrors` | The NVMe has recorded media errors |
| `NvmeSpareLow` | NVMe spare blocks are at the drive's threshold |
| `NvmeWearHigh` | NVMe has used over 80% of its rated endurance |
| `NvmeTemperatureHigh` | The NVMe is above 70C for 15 minutes |

## The BookBuddy generation worker

The worker runs on the node, not in the cluster, because it spends a Codex
subscription seat rather than per-token API credit. Its `CODEX_AUTH_FILE` is an
interactive login artefact that is not in Key Vault, so the role is gated behind
an explicit tag and **the platform deploy workflow does not install it**. After a
rebuild it must be reinstalled by hand:

```sh
cd ansible
export BOOKBUDDY_WORKER_TOKEN="$(kubectl get secret bookbuddy-env -n bookbuddy \
  -o jsonpath='{.data.WORKER_TOKEN}' | base64 -d)"
export CODEX_AUTH_FILE="$HOME/.codex/auth.json"
ansible-playbook -i inventory/hosts.yml site.yml --tags bookbuddy_worker
```

`BookBuddyWorkerTimerMissing` is what tells you this was forgotten.
