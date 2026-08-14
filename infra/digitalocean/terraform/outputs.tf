output "prod_droplet_id" {
  value = digitalocean_droplet.prod.id
}

output "prod_ipv4" {
  value = digitalocean_droplet.prod.ipv4_address
}

output "prod_firewall_id" {
  value = digitalocean_firewall.prod.id
}

output "dns_management_enabled" {
  value = var.manage_dns
}
