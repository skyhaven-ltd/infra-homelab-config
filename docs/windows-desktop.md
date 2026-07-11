# Windows desktop

`lnsvrdesktop01` is a Windows 11 Pro desktop for remote Codex work. Terraform manages its Proxmox hardware in `terraform/windows-desktop`; Windows installation and user-scoped authentication remain operator actions.

## Allocation

| Property | Value |
| --- | --- |
| VM ID | `400` |
| LAN address | `192.168.1.4/24` |
| CPU | 4 vCPU |
| Memory | 4 GiB minimum, 6 GiB maximum |
| Disk | 64 GiB thin-provisioned |
| Firmware | UEFI Secure Boot with TPM 2.0 |

The allocation assumes the k3s VM is reduced from 16 GiB to 12 GiB and includes the 2 GiB GitHub Actions LXC. Before the change, Proxmox RRD data showed 8.26 GiB average and 9.32 GiB maximum k3s guest memory over the available month, while Kubernetes showed a 7.05 GiB current working set.

## Prerequisites

Upload a licensed Windows 11 ISO to Proxmox as `local:iso/Windows11.iso`. Supply the Proxmox token through `TF_VAR_proxmox_api_token` and load the Proxmox SSH key into the SSH agent.

## Provision

```powershell
make windows-plan
make windows-apply
```

Open the Proxmox console and install Windows 11 Pro onto the 64 GiB disk. Complete setup with the account that will run ChatGPT and Codex.

## Configure

Copy `scripts/windows-desktop/Bootstrap-WindowsDesktop.ps1` to the desktop and run it from an elevated PowerShell session. It configures the reserved address, enables Remote Desktop, installs Git, GitHub CLI, Visual Studio Code, Tailscale, and ChatGPT, then installs the shared `AGENTS.md` and skills from `infra-developer-config`.

Authenticate Tailscale, GitHub CLI, and ChatGPT interactively after the script finishes. Restrict remote access to Tailscale; do not forward RDP from the router.

Install the VirtIO balloon driver from the current stable `virtio-win.iso` after Windows setup. Until the driver is installed, Proxmox may retain the full 6 GiB allocation.
