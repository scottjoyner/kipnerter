# Quarantine FIREWALL ONLY. There is intentionally no Droplet here.
# Apply only under separate owner authorization; no CI apply and no live host writes.
terraform {
  required_version = ">= 1.8.0"

  required_providers {
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "~> 2.96"
    }
  }
}

variable "digitalocean_token" {
  description = "Owner-scoped DO API token. Supply from protected environment, never commit."
  type        = string
  sensitive   = true
}

provider "digitalocean" {
  token = var.digitalocean_token
}

locals {
  quarantine_tag  = "kp-dr-quarantine-20261018-250354430"
  quarantine_name = "kp-dr-deny-all-20261018-250354430"
}

resource "digitalocean_tag" "quarantine" {
  name = local.quarantine_tag
}

resource "digitalocean_firewall" "quarantine" {
  name = local.quarantine_name
  tags = [digitalocean_tag.quarantine.name]

  # EXPLICIT deny across IPv4/IPv6 and every IP protocol/port.
  # DigitalOcean combines allows from multiple attached firewalls;
  # a rule-free firewall is insufficient if another allows traffic.
  # Deny rules override those external allowances.
  inbound_rule {
    protocol         = "all"
    action           = "deny"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "all"
    action                = "deny"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  lifecycle {
    prevent_destroy = true
  }
}

output "firewall_id" {
  value = digitalocean_firewall.quarantine.id
}

output "quarantine_tag" {
  value = digitalocean_tag.quarantine.name
}

output "firewall_status" {
  value = digitalocean_firewall.quarantine.status
}
