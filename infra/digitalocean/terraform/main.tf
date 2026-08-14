locals {
  common_tags = ["kipnerter", "production", "managed-by-terraform"]
}

resource "digitalocean_droplet" "prod" {
  name     = "kipnerter-prod-01"
  region   = var.region
  size     = var.droplet_size
  image    = var.droplet_image
  ssh_keys = var.ssh_key_fingerprints
  tags     = local.common_tags

  monitoring = true
  backups    = true

  lifecycle {
    prevent_destroy = true
  }
}

resource "digitalocean_firewall" "prod" {
  name        = "kipnerter-prod"
  droplet_ids = [digitalocean_droplet.prod.id]

  inbound_rule {
    protocol         = "tcp"
    port_range       = "80"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  inbound_rule {
    protocol         = "tcp"
    port_range       = "443"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  dynamic "inbound_rule" {
    for_each = length(var.admin_source_cidrs) > 0 ? [1] : []
    content {
      protocol         = "tcp"
      port_range       = "22"
      source_addresses = var.admin_source_cidrs
    }
  }

  outbound_rule {
    protocol              = "tcp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "udp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "icmp"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }
}

resource "digitalocean_domain" "kipnerter" {
  count = var.manage_dns ? 1 : 0
  name  = var.domain
}

resource "digitalocean_record" "apex" {
  count  = var.manage_dns ? 1 : 0
  domain = digitalocean_domain.kipnerter[0].id
  type   = "A"
  name   = "@"
  value  = digitalocean_droplet.prod.ipv4_address
  ttl    = 300
}

resource "digitalocean_record" "api" {
  count  = var.manage_dns ? 1 : 0
  domain = digitalocean_domain.kipnerter[0].id
  type   = "A"
  name   = "api"
  value  = digitalocean_droplet.prod.ipv4_address
  ttl    = 300
}

resource "digitalocean_record" "www" {
  count  = var.manage_dns ? 1 : 0
  domain = digitalocean_domain.kipnerter[0].id
  type   = "CNAME"
  name   = "www"
  value  = "${var.domain}."
  ttl    = 300
}
