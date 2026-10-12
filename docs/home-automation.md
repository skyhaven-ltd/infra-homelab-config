# Home automation

Mosquitto, Zigbee2MQTT and Home Assistant Container run in the
`home-automation` namespace, with one replica and a persistent volume each.

| Service | Version | Access |
| --- | --- | --- |
| Home Assistant | 2026.9.1 | https://homeassistant.lab.skyhaven.ltd |
| Zigbee2MQTT | 2.14.1 | https://zigbee2mqtt.lab.skyhaven.ltd |
| Mosquitto | 2.1.2 | `mosquitto.home-automation.svc.cluster.local:1883`, inside the cluster |
| SMLIGHT SLZB-06U | CC2652P coordinator | http://192.168.1.121 |

Images are pinned by digest. HTTPS ingress permits `192.168.1.0/24` and
`100.64.0.0/10`, following the other private applications. Use Pi-hole DNS
on the LAN or the existing Tailscale subnet route remotely. Do not add router
port forwards. Home Assistant also listens on `192.168.1.3:8123`; its host
network permits local discovery without a privileged container or USB access.

## First use

1. Open Home Assistant and create your owner account. Complete location and
   household setup there.
2. The MQTT integration is already connected to broker
   `mosquitto.home-automation.svc.cluster.local` on port `1883`. Its username
   is `homeautomation`; retrieve its password from the Kubernetes Secret below.
   Broker TLS is off because the broker is internal to the cluster.
3. Open Zigbee2MQTT. Enable **Permit join** only when ready to pair, reset the
   intended device into pairing mode, and close joining afterwards. Start with
   mains-powered devices before battery sensors. Reset Hue bulbs only when
   ready to remove them from their existing Hue setup.
4. Confirm the device appears in both interfaces and test on/off control.
   Create room assignments and automations in Home Assistant after pairing.

Copy the MQTT password to the Windows clipboard from PowerShell:

```powershell
wsl -d Ubuntu-24.04 -- bash -lc 'kubectl get secret mqtt-credentials -n home-automation -o jsonpath="{.data.MQTT_PASSWORD}" | base64 -d | clip.exe'
```

The password is randomly generated and stored in Kubernetes; only the
SealedSecret ciphertext is in Git. The Sealed Secrets controller must retain
its private sealing key to decrypt this file after a cluster rebuild. If that
key is lost, generate replacement credentials, seal them for the new cluster,
restart Mosquitto and Zigbee2MQTT, and update the Home Assistant integration.

Home Assistant Container has no Supervisor or add-on store. Configure MQTT as
an integration; do not install a second broker or configure ZHA against the
same coordinator. Zigbee2MQTT publishes Home Assistant discovery messages.

## Windows PC sleep control

HASS.Agent can expose a Windows sleep command through the existing MQTT
integration. The `mosquitto-lan` Service makes the authenticated broker
available to LAN clients at `192.168.1.3:31883`. This endpoint uses plain MQTT;
keep it on the trusted LAN or Tailscale network and do not forward it through
the router. The original cluster-internal endpoint remains unchanged.

For WNWSLAB01, configure HASS.Agent with only a button command of type
`WinformsSleepCommand`, named `Sleep PC`, with entity name `wnwslab01_sleep`.
This uses Windows suspend, with hibernation and forced suspension disabled.
On WNWSLAB01, the Windows scheduled task `HASS.Agent receiver` starts the
client at sign-in and retries every minute if it exits. It runs interactively
as the signed-in user, ignores overlapping starts, has no execution time limit,
and does not wake the PC. It replaces the application's HKCU Run entry.
The client must be running and MQTT-connected to receive the command; this
recovery handles process exits, not a running client with a stuck connection.
To deliberately keep the receiver stopped, disable this task first.
Command discovery uses the existing MQTT integration
and does not require the HASS.Agent custom integration, HACS, or a subscription.
Keep MQTT credentials in the local application settings, never in Git.

The existing `switch.wnwslab01` sends Wake-on-LAN to the Ethernet adapter.
The custom Overview at `/home-dashboard/home` displays this entity as a switch
and is the system and owner-account default dashboard. ON sends Wake-on-LAN;
OFF presses `button.wnwslab01_wnwslab01_sleep` through the switch's `turn_off`
action. The live persistent configuration and repository seed contain this
mapping. HASS.Agent's MQTT device belongs to Office. The dashboard also
contains the existing scenes, weather, room lighting, and TV remote.
Verify an actual sleep/wake cycle only when the PC user is ready to interrupt
active work.

## Coordinator address and radio

Reserve DHCP address `192.168.1.121` for Ethernet MAC `9E:13:9E:34:88:F8` in
the router. DHCP was enabled on discovery; a router reservation is still
required to keep this endpoint stable. The radio connection is
`tcp://192.168.1.121:6638`, adapter `zstack`, baud rate `115200`, without
hardware flow control.

The initial Zigbee channel is 25. The local Wi-Fi channel has not been
measured; confirm interference conditions before pairing the whole house.
Keep the external antenna fitted and locate the coordinator clear of the rack.
Radio and coordinator firmware were left at their installed versions.

## Configuration and persistence

ArgoCD application manifests are in `kubernetes/argocd-apps/app-mosquitto.yaml`,
`app-zigbee2mqtt.yaml` and `app-homeassistant.yaml`, targeting `main`.
The root application discovers them once merged. All three use the shared
`home-automation` namespace. Mosquitto owns the shared MQTT SealedSecret.

Home Assistant and Zigbee2MQTT copy their initial configuration from a
ConfigMap only when the persistent configuration file does not exist. Later
UI changes, network keys, paired devices and automations survive rollouts.
Editing these seed files does not overwrite an existing installation: update
the persistent configuration through the application or explicitly migrate it
with the workload stopped. Never replace a running Zigbee network's generated
identifiers with `GENERATE`.
Home Assistant 2026.9 stores HTTP settings in `/config/.storage/http`.
The initial `http.json` seeds the stable configuration only when that store
does not exist. An `http:` YAML block instead triggers migration into a
five-minute trial, which reverts without administrator confirmation and breaks
ingress access. Change HTTP settings later in **Settings → System → Network**
and confirm them after the restart.

| Claim | Container path | Contents |
| --- | --- | --- |
| `mosquitto-data` | `/mosquitto/data` | Retained MQTT messages and broker persistence |
| `zigbee2mqtt-data` | `/app/data` | Configuration, network identifiers, device database and `coordinator_backup.json` |
| `homeassistant-config` | `/config` | Account, integrations, dashboards, automations and database |

All claims use the existing `local-path` storage under `/srv/appdata/local-path`.
The [nightly appdata backup](backup-restore.md) includes this directory and
uploads to OneDrive. A NAS backup destination and restore test remain separate
work. The live archive is not an application-quiesced database backup.
On 10 September 2026 the latest backup service run reported `Result=timeout`
during its OneDrive post-processing step. Successful off-node protection for
these new volumes has not yet been verified.

## Verification

Run from Ubuntu WSL:

```bash
kubectl get pods,pvc,certificate -n home-automation
kubectl logs -n home-automation deployment/zigbee2mqtt -c zigbee2mqtt --tail=30
kubectl exec -n home-automation deployment/homeassistant -c homeassistant -- python -m homeassistant --script check_config --config /config
```

Zigbee2MQTT should report a connected MQTT server and a started coordinator.
The bridge health check should return `healthy: true`; joining should be off
except during pairing. HTTPS should have a valid certificate at both hostnames.

References: [SMLIGHT configuration](https://smlight.tech/manual/slzb-06/guide/installation/),
[Zigbee2MQTT adapter settings](https://www.zigbee2mqtt.io/guide/configuration/adapter-settings.html),
[MQTT settings](https://www.zigbee2mqtt.io/guide/configuration/mqtt.html),
[Home Assistant Container](https://www.home-assistant.io/installation/linux/).
