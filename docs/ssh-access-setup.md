# SSH Access Setup — Client → K8S & Proxmox

How to let **any client machine** SSH into the two homelab servers, even when you
have **no local admin** on the client.

| Target | Host | IP | Admin user | Automation user |
|---|---|---|---|---|
| K8S server (`lnsvrk8s01`) | k8s | `192.168.1.3` | `liam` | `ops` |
| Proxmox host (`lnproxlab01`) | proxmox | `192.168.1.2` | `liam` | `root` |

> **Direction:** clients connect **in**. The private key stays on the client and
> never moves. Only each client's **public** key lands on the servers'
> `authorized_keys`. One keypair per client machine.

---

## 0. Canonical method — Ansible role `users` (do this first)

Access is **managed as code** by `ansible/roles/users`, applied to both hosts via
`ansible/site.yml` (play `hosts: all`). Prefer this over the manual steps below;
the manual flow (§1–§8) is the fallback for a first-contact host or a locked-out
box.

**Model (decided 2026-07-06):**
- Same admin user **`liam`** on both hosts, in group `sudo`.
- **SSH key = primary auth.** Every `*.pub` in
  `ansible/roles/users/files/authorized_keys.d/` is installed to `liam`.
- **Password auth kept ON** (`PasswordAuthentication yes`) so a brand-new client
  with no key can bootstrap in with the password, then add its own key.
- **Password lives in Bitwarden only.** Never in Git. Ansible sets it from a
  SHA-512 hash passed via the `LIAM_PASSWORD_HASH` env var at runtime; the
  plaintext is generated from the Bitwarden entry.

**Add a new client machine:**
1. On the client, generate a keypair (§1).
2. Commit its public key to `ansible/roles/users/files/authorized_keys.d/<client>.pub`.
3. Re-run:
   ```bash
   cd ansible
   ANSIBLE_HOST_KEY_CHECKING=False ansible-playbook -i inventory/hosts.yml site.yml -t users
   ```

**Set / rotate the Bitwarden password** (enables sudo + password bootstrap):
```bash
cd ansible
export LIAM_PASSWORD_HASH="$(mkpasswd -m sha-512)"   # paste Bitwarden password; needs `whois` pkg (or: openssl passwd -6)
ANSIBLE_HOST_KEY_CHECKING=False ansible-playbook -i inventory/hosts.yml site.yml -t users
unset LIAM_PASSWORD_HASH
```

**Bootstrapping a host that has no key yet:** with password auth on, run the
playbook with `-k` (`--ask-pass`) and the Bitwarden password, or seed the first
key out-of-band via the Proxmox guest agent:
`qm guest exec <vmid> -- bash -c 'echo "<pubkey>" >> /home/liam/.ssh/authorized_keys'`.

---

## Why no admin is needed

- `ssh-keygen` writes only into your own `~/.ssh` — no elevation.
- Appending a public key to a server's `authorized_keys` uses your existing
  server login — no admin on the *client*.
- The OpenSSH **client** ships built-in on Windows 10/11 and every modern Linux,
  so nothing to install.
- The only step that *would* need admin is starting the `ssh-agent` **service**
  on Windows (optional convenience). A no-admin fallback is given in §5.

---

## 1. Generate a keypair on the client

Run **once per client machine**. Pick the block matching the client OS.

### Windows (PowerShell) — no admin

```powershell
ssh-keygen -t ed25519 -C "$env:USERNAME@$env:COMPUTERNAME" -f "$env:USERPROFILE\.ssh\id_ed25519"
```

### Linux / macOS / WSL

```bash
ssh-keygen -t ed25519 -C "$(whoami)@$(hostname)" -f ~/.ssh/id_ed25519
```

- Accept the default path. Set a passphrase if the machine is shared; leave empty
  for unattended use.
- The `-C` comment stamps *which client* the key is — makes later revocation easy.
- Produces two files: `id_ed25519` (**private — never share**) and
  `id_ed25519.pub` (**public — this is what you copy out**).

---

## 2. Copy the PUBLIC key to both servers

`ssh-copy-id` is the one-shot way. It appends your `.pub` to the server's
`~/.ssh/authorized_keys`, creating dirs with correct perms. It uses your existing
password login the first (and only) time.

### Linux / macOS / WSL client

```bash
ssh-copy-id -i ~/.ssh/id_ed25519.pub ops@192.168.1.3
ssh-copy-id -i ~/.ssh/id_ed25519.pub root@192.168.1.2
```

### Windows (PowerShell) — no `ssh-copy-id`, use this one-liner per target

```powershell
# K8S
type "$env:USERPROFILE\.ssh\id_ed25519.pub" | ssh ops@192.168.1.3 "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"

# Proxmox
type "$env:USERPROFILE\.ssh\id_ed25519.pub" | ssh root@192.168.1.2 "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
```

> **Proxmox note:** root's `~/.ssh/authorized_keys` is a symlink into
> `/etc/pve/priv/authorized_keys` (cluster-managed). Appending through the symlink
> as above is correct and survives reboots — do **not** replace the symlink.

You'll be prompted for the server password once per target. That's the last time.

---

## 3. Test key login

```bash
ssh ops@192.168.1.3    # should land you in with NO password prompt
ssh root@192.168.1.2
```

If it still asks for a password, jump to §6 Troubleshooting.

---

## 4. Optional — SSH config aliases (per client)

Saves typing IPs. Client-side only, no admin.

`~/.ssh/config` (Linux/WSL) or `%USERPROFILE%\.ssh\config` (Windows):

```
Host k8s
    HostName 192.168.1.3
    User ops
    IdentityFile ~/.ssh/id_ed25519

Host proxmox
    HostName 192.168.1.2
    User root
    IdentityFile ~/.ssh/id_ed25519
```

Then simply: `ssh k8s` / `ssh proxmox`.

---

## 5. Optional — remember passphrase without admin (Windows)

The Windows `ssh-agent` service needs admin to enable. No-admin fallback: run a
user-scoped agent in your shell session.

```powershell
# start an agent for this session and load the key
ssh-agent | Out-String   # informational
ssh-add "$env:USERPROFILE\.ssh\id_ed25519"
```

For WSL/Linux, add to `~/.bashrc`:

```bash
eval "$(ssh-agent -s)" >/dev/null
ssh-add ~/.ssh/id_ed25519 2>/dev/null
```

---

## 6. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Still prompted for password after §2 | `authorized_keys` perms wrong. On server: `chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys`. |
| `Permission denied (publickey)` | Wrong key offered. Force it: `ssh -i ~/.ssh/id_ed25519 ops@192.168.1.3 -v` and read the `-v` output. |
| `Too many authentication failures` | Agent offering many keys. Add `IdentitiesOnly yes` to the `~/.ssh/config` host block. |
| Windows `ssh` not found | Enable *OpenSSH Client* under Settings → Apps → Optional Features (no admin for per-user), or use WSL. |

---

## 7. Storing public keys in Git (recommended)

Public keys are **not secret**. Commit them so servers can be rebuilt without
re-collecting keys — fits this repo's GitOps model.

```
docs/../ssh/authorized_keys.d/
  <client-name>.pub
```

Add each client's `id_ed25519.pub` there. A future Ansible task / cloud-init can
render these into each server's `authorized_keys`. **Never** commit a private key
(`id_ed25519` with no `.pub`).

---

## 8. Hardening (after key login confirmed — do NOT skip verification)

> **Warning:** keep your current SSH session open and confirm a **new** key login
> works in a second terminal BEFORE disabling passwords, or you can lock yourself
> out.

On each server, edit `/etc/ssh/sshd_config`:

```
PubkeyAuthentication yes
PasswordAuthentication no
PermitRootLogin prohibit-password
```

Then reload:

```bash
sudo systemctl restart ssh     # k8s (Ubuntu: service is "ssh")
systemctl restart sshd         # proxmox (Debian: "sshd")
```

To revoke a client later: delete its line from the server's `authorized_keys`
(identify by the `-C` comment from §1).
