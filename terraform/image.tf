resource "proxmox_download_file" "ubuntu_noble" {
  content_type = "iso"
  datastore_id = var.iso_storage
  node_name    = var.proxmox_node
  url          = "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img"
  file_name    = "ubuntu-noble-cloudimg-amd64.img"
}
