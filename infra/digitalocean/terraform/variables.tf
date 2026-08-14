variable "digitalocean_token" {
  description = "DigitalOcean API token. Supply via TF_VAR_digitalocean_token."
  type        = string
  sensitive   = true
}

variable "project_name" {
  type    = string
  default = "kipnerter"
}

variable "region" {
  type    = string
  default = "nyc3"
}

variable "droplet_size" {
  type    = string
  default = "s-2vcpu-4gb"
}

variable "droplet_image" {
  type    = string
  default = "ubuntu-24-04-x64"
}

variable "ssh_key_fingerprints" {
  description = "DigitalOcean SSH key fingerprints permitted on newly created hosts."
  type        = list(string)
  default     = []
}

variable "admin_source_cidrs" {
  description = "Optional public CIDRs allowed to reach SSH. Prefer Tailscale and leave this empty after bootstrap."
  type        = list(string)
  default     = []
}

variable "manage_dns" {
  description = "False during inventory/migration. Enable only after existing DNS records have been imported and reviewed."
  type        = bool
  default     = false
}

variable "domain" {
  type    = string
  default = "kipnerter.com"
}
