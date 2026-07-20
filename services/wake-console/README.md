# Wake Console

Internal web control that sends a Wake-on-WLAN magic packet to the fixed
`WNWSLAB01` Intel AX201 Wi-Fi adapter. The browser cannot supply or change the
target MAC address or broadcast address.

The Kubernetes deployment uses the K3s node network so the UDP broadcast leaves
on the physical `192.168.1.0/24` LAN. Access is restricted at the Ingress to
that LAN and the private Tailscale `100.64.0.0/10` range. The application is
protected with HTTPS, host and origin validation, a same-site CSRF token, and
an application rate limit.

When `WAKE_UNICAST_ADDRESS` is set, each magic packet is also sent unicast to
the target's own IP. Broadcast frames are decrypted with the Wi-Fi group key,
which a sleeping WPA3 adapter can miss when the AP rotates it (a GTK rekey),
so broadcast-only wakes stop working after roughly an hour of sleep. The
unicast copy uses the pairwise key the adapter keeps, so it keeps waking the
host. Pin the unicast address with a DHCP reservation for the target's MAC.

Run the tests from this directory:

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
```

