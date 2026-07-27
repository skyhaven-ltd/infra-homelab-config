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
