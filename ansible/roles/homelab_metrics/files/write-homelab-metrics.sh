#!/bin/bash
# Publishes homelab-specific health signals for node_exporter's textfile
# collector. Everything here is a state that broke silently after the cluster
# rebuild: the tailnet path to the API server, the BookBuddy generation worker,
# and Sonarr's size caps and quality profile assignment.
set -euo pipefail

: "${TEXTFILE_DIR:?TEXTFILE_DIR is required}"
: "${SONARR_HOST:?SONARR_HOST is required}"
: "${SONARR_PROFILE:?SONARR_PROFILE is required}"
SONARR_API_KEY="${SONARR_API_KEY:-}"
ADVERTISED_ROUTE="${ADVERTISED_ROUTE:-192.168.1.0/24}"
MAGICDNS_NAME="${MAGICDNS_NAME:-}"

OUT="${TEXTFILE_DIR}/homelab.prom"
TMP="$(mktemp "${OUT}.XXXXXX")"
trap 'rm -f "${TMP}"' EXIT

emit() { printf '%s\n' "$1" >> "${TMP}"; }

# --- Tailscale ---------------------------------------------------------------
ts_json="$(tailscale status --json 2>/dev/null || echo '{}')"
ts_summary="$(
  printf '%s' "${ts_json}" | ADVERTISED_ROUTE="${ADVERTISED_ROUTE}" python3 -c '
import json, os, sys
try:
    status = json.load(sys.stdin)
except ValueError:
    status = {}
node = status.get("Self") or {}
routes = node.get("PrimaryRoutes") or []
addresses = [a for a in (node.get("TailscaleIPs") or []) if ":" not in a]
print(
    1 if status.get("BackendState") == "Running" else 0,
    1 if os.environ["ADVERTISED_ROUTE"] in routes else 0,
    addresses[0] if addresses else "none",
)'
)"
read -r backend approved tsip <<<"${ts_summary}"

emit '# HELP homelab_tailscale_backend_running Tailscale backend is in the Running state.'
emit '# TYPE homelab_tailscale_backend_running gauge'
emit "homelab_tailscale_backend_running ${backend}"
emit '# HELP homelab_tailscale_route_approved Advertised subnet route is approved in the tailnet.'
emit '# TYPE homelab_tailscale_route_approved gauge'
emit "homelab_tailscale_route_approved{route=\"${ADVERTISED_ROUTE}\"} ${approved}"
emit '# HELP homelab_tailscale_node_address_info Current tailnet IPv4 address of this node.'
emit '# TYPE homelab_tailscale_node_address_info gauge'
emit "homelab_tailscale_node_address_info{address=\"${tsip}\"} 1"

# --- API server certificate --------------------------------------------------
# A rebuild gives the node a new tailnet address. If the certificate still
# covers only the old one, every remote kubectl fails TLS verification.
cert_ok=0
if [[ "${tsip}" != "none" ]]; then
  sans="$(echo | openssl s_client -connect "127.0.0.1:6443" 2>/dev/null \
    | openssl x509 -noout -text 2>/dev/null \
    | grep -A1 'Subject Alternative Name' || true)"
  if grep -q "IP Address:${tsip}" <<<"${sans}"; then
    if [[ -z "${MAGICDNS_NAME}" ]] || grep -q "DNS:${MAGICDNS_NAME}" <<<"${sans}"; then
      cert_ok=1
    fi
  fi
fi
emit '# HELP homelab_apiserver_cert_covers_tailnet API server certificate covers the current tailnet address.'
emit '# TYPE homelab_apiserver_cert_covers_tailnet gauge'
emit "homelab_apiserver_cert_covers_tailnet ${cert_ok}"

# --- BookBuddy generation worker ---------------------------------------------
timer_active=0
if systemctl is-active --quiet bookbuddy-worker.timer; then timer_active=1; fi
worker_result="$(systemctl show -p Result --value bookbuddy-worker.service 2>/dev/null || echo unknown)"
worker_ok=0
if [[ "${worker_result}" == "success" ]]; then worker_ok=1; fi
emit '# HELP homelab_bookbuddy_worker_timer_active BookBuddy generation worker timer is installed and active.'
emit '# TYPE homelab_bookbuddy_worker_timer_active gauge'
emit "homelab_bookbuddy_worker_timer_active ${timer_active}"
emit '# HELP homelab_bookbuddy_worker_last_run_ok Last BookBuddy worker run finished successfully.'
emit '# TYPE homelab_bookbuddy_worker_last_run_ok gauge'
emit "homelab_bookbuddy_worker_last_run_ok ${worker_ok}"

# --- Sonarr quality guardrails -----------------------------------------------
# Both of these silently reverted to permissive defaults on the rebuild and are
# what let a single season reach 50GB.
uncapped=-1
off_profile=-1
if [[ -n "${SONARR_API_KEY}" ]]; then
  sonarr_get() {
    curl -sfk --max-time 15 \
      -H "Host: ${SONARR_HOST}" \
      -H "X-Api-Key: ${SONARR_API_KEY}" \
      "https://127.0.0.1/api/v3/$1" 2>/dev/null || true
  }
  definitions="$(sonarr_get qualitydefinition)"
  profiles="$(sonarr_get qualityprofile)"
  series="$(sonarr_get series)"
  if [[ -n "${definitions}" && -n "${profiles}" && -n "${series}" ]]; then
    payload="$(
      SONARR_DEFINITIONS="${definitions}" \
      SONARR_PROFILES="${profiles}" \
      SONARR_SERIES="${series}" \
      python3 -c '
import json, os
definitions = json.loads(os.environ["SONARR_DEFINITIONS"])
profiles = json.loads(os.environ["SONARR_PROFILES"])
series = json.loads(os.environ["SONARR_SERIES"])
wanted = os.environ["SONARR_PROFILE"]
# HD or better with no ceiling is the condition that allows oversized grabs.
uncapped = sum(
    1
    for d in definitions
    if d.get("maxSize") is None and d["quality"].get("resolution", 0) >= 720
)
target = next((p["id"] for p in profiles if p["name"] == wanted), None)
off = sum(1 for s in series if s.get("qualityProfileId") != target)
print(uncapped, off)
'
    )"
    read -r uncapped off_profile <<<"${payload}"
  fi
fi
emit '# HELP homelab_sonarr_quality_definitions_uncapped HD-or-better Sonarr qualities with no maximum size (-1 when unknown).'
emit '# TYPE homelab_sonarr_quality_definitions_uncapped gauge'
emit "homelab_sonarr_quality_definitions_uncapped ${uncapped}"
emit '# HELP homelab_sonarr_series_off_managed_profile Series not on the managed quality profile (-1 when unknown).'
emit '# TYPE homelab_sonarr_series_off_managed_profile gauge'
emit "homelab_sonarr_series_off_managed_profile{profile=\"${SONARR_PROFILE}\"} ${off_profile}"

emit '# HELP homelab_metrics_last_run_timestamp_seconds When this exporter last wrote its metrics.'
emit '# TYPE homelab_metrics_last_run_timestamp_seconds gauge'
emit "homelab_metrics_last_run_timestamp_seconds $(date +%s)"

chmod 0644 "${TMP}"
mv "${TMP}" "${OUT}"
trap - EXIT
