# Production on AWS: one EC2 server running k3s, Postgres on the same host outside Kubernetes, a fixed public IP,
# and Amazon SES for the login e-mails. About USD 23 a month in eu-west-1 (t3.small, 30 GB gp3, one public IPv4).
#
#   aws login                                   # short-lived credentials for your IAM admin user
#   terraform init
#   terraform apply                             # prints the DNS records to add at the registrar
#
# SSH and the Kubernetes API are open only to the IP address you run `terraform apply` from. When your IP changes,
# run `terraform apply` again.

terraform {
  required_version = ">= 1.5"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 5.70" }
    http   = { source = "hashicorp/http", version = "~> 3.4" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { project = "techjobsradar" }
  }
}

variable "region" { default = "eu-west-1" }
variable "domain" { default = "techjobsradar.nl" }
variable "instance_type" {
  description = "t3.small (2 vCPU, 2 GB, allowed on the Free plan) runs k3s, Postgres, the API and one crawl worker"
  default     = "t3.small"
}
variable "ssh_public_key_path" { default = "~/.ssh/id_ed25519.pub" }
variable "test_recipient" {
  description = "While SES is in its sandbox it only delivers to verified addresses; put your own here to test login"
  default     = ""
}

data "http" "my_ip" { url = "https://checkip.amazonaws.com" }
locals { admin_cidr = "${chomp(data.http.my_ip.response_body)}/32" }

data "aws_vpc" "default" { default = true }

data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical
  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }
}

resource "random_password" "postgres" {
  length  = 32
  special = false
}

resource "aws_key_pair" "radar" {
  key_name   = "radar"
  public_key = file(pathexpand(var.ssh_public_key_path))
}

resource "aws_security_group" "radar" {
  name        = "radar"
  description = "Tech Jobs Radar: web to everyone, SSH and Kubernetes API to the admin only"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "HTTP (Lets Encrypt challenge and redirect)"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    description = "SSH from the admin"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [local.admin_cidr]
  }
  ingress {
    description = "Kubernetes API from the admin"
    from_port   = 6443
    to_port     = 6443
    protocol    = "tcp"
    cidr_blocks = [local.admin_cidr]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# Allocated before the server so its address can go into the k3s certificate
resource "aws_eip" "radar" {
  domain = "vpc"
}

resource "aws_instance" "radar" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.instance_type
  key_name               = aws_key_pair.radar.key_name
  vpc_security_group_ids = [aws_security_group.radar.id]
  user_data = templatefile("${path.module}/cloud-init.yaml", {
    public_ip         = aws_eip.radar.public_ip
    postgres_password = random_password.postgres.result
  })

  root_block_device {
    volume_type = "gp3"
    volume_size = 30
    encrypted   = true
  }
  metadata_options {
    http_tokens = "required" # IMDSv2 only
  }
  tags = { Name = "radar-k3s" }

  # never replace the server (and its database) because a newer Ubuntu image appeared or cloud-init was edited
  lifecycle {
    ignore_changes = [ami, user_data]
  }
}

resource "aws_eip_association" "radar" {
  instance_id   = aws_instance.radar.id
  allocation_id = aws_eip.radar.id
}

# ---------- e-mail (login links) ----------
resource "aws_sesv2_email_identity" "domain" {
  email_identity = var.domain
}

resource "aws_sesv2_email_identity" "test_recipient" {
  count          = var.test_recipient == "" ? 0 : 1
  email_identity = var.test_recipient
}

# SMTP credentials that can only send mail from the domain
resource "aws_iam_user" "smtp" {
  name = "radar-ses-smtp"
}

resource "aws_iam_user_policy" "smtp" {
  name = "send-login-mail"
  user = aws_iam_user.smtp.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["ses:SendRawEmail", "ses:SendEmail"]
      Resource = "*"
      Condition = {
        StringLike = { "ses:FromAddress" = "*@${var.domain}" }
      }
    }]
  })
}

resource "aws_iam_access_key" "smtp" {
  user = aws_iam_user.smtp.name
}

# ---------- outputs ----------
output "server_ip" { value = aws_eip.radar.public_ip }

output "ssh" { value = "ssh ubuntu@${aws_eip.radar.public_ip}" }

output "dns_records" {
  description = "Add these at the registrar (GoDaddy: My Products > techjobsradar.nl > DNS)"
  value = concat(
    [
      { type = "A", name = "@", value = aws_eip.radar.public_ip },
      { type = "TXT", name = "_dmarc", value = "v=DMARC1; p=none;" },
    ],
    [for t in aws_sesv2_email_identity.domain.dkim_signing_attributes[0].tokens :
      { type = "CNAME", name = "${t}._domainkey", value = "${t}.dkim.amazonses.com" }]
  )
}

output "database_url_in_cluster" {
  description = "For the radar-db Kubernetes Secret: pods reach Postgres on the node's private address"
  value       = "postgresql+psycopg://radar:${random_password.postgres.result}@${aws_instance.radar.private_ip}:5432/radar"
  sensitive   = true
}

output "database_url_via_tunnel" {
  description = "From the laptop through `ssh -N -L 5433:localhost:5432 ubuntu@<server_ip>`, for `radar copy-db`"
  value       = "postgresql+psycopg://radar:${random_password.postgres.result}@localhost:5433/radar"
  sensitive   = true
}

output "smtp_user" {
  value     = aws_iam_access_key.smtp.id
  sensitive = true
}

output "smtp_password" {
  value     = aws_iam_access_key.smtp.ses_smtp_password_v4
  sensitive = true
}
