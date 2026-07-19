# Wake Console

Internal web control that sends a Wake-on-WLAN magic packet to the fixed
`WNWSLAB01` Intel AX201 Wi-Fi adapter. The browser cannot supply or change the
target MAC address or broadcast address.

The Kubernetes deployment uses the K3s node network so the UDP broadcast leaves
on the physical `192.168.1.0/24` LAN. Access is restricted to that LAN at the
Ingress and protected with HTTPS, host and origin validation, a same-site CSRF
token, and an application rate limit.

Run the tests from this directory:

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
```

