# One Hetzner Cloud server running k3s. Postgres runs on the same host outside Kubernetes (see cloud-init),
# which keeps the database off the cluster's storage layer while staying on one cheap machine.
#
#   export HCLOUD_TOKEN=...            # Hetzner Cloud API token (read/write)
#   terraform init && terraform apply -var ssh_public_key="$(cat ~/.ssh/id_ed25519.pub)"
#   scp root@<ip>:/etc/rancher/k3s/k3s.yaml ~/.kube/radar.yaml   # then replace 127.0.0.1 with <ip>

terraform {
  required_version = ">= 1.5"
  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "~> 1.48"
    }
  }
}

provider "hcloud" {}

variable "server_type" {
  description = "cx22 (2 vCPU, 4 GB) is enough for the NL radar; cpx31 for the Europe-wide crawl"
  default     = "cx22"
}
variable "location" { default = "nbg1" }
variable "ssh_public_key" { type = string }
variable "postgres_password" {
  type      = string
  sensitive = true
  default   = "change-me"
}
variable "allowed_ssh_cidr" { default = "0.0.0.0/0" }

resource "hcloud_ssh_key" "radar" {
  name       = "radar"
  public_key = var.ssh_public_key
}

resource "hcloud_firewall" "radar" {
  name = "radar"
  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "22"
    source_ips = [var.allowed_ssh_cidr]
  }
  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "80"
    source_ips = ["0.0.0.0/0", "::/0"]
  }
  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "443"
    source_ips = ["0.0.0.0/0", "::/0"]
  }
  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "6443" # kube-apiserver; restrict to your IP once kubeconfig is fetched
    source_ips = [var.allowed_ssh_cidr]
  }
}

resource "hcloud_server" "radar" {
  name         = "radar-k3s"
  server_type  = var.server_type
  image        = "ubuntu-24.04"
  location     = var.location
  ssh_keys     = [hcloud_ssh_key.radar.id]
  firewall_ids = [hcloud_firewall.radar.id]
  user_data = templatefile("${path.module}/cloud-init.yaml", {
    postgres_password = var.postgres_password
  })
}

output "server_ip" { value = hcloud_server.radar.ipv4_address }
output "database_url" {
  value     = "postgresql+psycopg://radar:${var.postgres_password}@${hcloud_server.radar.ipv4_address}:5432/radar"
  sensitive = true
}
output "next_steps" {
  value = <<-EOT
    1. scp root@${hcloud_server.radar.ipv4_address}:/etc/rancher/k3s/k3s.yaml ~/.kube/radar.yaml
       sed -i 's/127.0.0.1/${hcloud_server.radar.ipv4_address}/' ~/.kube/radar.yaml && export KUBECONFIG=~/.kube/radar.yaml
    2. Point your DNS A record at ${hcloud_server.radar.ipv4_address}
    3. helm upgrade --install radar deploy/helm/radar -n radar --create-namespace \
         --set ingress.host=YOUR_DOMAIN --set database.url="$(terraform output -raw database_url)"
  EOT
}
