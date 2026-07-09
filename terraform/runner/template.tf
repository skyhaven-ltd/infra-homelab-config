# Proxmox serves its template mirror over plain HTTP only (TLS is not offered on
# download.proxmox.com), so the sha512 pin is what makes this download safe rather
# than a nicety. Both values come from the PVE 8 appliance index:
#   http://download.proxmox.com/images/aplinfo-pve-8.dat
# Pinned per §1.16 — never pull a rolling "latest" template.
resource "proxmox_download_file" "ubuntu_lxc" {
  content_type       = "vztmpl"
  datastore_id       = var.template_storage
  node_name          = var.proxmox_node
  url                = "http://download.proxmox.com/images/system/ubuntu-24.04-standard_24.04-2_amd64.tar.zst"
  file_name          = "ubuntu-24.04-standard_24.04-2_amd64.tar.zst"
  checksum           = "45c2978e6b97fe292ada95fe06834276015e5739a594db4de2fdfd830fa0c37942e8ae118fc1e32ffd9154b3f9378b592738b668ea3957db41f2907b86f219de"
  checksum_algorithm = "sha512"
}
